"""Retained approval requests; resolved decisions cannot be rewritten."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_approvals_attempt",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("node_run_id", name="uq_approvals_attempt"),
        UniqueConstraint("workflow_run_id", "node_id", name="uq_approvals_run_node"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'cancelled')",
            name="status",
        ),
        CheckConstraint("length(btrim(title)) BETWEEN 1 AND 200", name="title_bounds"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint("(status = 'pending') = (resolved_at IS NULL)", name="resolution_required"),
        CheckConstraint(
            "resolved_at IS NULL OR resolved_at >= created_at", name="resolution_after_creation"
        ),
        Index("ix_approvals_assignee_status_created", "assigned_to", "status", "created_at", "id"),
        Index(
            "ix_approvals_pending_expiry", "expires_at", postgresql_where=text("status='pending'")
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_dispatches.run_id", ondelete="RESTRICT")
    )
    node_run_id: Mapped[UUID]
    node_id: Mapped[str] = mapped_column(String(64))
    assigned_to: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), server_default=text("'pending'"))
    note: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
