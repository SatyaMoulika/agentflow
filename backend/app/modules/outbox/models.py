"""Outbox rows contain only an opaque ID and a fixed transport intent."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (
        CheckConstraint("kind IN ('transport_probe', 'workflow_run')", name="supported_kind"),
        CheckConstraint(
            "(kind = 'workflow_run') = (workflow_run_id IS NOT NULL)", name="workflow_target"
        ),
        CheckConstraint("attempts >= 0", name="nonnegative_attempts"),
        CheckConstraint("(lease_token IS NULL) = (lease_until IS NULL)", name="lease_pair"),
        CheckConstraint(
            "published_at IS NULL OR (lease_token IS NULL AND lease_until IS NULL)",
            name="published_no_lease",
        ),
        Index(
            "ix_outbox_messages_pending",
            "created_at",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
        Index(
            "ix_outbox_messages_one_pending_workflow",
            "workflow_run_id",
            unique=True,
            postgresql_where=text("workflow_run_id IS NOT NULL AND published_at IS NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    kind: Mapped[str] = mapped_column(String(32), server_default=text("'transport_probe'"))
    workflow_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("workflow_dispatches.run_id", ondelete="RESTRICT")
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
