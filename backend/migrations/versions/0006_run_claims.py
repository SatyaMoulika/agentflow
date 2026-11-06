"""Run claim slots and fencing generations.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "run_claims",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_runs.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("generation >= 1", name=op.f("ck_run_claims_generation_positive")),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)", name=op.f("ck_run_claims_lease_pair")
        ),
    )
    op.create_index(
        "ix_run_claims_lease_until",
        "run_claims",
        ["lease_until"],
        postgresql_where=sa.text("lease_until IS NOT NULL"),
    )
    op.execute("""
        CREATE FUNCTION guard_run_claim() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
            RAISE EXCEPTION 'Claim history is retained' USING ERRCODE = '23514';
          END IF;
          IF NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.generation < OLD.generation
            OR NEW.generation > OLD.generation + 1 THEN
            RAISE EXCEPTION 'Invalid claim generation' USING ERRCODE = '23514';
          END IF;
          IF NEW.lease_token IS DISTINCT FROM OLD.lease_token AND NEW.lease_token IS NOT NULL
             AND NEW.generation <> OLD.generation + 1 THEN
            RAISE EXCEPTION 'New claim requires a new generation' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER run_claims_update_guard BEFORE UPDATE ON run_claims "
        "FOR EACH ROW EXECUTE FUNCTION guard_run_claim()"
    )
    op.execute(
        "CREATE TRIGGER run_claims_delete_guard BEFORE DELETE OR TRUNCATE ON run_claims "
        "FOR EACH STATEMENT EXECUTE FUNCTION guard_run_claim()"
    )


def downgrade() -> None:
    op.drop_table("run_claims")
    op.execute("DROP FUNCTION guard_run_claim()")
