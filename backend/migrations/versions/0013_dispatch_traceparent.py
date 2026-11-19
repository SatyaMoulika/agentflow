"""Retain minimal trace context for background delivery correlation.

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op
 
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("workflow_dispatches", sa.Column("traceparent", sa.String(55), nullable=True))
    op.execute("""
        CREATE FUNCTION guard_dispatch_traceparent() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.traceparent IS DISTINCT FROM OLD.traceparent THEN
            RAISE EXCEPTION 'Dispatch trace context is immutable' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER dispatch_traceparent_guard BEFORE UPDATE ON workflow_dispatches "
        "FOR EACH ROW EXECUTE FUNCTION guard_dispatch_traceparent()"
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM workflow_dispatches WHERE traceparent IS NOT NULL) THEN
            RAISE EXCEPTION 'Trace correlation history prevents downgrade' USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    op.execute("DROP TRIGGER dispatch_traceparent_guard ON workflow_dispatches")
    op.execute("DROP FUNCTION guard_dispatch_traceparent()")
    op.drop_column("workflow_dispatches", "traceparent")
