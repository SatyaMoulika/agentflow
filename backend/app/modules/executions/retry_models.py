"""Retained retry deadlines, resolved atomically with resume or cancellation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class NodeRetry(Base):
    __tablename__ = "node_retries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_node_retries_attempt",
            ondelete="RESTRICT",
        ),
        CheckConstraint("due_at >= created_at", name="due_after_creation"),
        CheckConstraint("resumed_at IS NULL OR resumed_at >= due_at", name="resume_after_due"),
        CheckConstraint(
            "cancelled_at IS NULL OR cancelled_at >= created_at", name="cancel_after_creation"
        ),
        CheckConstraint("resumed_at IS NULL OR cancelled_at IS NULL", name="one_resolution"),
        Index(
            "ix_node_retries_one_pending_run",
            "workflow_run_id",
            unique=True,
            postgresql_where=text("resumed_at IS NULL AND cancelled_at IS NULL"),
        ),
    )

    node_run_id: Mapped[UUID] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_dispatches.run_id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
