"""Durable, leased outbox transport intents.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "kind", sa.String(32), nullable=False, server_default=sa.text("'transport_probe'")
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("clock_timestamp()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind = 'transport_probe'", name=op.f("ck_outbox_messages_supported_kind")
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_outbox_messages_nonnegative_attempts")),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_until IS NULL)",
            name=op.f("ck_outbox_messages_lease_pair"),
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR (lease_token IS NULL AND lease_until IS NULL)",
            name=op.f("ck_outbox_messages_published_no_lease"),
        ),
    )
    op.create_index(
        "ix_outbox_messages_pending",
        "outbox_messages",
        ["created_at", "id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )
    op.execute("""
        CREATE FUNCTION guard_outbox_message() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR TG_OP = 'TRUNCATE' THEN
            RAISE EXCEPTION 'Outbox history is retained' USING ERRCODE = '23514';
          END IF;
          IF ROW(NEW.id, NEW.kind, NEW.created_at) IS DISTINCT FROM
             ROW(OLD.id, OLD.kind, OLD.created_at)
             OR NEW.attempts < OLD.attempts OR OLD.published_at IS NOT NULL THEN
            RAISE EXCEPTION 'Invalid outbox history change' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END;
        $$
    """)
    op.execute(
        "CREATE TRIGGER outbox_update_guard BEFORE UPDATE ON outbox_messages "
        "FOR EACH ROW EXECUTE FUNCTION guard_outbox_message()"
    )
    op.execute(
        "CREATE TRIGGER outbox_delete_guard BEFORE DELETE OR TRUNCATE ON outbox_messages "
        "FOR EACH STATEMENT EXECUTE FUNCTION guard_outbox_message()"
    )


def downgrade() -> None:
    op.drop_table("outbox_messages")
    op.execute("DROP FUNCTION guard_outbox_message()")
