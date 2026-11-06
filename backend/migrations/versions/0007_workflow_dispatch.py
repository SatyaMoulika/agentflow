"""Worker-owned workflow provenance and retained outbox deliveries.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def _outbox_guard(*, workflow_targets: bool) -> None:
    identity = "NEW.workflow_run_id" if workflow_targets else "NEW.id"
    old_identity = "OLD.workflow_run_id" if workflow_targets else "OLD.id"
    op.execute(f"""
        CREATE OR REPLACE FUNCTION guard_outbox_message() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
            RAISE EXCEPTION 'Outbox history is retained' USING ERRCODE = '23514';
          END IF;
          IF ROW(NEW.id, NEW.kind, NEW.created_at, {identity}) IS DISTINCT FROM
             ROW(OLD.id, OLD.kind, OLD.created_at, {old_identity})
             OR NEW.attempts < OLD.attempts OR OLD.published_at IS NOT NULL THEN
            RAISE EXCEPTION 'Invalid outbox history change' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)


def upgrade() -> None:
    op.create_table(
        "workflow_dispatches",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("dispatch_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "next_dispatch_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.PrimaryKeyConstraint("run_id"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "dispatch_count >= 1", name=op.f("ck_workflow_dispatches_positive_count")
        ),
    )
    op.create_index(
        "ix_workflow_dispatches_next_run", "workflow_dispatches", ["next_dispatch_at", "run_id"]
    )
    op.add_column("outbox_messages", sa.Column("workflow_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_outbox_messages_workflow_run_id_workflow_dispatches"),
        "outbox_messages",
        "workflow_dispatches",
        ["workflow_run_id"],
        ["run_id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(op.f("ck_outbox_messages_supported_kind"), "outbox_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_outbox_messages_supported_kind"),
        "outbox_messages",
        "kind IN ('transport_probe', 'workflow_run')",
    )
    op.create_check_constraint(
        op.f("ck_outbox_messages_workflow_target"),
        "outbox_messages",
        "(kind = 'workflow_run') = (workflow_run_id IS NOT NULL)",
    )
    op.create_index(
        "ix_outbox_messages_one_pending_workflow",
        "outbox_messages",
        ["workflow_run_id"],
        unique=True,
        postgresql_where=sa.text("workflow_run_id IS NOT NULL AND published_at IS NULL"),
    )
    _outbox_guard(workflow_targets=True)
    op.execute("""
        CREATE FUNCTION guard_workflow_dispatch() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE eligible boolean;
        BEGIN
          IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
            RAISE EXCEPTION 'Workflow dispatch history is retained' USING ERRCODE = '23514';
          END IF;
          IF TG_OP = 'INSERT' THEN
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.workflow_runs '
              'WHERE id = $1 AND status = ''queued'' AND revision = 0)', TG_TABLE_SCHEMA)
              INTO eligible USING NEW.run_id;
            IF NOT eligible OR NEW.dispatch_count <> 1 THEN
              RAISE EXCEPTION 'Workflow dispatch requires a fresh queued run'
                USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
          END IF;
          IF ROW(NEW.run_id, NEW.created_at) IS DISTINCT FROM ROW(OLD.run_id, OLD.created_at)
            OR NEW.dispatch_count < OLD.dispatch_count
            OR NEW.dispatch_count > OLD.dispatch_count + 1 THEN
            RAISE EXCEPTION 'Invalid workflow dispatch history change' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER workflow_dispatches_write_guard BEFORE INSERT OR UPDATE "
        "ON workflow_dispatches FOR EACH ROW EXECUTE FUNCTION guard_workflow_dispatch()"
    )
    op.execute(
        "CREATE TRIGGER workflow_dispatches_delete_guard BEFORE DELETE OR TRUNCATE "
        "ON workflow_dispatches FOR EACH STATEMENT EXECUTE FUNCTION guard_workflow_dispatch()"
    )


def downgrade() -> None:
    # Retained delivery history must never be silently converted or discarded.
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM workflow_dispatches) THEN
            RAISE EXCEPTION 'Cannot downgrade while workflow dispatch history exists'
              USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    _outbox_guard(workflow_targets=False)
    op.drop_index("ix_outbox_messages_one_pending_workflow", table_name="outbox_messages")
    op.drop_constraint(op.f("ck_outbox_messages_workflow_target"), "outbox_messages", type_="check")
    op.drop_constraint(op.f("ck_outbox_messages_supported_kind"), "outbox_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_outbox_messages_supported_kind"), "outbox_messages", "kind = 'transport_probe'"
    )
    op.drop_constraint(
        op.f("fk_outbox_messages_workflow_run_id_workflow_dispatches"),
        "outbox_messages",
        type_="foreignkey",
    )
    op.drop_column("outbox_messages", "workflow_run_id")
    op.drop_table("workflow_dispatches")
    op.execute("DROP FUNCTION guard_workflow_dispatch()")
