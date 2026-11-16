"""Owned, expiring Gmail OAuth attempts and revocable credentials."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class GmailAuthorization(Base):
    __tablename__ = "gmail_authorizations"
    __table_args__ = (
        CheckConstraint("length(state_digest) = 64", name="state_digest_length"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint(
            "(consumed_at IS NULL) = (encrypted_verifier IS NOT NULL)", name="verifier_state"
        ),
        Index("ix_gmail_authorizations_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    state_digest: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_verifier: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GmailConnection(Base):
    __tablename__ = "gmail_connections"
    __table_args__ = (
        CheckConstraint(
            "(revoked_at IS NULL AND encrypted_refresh_token IS NOT NULL) OR "
            "(revoked_at IS NOT NULL AND encrypted_refresh_token IS NULL)",
            name="credential_state",
        ),
        Index("ix_gmail_connections_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
