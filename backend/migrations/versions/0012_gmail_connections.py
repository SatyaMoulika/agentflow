"""Owner-bound Gmail OAuth attempts and credentials.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "gmail_authorizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("state_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("encrypted_verifier", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "length(state_digest) = 64", name=op.f("ck_gmail_authorizations_state_digest_length")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_gmail_authorizations_expiry_after_creation")
        ),
        sa.CheckConstraint(
            "(consumed_at IS NULL) = (encrypted_verifier IS NOT NULL)",
            name=op.f("ck_gmail_authorizations_verifier_state"),
        ),
    )
    op.create_index(
        "ix_gmail_authorizations_owner_created", "gmail_authorizations", ["owner_id", "created_at"]
    )
    op.create_table(
        "gmail_connections",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("encrypted_refresh_token", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(revoked_at IS NULL AND encrypted_refresh_token IS NOT NULL) OR "
            "(revoked_at IS NOT NULL AND encrypted_refresh_token IS NULL)",
            name=op.f("ck_gmail_connections_credential_state"),
        ),
    )
    op.create_index(
        "ix_gmail_connections_owner_created", "gmail_connections", ["owner_id", "created_at"]
    )


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM gmail_connections) OR EXISTS (SELECT 1 FROM gmail_authorizations)
          THEN RAISE EXCEPTION 'Gmail history prevents downgrade' USING ERRCODE = '23514';
          END IF;
        END $$
    """)
    op.drop_table("gmail_connections")
    op.drop_table("gmail_authorizations")
