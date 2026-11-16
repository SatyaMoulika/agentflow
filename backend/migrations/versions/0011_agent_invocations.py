"""Retained owner-correlated agent threads and explicit continuation events.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def _events(enabled: bool) -> None:
    nodes = "'node.created', 'node.status_changed', 'node.retry_scheduled'"
    if enabled:
        nodes += ", 'agent.checkpointed', 'agent.resumed'"
    for name, expression in (
        ("event_type", f"event_type IN ('run.created', 'run.status_changed', {nodes})"),
        ("event_node_context", f"(event_type IN ({nodes})) = (node_run_id IS NOT NULL)"),
    ):
        constraint = op.f(f"ck_execution_events_{name}")
        op.drop_constraint(constraint, "execution_events", type_="check")
        op.create_check_constraint(constraint, "execution_events", expression)


def upgrade() -> None:
    op.create_table(
        "agent_invocations",
        sa.Column("node_run_id", sa.Uuid(), primary_key=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'running'")),
        sa.Column("checkpoint_id", sa.String(80)),
        sa.Column("resume_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_agent_invocations_attempt",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("thread_id", name=op.f("uq_agent_invocations_thread_id")),
        sa.CheckConstraint(
            "status IN ('running', 'paused', 'completed', 'failed', 'cancelled')",
            name=op.f("ck_agent_invocations_status"),
        ),
        sa.CheckConstraint(
            "resume_count BETWEEN 0 AND 5", name=op.f("ck_agent_invocations_resume_count")
        ),
        sa.CheckConstraint(
            "status <> 'paused' OR checkpoint_id IS NOT NULL",
            name=op.f("ck_agent_invocations_paused_checkpoint"),
        ),
    )
    op.create_index(
        "ix_agent_invocations_workflow_run_id", "agent_invocations", ["workflow_run_id"]
    )
    _events(True)
    op.execute("""
        CREATE FUNCTION guard_agent_invocation() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE active boolean;
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'Agent invocation history is retained' USING ERRCODE = '23514';
          END IF;
          EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.node_runs n '
            'JOIN %I.workflow_runs r ON r.id=n.workflow_run_id '
            'WHERE n.id=$1 AND n.workflow_run_id=$2 AND n.status=''running'' '
            'AND r.status=''running'')', TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
            INTO active USING NEW.node_run_id, NEW.workflow_run_id;
          IF TG_OP = 'INSERT' THEN
            IF NOT active OR NEW.status <> 'running' OR NEW.resume_count <> 0
               OR NEW.checkpoint_id IS NOT NULL THEN
              RAISE EXCEPTION 'Agent invocation requires an active attempt' USING ERRCODE = '23514';
            END IF;
          ELSE
            IF ROW(NEW.node_run_id, NEW.workflow_run_id, NEW.thread_id, NEW.created_at)
              IS DISTINCT FROM ROW(OLD.node_run_id, OLD.workflow_run_id,
                OLD.thread_id, OLD.created_at)
              OR OLD.status IN ('completed', 'failed', 'cancelled')
              OR NOT ((OLD.status='running' AND NEW.status IN
                        ('paused','completed','failed','cancelled')
                        AND NEW.resume_count=OLD.resume_count)
                     OR (OLD.status='paused' AND NEW.status='running'
                        AND NEW.resume_count=OLD.resume_count+1
                        AND NEW.checkpoint_id=OLD.checkpoint_id)
                     OR (OLD.status='paused' AND NEW.status='cancelled'
                        AND NEW.resume_count=OLD.resume_count)) THEN
              RAISE EXCEPTION 'Invalid agent invocation transition' USING ERRCODE = '23514';
            END IF;
            IF NEW.status IN ('paused','running') AND NOT active THEN
              RAISE EXCEPTION 'Agent continuation requires active attempt' USING ERRCODE = '23514';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER agent_invocations_write_guard BEFORE INSERT OR UPDATE ON agent_invocations "
        "FOR EACH ROW EXECUTE FUNCTION guard_agent_invocation()"
    )
    op.execute(
        "CREATE TRIGGER agent_invocations_delete_guard "
        "BEFORE DELETE OR TRUNCATE ON agent_invocations "
        "FOR EACH STATEMENT EXECUTE FUNCTION guard_agent_invocation()"
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM agent_invocations) OR EXISTS
            (SELECT 1 FROM execution_events
              WHERE event_type IN ('agent.checkpointed','agent.resumed'))
          THEN RAISE EXCEPTION 'Agent history prevents downgrade' USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    op.drop_table("agent_invocations")
    op.execute("DROP FUNCTION guard_agent_invocation()")
    _events(False)
