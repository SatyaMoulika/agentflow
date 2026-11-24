"""Retain owner approval requests and atomic decision history.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | None = None
depends_on: str | None = None


def _events(approvals: bool) -> None:
    nodes = "'node.created', 'node.status_changed', 'node.retry_scheduled', "
    nodes += "'agent.checkpointed', 'agent.resumed'"
    if approvals:
        nodes += ", 'approval.requested', 'approval.resolved'"
    for name, expression in (
        ("event_type", f"event_type IN ('run.created', 'run.status_changed', {nodes})"),
        ("event_node_context", f"(event_type IN ({nodes})) = (node_run_id IS NOT NULL)"),
    ):
        name = op.f(f"ck_execution_events_{name}")
        op.drop_constraint(name, "execution_events", type_="check")
        op.create_check_constraint(name, "execution_events", expression)


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("node_run_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("note", sa.String(2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_dispatches.run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_approvals_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("node_run_id", name="uq_approvals_attempt"),
        sa.UniqueConstraint("workflow_run_id", "node_id", name="uq_approvals_run_node"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name=op.f("ck_approvals_status"),
        ),
        sa.CheckConstraint(
            "length(btrim(title)) BETWEEN 1 AND 200", name=op.f("ck_approvals_title_bounds")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_approvals_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (resolved_at IS NULL)",
            name=op.f("ck_approvals_resolution_required"),
        ),
        sa.CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= created_at",
            name=op.f("ck_approvals_resolution_after_creation"),
        ),
    )
    op.create_index(
        "ix_approvals_assignee_status_created",
        "approvals",
        ["assigned_to", "status", "created_at", "id"],
    )
    op.create_index(
        "ix_approvals_pending_expiry",
        "approvals",
        ["expires_at"],
        postgresql_where=sa.text("status='pending'"),
    )
    _events(True)
    op.execute("""
        CREATE FUNCTION guard_approval() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE eligible boolean;
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'Approval history is retained' USING ERRCODE = '23514';
          END IF;
          EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.workflow_runs r '
            'JOIN %I.workflows w ON w.id=r.workflow_id JOIN %I.node_runs n '
            'ON n.workflow_run_id=r.id WHERE r.id=$1 AND n.id=$2 AND n.node_id=$3 '
            'AND w.owner_id=$4)', TG_TABLE_SCHEMA, TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
            INTO eligible USING NEW.workflow_run_id, NEW.node_run_id, NEW.node_id, NEW.assigned_to;
          IF NOT eligible THEN
            RAISE EXCEPTION 'Approval owner or attempt mismatch' USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.status <> 'pending' OR NEW.resolved_at IS NOT NULL OR NEW.note IS NOT NULL THEN
              RAISE EXCEPTION 'Approval must begin pending' USING ERRCODE = '23514';
            END IF;
          ELSIF OLD.status <> 'pending' OR NEW.status = 'pending' OR
            ROW(NEW.id, NEW.workflow_run_id, NEW.node_run_id, NEW.node_id, NEW.assigned_to,
                NEW.title, NEW.created_at, NEW.expires_at) IS DISTINCT FROM
            ROW(OLD.id, OLD.workflow_run_id, OLD.node_run_id, OLD.node_id, OLD.assigned_to,
                OLD.title, OLD.created_at, OLD.expires_at) THEN
            RAISE EXCEPTION 'Approval request and decisions are immutable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER approvals_write_guard BEFORE INSERT OR UPDATE ON approvals "
        "FOR EACH ROW EXECUTE FUNCTION guard_approval()"
    )
    op.execute(
        "CREATE TRIGGER approvals_delete_guard BEFORE DELETE OR TRUNCATE ON approvals "
        "FOR EACH STATEMENT EXECUTE FUNCTION guard_approval()"
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM approvals) OR EXISTS
            (SELECT 1 FROM execution_events
             WHERE event_type IN ('approval.requested', 'approval.resolved')) THEN
            RAISE EXCEPTION 'Cannot downgrade retained approval history' USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    op.drop_table("approvals")
    op.execute("DROP FUNCTION guard_approval()")
    _events(False)
