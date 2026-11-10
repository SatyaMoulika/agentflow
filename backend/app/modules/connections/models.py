"""Connection identity is retained when revoked; usable secrets are removed."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Connection(Base):
    __tablename__ = "connections"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) BETWEEN 1 AND 100", name="name_bounds"),
        CheckConstraint("auth_type IN ('none', 'bearer', 'api_key')", name="auth_type"),
        CheckConstraint("length(endpoint_url) BETWEEN 1 AND 1000", name="endpoint_bounds"),
        CheckConstraint(
            "(revoked_at IS NOT NULL AND encrypted_secret IS NULL) OR "
            "(revoked_at IS NULL AND ((auth_type = 'none' AND encrypted_secret IS NULL) OR "
            "(auth_type <> 'none' AND encrypted_secret IS NOT NULL)))",
            name="credential_state",
        ),
        CheckConstraint("revoked_at IS NULL OR revoked_at >= created_at", name="revocation_time"),
        Index("ix_connections_owner_created_id", "owner_id", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(100))
    endpoint_url: Mapped[str] = mapped_column(String(1000))
    auth_type: Mapped[str] = mapped_column(String(20))
    encrypted_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
