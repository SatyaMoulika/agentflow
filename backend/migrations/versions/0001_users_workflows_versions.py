"""Users, workflows, immutable versions, and the same-workflow current pointer.

Revision ID: 0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(1024), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND length(email) > 0",
            name=op.f("ck_users_email_normalized"),
        ),
        sa.CheckConstraint(
            "length(btrim(password_hash)) > 0", name=op.f("ck_users_password_hash_nonempty")
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) > 0", name=op.f("ck_users_display_name_nonempty")
        ),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflows_owner_id_users"),
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name=op.f("ck_workflows_name_nonempty")),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'archived')",
            name=op.f("ck_workflows_workflow_status"),
        ),
    )
    op.create_index("ix_workflows_owner_updated_id", "workflows", ["owner_id", "updated_at", "id"])
    op.create_index(
        "ix_workflows_owner_status_updated_id",
        "workflows",
        ["owner_id", "status", "updated_at", "id"],
    )
    op.create_table(
        "workflow_versions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition_json", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.String(10), nullable=False, server_default=sa.text("'1.0'")),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_versions_workflow_id_workflows"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            ondelete="RESTRICT",
            name=op.f("fk_workflow_versions_created_by_users"),
        ),
        sa.UniqueConstraint(
            "workflow_id", "version_number", name="uq_workflow_versions_workflow_number"
        ),
        sa.UniqueConstraint("workflow_id", "id", name="uq_workflow_versions_workflow_id"),
        sa.CheckConstraint(
            "version_number >= 1", name=op.f("ck_workflow_versions_version_number_positive")
        ),
        sa.CheckConstraint(
            "schema_version = '1.0'", name=op.f("ck_workflow_versions_schema_version_supported")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(definition_json) = 'object'",
            name=op.f("ck_workflow_versions_definition_object"),
        ),
        sa.CheckConstraint(
            "definition_json ->> 'schema_version' IS NOT NULL "
            "AND jsonb_typeof(definition_json -> 'schema_version') = 'string' "
            "AND definition_json ->> 'schema_version' = schema_version",
            name=op.f("ck_workflow_versions_definition_schema_matches"),
        ),
    )
    op.create_index("ix_workflow_versions_created_by", "workflow_versions", ["created_by"])
    # The target table/unique key must exist before adding this circular reference.
    op.create_foreign_key(
        "fk_workflows_current_version",
        "workflows",
        "workflow_versions",
        ["id", "current_version_id"],
        ["workflow_id", "id"],
        ondelete="RESTRICT",
    )
    op.execute("""
        CREATE FUNCTION reject_workflow_version_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Workflow versions are immutable' USING ERRCODE = '23514';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER workflow_versions_immutable
        BEFORE UPDATE OR DELETE OR TRUNCATE ON workflow_versions
        FOR EACH STATEMENT EXECUTE FUNCTION reject_workflow_version_mutation()
    """)
    op.execute("""
        CREATE FUNCTION set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    for table in ("users", "workflows"):
        op.execute(
            f"CREATE TRIGGER {table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER workflow_versions_immutable ON workflow_versions")
    op.execute("DROP FUNCTION reject_workflow_version_mutation()")
    op.drop_constraint("fk_workflows_current_version", "workflows", type_="foreignkey")
    op.drop_table("workflow_versions")
    op.drop_table("workflows")
    op.drop_table("users")
    op.execute("DROP FUNCTION set_updated_at()")
