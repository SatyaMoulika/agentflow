"""Persist bounded retry policy and retained node retry deadlines.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def _event_constraints(*, retries: bool) -> None:
    values = "'run.created', 'run.status_changed', 'node.created', 'node.status_changed'"
    nodes = "'node.created', 'node.status_changed'"
    if retries:
        values += ", 'node.retry_scheduled'"
        nodes += ", 'node.retry_scheduled'"
    for name, expression in (
        ("event_type", f"event_type IN ({values})"),
        ("event_node_context", f"(event_type IN ({nodes})) = (node_run_id IS NOT NULL)"),
    ):
        constraint = op.f(f"ck_execution_events_{name}")
        op.drop_constraint(constraint, "execution_events", type_="check")
        op.create_check_constraint(constraint, "execution_events", expression)


def upgrade() -> None:
    for column, default in (("retry_base_seconds", "5"), ("retry_max_seconds", "60")):
        op.add_column(
            "workflow_dispatches",
            sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text(default)),
        )
    op.create_check_constraint(
        op.f("ck_workflow_dispatches_retry_base_bounds"),
        "workflow_dispatches",
        "retry_base_seconds BETWEEN 1 AND 300",
    )
    op.create_check_constraint(
        op.f("ck_workflow_dispatches_retry_max_bounds"),
        "workflow_dispatches",
        "retry_max_seconds BETWEEN retry_base_seconds AND 3600",
    )
    op.create_table(
        "node_retries",
        sa.Column("node_run_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("node_run_id"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id"], ["workflow_dispatches.run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_node_retries_attempt",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("due_at >= created_at", name=op.f("ck_node_retries_due_after_creation")),
        sa.CheckConstraint(
            "resumed_at IS NULL OR resumed_at >= due_at",
            name=op.f("ck_node_retries_resume_after_due"),
        ),
        sa.CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at",
            name=op.f("ck_node_retries_cancel_after_creation"),
        ),
        sa.CheckConstraint(
            "resumed_at IS NULL OR cancelled_at IS NULL",
            name=op.f("ck_node_retries_one_resolution"),
        ),
    )
    op.create_index(
        "ix_node_retries_one_pending_run",
        "node_retries",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("resumed_at IS NULL AND cancelled_at IS NULL"),
    )
    _event_constraints(retries=True)
    op.execute("""
        CREATE FUNCTION guard_retry_policy() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF ROW(NEW.retry_base_seconds, NEW.retry_max_seconds) IS DISTINCT FROM
             ROW(OLD.retry_base_seconds, OLD.retry_max_seconds) THEN
            RAISE EXCEPTION 'Run retry policy is immutable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER workflow_dispatches_retry_policy BEFORE UPDATE ON workflow_dispatches "
        "FOR EACH ROW EXECUTE FUNCTION guard_retry_policy()"
    )
    op.execute("""
        CREATE FUNCTION guard_node_retry() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE parent_status text; eligible boolean;
        BEGIN
          IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
            RAISE EXCEPTION 'Retry history is retained' USING ERRCODE = '23514';
          END IF;
          EXECUTE format('SELECT status FROM %I.workflow_runs WHERE id=$1 FOR UPDATE',
            TG_TABLE_SCHEMA) INTO parent_status USING NEW.workflow_run_id;
          IF TG_OP = 'INSERT' THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.node_runs n '
              'JOIN %I.workflow_runs r ON r.id=n.workflow_run_id '
              'WHERE n.id=$1 AND n.workflow_run_id=$2 AND n.status=''failed'' '
              'AND n.error_code IN (''INTERNAL_FAILURE'', ''DEADLINE_EXCEEDED'') '
              'AND n.attempt_number < r.max_attempts AND NOT EXISTS '
              '(SELECT 1 FROM %I.node_runs later WHERE later.workflow_run_id=r.id '
              'AND later.node_id=n.node_id AND later.attempt_number>n.attempt_number))',
              TG_TABLE_SCHEMA, TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
              INTO eligible USING NEW.node_run_id, NEW.workflow_run_id;
            IF parent_status IS DISTINCT FROM 'running' OR NOT eligible
              OR NEW.resumed_at IS NOT NULL OR NEW.cancelled_at IS NOT NULL THEN
              RAISE EXCEPTION 'Attempt is not eligible for a retry' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;
          IF ROW(NEW.node_run_id, NEW.workflow_run_id, NEW.created_at, NEW.due_at)
             IS DISTINCT FROM ROW(OLD.node_run_id, OLD.workflow_run_id, OLD.created_at, OLD.due_at)
             OR OLD.resumed_at IS NOT NULL OR OLD.cancelled_at IS NOT NULL
             OR (NEW.resumed_at IS NULL AND NEW.cancelled_at IS NULL) THEN
            RAISE EXCEPTION 'Retry deadline and history are immutable' USING ERRCODE = '23514';
          END IF;
          IF NEW.resumed_at IS NOT NULL THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.node_runs old '
              'JOIN %I.node_runs next ON next.workflow_run_id=old.workflow_run_id '
              'AND next.node_id=old.node_id AND next.attempt_number=old.attempt_number+1 '
              'WHERE old.id=$1 AND next.status=''running'')', TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
              INTO eligible USING NEW.node_run_id;
            IF parent_status IS DISTINCT FROM 'running' OR NOT eligible THEN
              RAISE EXCEPTION 'Retry resume requires a new active attempt' USING ERRCODE = '23514';
            END IF;
          ELSIF parent_status IS DISTINCT FROM 'cancelled' THEN
            RAISE EXCEPTION 'Retry cancellation requires a cancelled run' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER node_retries_write_guard BEFORE INSERT OR UPDATE ON node_retries "
        "FOR EACH ROW EXECUTE FUNCTION guard_node_retry()"
    )
    op.execute(
        "CREATE TRIGGER node_retries_delete_guard BEFORE DELETE OR TRUNCATE ON node_retries "
        "FOR EACH STATEMENT EXECUTE FUNCTION guard_node_retry()"
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM node_retries) OR EXISTS
             (SELECT 1 FROM execution_events WHERE event_type='node.retry_scheduled') THEN
            RAISE EXCEPTION 'Cannot downgrade while retry history exists' USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    op.drop_table("node_retries")
    op.execute("DROP FUNCTION guard_node_retry()")
    op.execute("DROP TRIGGER workflow_dispatches_retry_policy ON workflow_dispatches")
    op.execute("DROP FUNCTION guard_retry_policy()")
    _event_constraints(retries=False)
    for name in ("retry_base_bounds", "retry_max_bounds"):
        op.drop_constraint(
            op.f(f"ck_workflow_dispatches_{name}"), "workflow_dispatches", type_="check"
        )
    op.drop_column("workflow_dispatches", "retry_max_seconds")
    op.drop_column("workflow_dispatches", "retry_base_seconds")
