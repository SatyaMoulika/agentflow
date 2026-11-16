"""Application-owned invocation identity; LangGraph owns its separate checkpoint schema."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class AgentInvocation(Base):
    __tablename__ = "agent_invocations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_agent_invocations_attempt",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("thread_id"),
        CheckConstraint(
            "status IN ('running', 'paused', 'completed', 'failed', 'cancelled')", name="status"
        ),
        CheckConstraint("resume_count BETWEEN 0 AND 5", name="resume_count"),
        CheckConstraint(
            "status <> 'paused' OR checkpoint_id IS NOT NULL", name="paused_checkpoint"
        ),
    )

    node_run_id: Mapped[UUID] = mapped_column(primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(index=True)
    thread_id: Mapped[UUID] = mapped_column(default=uuid4)
    status: Mapped[str] = mapped_column(String(16), server_default=text("'running'"))
    checkpoint_id: Mapped[str | None] = mapped_column(String(80))
    resume_count: Mapped[int] = mapped_column(server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
