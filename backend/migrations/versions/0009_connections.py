"""Protected HTTP connections and explicit external-call failure codes.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def _failure_codes(*, external: bool) -> None:
    values = "'EXECUTION_FAILED', 'INPUT_MAPPING_FAILED', 'DEADLINE_EXCEEDED', 'INTERNAL_FAILURE'"
    if external:
        values += ", 'CONNECTION_UNAVAILABLE', 'HTTP_REQUEST_FAILED', 'HTTP_TARGET_BLOCKED'"
    for table in ("workflow_runs", "node_runs"):
        name = op.f(f"ck_{table}_failure_code")
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, f"error_code IN ({values})")


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("endpoint_url", sa.String(1000), nullable=False),
        sa.Column("auth_type", sa.String(20), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "length(btrim(name)) BETWEEN 1 AND 100", name=op.f("ck_connections_name_bounds")
        ),
        sa.CheckConstraint(
            "auth_type IN ('none', 'bearer', 'api_key')", name=op.f("ck_connections_auth_type")
        ),
        sa.CheckConstraint(
            "length(endpoint_url) BETWEEN 1 AND 1000", name=op.f("ck_connections_endpoint_bounds")
        ),
        sa.CheckConstraint(
            "(revoked_at IS NOT NULL AND encrypted_secret IS NULL) OR "
            "(revoked_at IS NULL AND ((auth_type = 'none' AND encrypted_secret IS NULL) OR "
            "(auth_type <> 'none' AND encrypted_secret IS NOT NULL)))",
            name=op.f("ck_connections_credential_state"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_connections_revocation_time"),
        ),
    )
    op.create_index(
        "ix_connections_owner_created_id", "connections", ["owner_id", "created_at", "id"]
    )
    op.execute("""
        CREATE FUNCTION guard_connection() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP <> 'UPDATE' THEN
            RAISE EXCEPTION 'Connection history is retained' USING ERRCODE = '23514';
          END IF;
          IF OLD.revoked_at IS NOT NULL OR
             ROW(NEW.id, NEW.owner_id, NEW.name, NEW.endpoint_url, NEW.auth_type, NEW.created_at)
             IS DISTINCT FROM
             ROW(OLD.id, OLD.owner_id, OLD.name, OLD.endpoint_url, OLD.auth_type, OLD.created_at)
             OR NEW.revoked_at IS NULL OR NEW.encrypted_secret IS NOT NULL THEN
            RAISE EXCEPTION 'Only credential revocation is allowed' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER connections_revoke_only BEFORE UPDATE OR DELETE ON connections "
        "FOR EACH ROW EXECUTE FUNCTION guard_connection()"
    )
    op.execute(
        "CREATE TRIGGER connections_no_truncate BEFORE TRUNCATE ON connections "
        "FOR EACH STATEMENT EXECUTE FUNCTION guard_connection()"
    )
    _failure_codes(external=True)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM connections) OR
             EXISTS (SELECT 1 FROM workflow_runs WHERE error_code IN
               ('CONNECTION_UNAVAILABLE', 'HTTP_REQUEST_FAILED', 'HTTP_TARGET_BLOCKED')) OR
             EXISTS (SELECT 1 FROM node_runs WHERE error_code IN
               ('CONNECTION_UNAVAILABLE', 'HTTP_REQUEST_FAILED', 'HTTP_TARGET_BLOCKED')) THEN
            RAISE EXCEPTION 'Connection or external-call history must be retained'
              USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    _failure_codes(external=False)
    op.drop_table("connections")
    op.execute("DROP FUNCTION guard_connection()")
