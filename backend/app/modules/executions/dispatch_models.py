"""Durable provenance and redispatch timing for worker-owned workflow runs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class WorkflowDispatch(Base):
    __tablename__ = "workflow_dispatches"
    __table_args__ = (
        CheckConstraint("dispatch_count >= 1", name="positive_count"),
        CheckConstraint("retry_base_seconds BETWEEN 1 AND 300", name="retry_base_bounds"),
        CheckConstraint(
            "retry_max_seconds BETWEEN retry_base_seconds AND 3600", name="retry_max_bounds"
        ),
        Index("ix_workflow_dispatches_next_run", "next_dispatch_at", "run_id"),
    )

    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    dispatch_count: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    traceparent: Mapped[str | None] = mapped_column(String(55))
    retry_base_seconds: Mapped[int] = mapped_column(Integer, server_default=text("5"))
    retry_max_seconds: Mapped[int] = mapped_column(Integer, server_default=text("60"))
    next_dispatch_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
