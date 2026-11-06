"""Durable command receipts and frozen bounded attempt budgets.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_workflow_runs_bounded_attempts"), "workflow_runs", "max_attempts BETWEEN 1 AND 3"
    )
    op.create_table(
        "run_commands",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("key_digest", sa.String(64), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("clock_timestamp()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("owner_id", "key_digest"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "key_digest ~ '^[a-f0-9]{64}$'", name=op.f("ck_run_commands_key_digest_format")
        ),
        sa.CheckConstraint(
            "request_digest ~ '^[a-f0-9]{64}$'", name=op.f("ck_run_commands_request_digest_format")
        ),
    )
    op.execute("""
        CREATE FUNCTION guard_execution_command() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owned boolean;
        BEGIN
            IF TG_TABLE_NAME = 'run_commands' THEN
                IF TG_OP = 'INSERT' THEN
                    EXECUTE format('SELECT EXISTS (SELECT 1 FROM %I.workflow_runs r '
                        'JOIN %I.workflows w ON r.workflow_id = w.id '
                        'WHERE r.id = $1 AND w.owner_id = $2)',
                        TG_TABLE_SCHEMA, TG_TABLE_SCHEMA)
                        INTO owned USING NEW.run_id, NEW.owner_id;
                    IF NOT owned THEN
                        RAISE EXCEPTION 'Command run ownership mismatch' USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'Execution command receipts are immutable' USING ERRCODE = '23514';
            END IF;
            IF NEW.max_attempts IS DISTINCT FROM OLD.max_attempts THEN
                RAISE EXCEPTION 'Execution attempt budget is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER run_commands_owner BEFORE INSERT ON run_commands "
        "FOR EACH ROW EXECUTE FUNCTION guard_execution_command()"
    )
    op.execute(
        "CREATE TRIGGER run_commands_immutable BEFORE UPDATE OR DELETE OR TRUNCATE "
        "ON run_commands FOR EACH STATEMENT EXECUTE FUNCTION guard_execution_command()"
    )
    op.execute(
        "CREATE TRIGGER workflow_runs_budget BEFORE UPDATE ON workflow_runs "
        "FOR EACH ROW EXECUTE FUNCTION guard_execution_command()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER workflow_runs_budget ON workflow_runs")
    op.drop_table("run_commands")
    op.execute("DROP FUNCTION guard_execution_command()")
    op.drop_constraint(op.f("ck_workflow_runs_bounded_attempts"), "workflow_runs", type_="check")
    op.drop_column("workflow_runs", "max_attempts")
