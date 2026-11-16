"""Mutable lifecycle rows and append-only events, bound to immutable workflow versions."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base
from app.modules.executions.state import EventType, FailureCode, NodeStatus, RunStatus

if TYPE_CHECKING:
    from app.modules.workflows.models import Workflow, WorkflowVersion


def _enum(
    enum_type: type[RunStatus] | type[NodeStatus] | type[FailureCode] | type[EventType],
    name: str,
    length: int = 32,
) -> Enum:
    return Enum(
        enum_type,
        values_callable=lambda values: [value.value for value in values],
        native_enum=False,
        create_constraint=True,
        name=name,
        length=length,
    )


def _json_constraint(column: str, nullable: bool = False) -> str:
    condition = f"jsonb_typeof({column}) = 'object' AND octet_length({column}::text) <= 1048576"
    return f"{column} IS NULL OR ({condition})" if nullable else condition


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_id", "workflow_version_id"],
            ["workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_workflow_runs_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "workflow_id", "workflow_version_id", "id", name="uq_workflow_runs_workflow_version_id"
        ),
        ForeignKeyConstraint(
            ["workflow_id", "workflow_version_id", "parent_run_id"],
            ["workflow_runs.workflow_id", "workflow_runs.workflow_version_id", "workflow_runs.id"],
            name="fk_workflow_runs_parent",
            ondelete="RESTRICT",
        ),
        CheckConstraint("parent_run_id IS NULL OR parent_run_id <> id", name="parent_not_self"),
        CheckConstraint("trigger_type = 'manual'", name="manual_trigger"),
        CheckConstraint("revision >= 0 AND event_sequence >= 0", name="nonnegative_counters"),
        CheckConstraint("max_attempts BETWEEN 1 AND 3", name="bounded_attempts"),
        CheckConstraint(_json_constraint("input_json"), name="input_object"),
        CheckConstraint(_json_constraint("output_json", True), name="output_object"),
        CheckConstraint(
            "(status = 'succeeded') = (output_json IS NOT NULL)", name="success_output"
        ),
        CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)", name="failure_code_required"
        ),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="start_after_creation"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= coalesce(started_at, created_at)",
            name="completion_after_start",
        ),
        CheckConstraint(
            "(status = 'queued' AND started_at IS NULL AND completed_at IS NULL) OR "
            "(status IN ('running', 'waiting_approval') AND started_at IS NOT NULL "
            "AND completed_at IS NULL) OR (status IN ('succeeded', 'failed', 'cancelled') "
            "AND completed_at IS NOT NULL AND (status <> 'succeeded' OR started_at IS NOT NULL))",
            name="lifecycle_timestamps",
        ),
        Index("ix_workflow_runs_workflow_created_id", "workflow_id", "created_at", "id"),
        Index("ix_workflow_runs_status_created_id", "status", "created_at", "id"),
        Index("ix_workflow_runs_parent_run_id", "parent_run_id"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"))
    workflow_version_id: Mapped[UUID]
    parent_run_id: Mapped[UUID | None]
    max_attempts: Mapped[int] = mapped_column(server_default=text("1"))
    trigger_type: Mapped[str] = mapped_column(String(16), server_default=text("'manual'"))
    status: Mapped[RunStatus] = mapped_column(
        _enum(RunStatus, "run_status"), server_default=text("'queued'")
    )
    revision: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    event_sequence: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[FailureCode | None] = mapped_column(_enum(FailureCode, "failure_code"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        server_onupdate=FetchedValue(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow: Mapped[Workflow] = relationship(foreign_keys=[workflow_id], viewonly=True)
    version: Mapped[WorkflowVersion] = relationship(
        foreign_keys="[WorkflowRun.workflow_id, WorkflowRun.workflow_version_id]",
        viewonly=True,
    )
    attempts: Mapped[list[NodeRun]] = relationship(
        back_populates="run",
        passive_deletes="all",
        foreign_keys="NodeRun.workflow_run_id",
    )
    events: Mapped[list[ExecutionEvent]] = relationship(
        back_populates="run",
        passive_deletes="all",
        foreign_keys="ExecutionEvent.workflow_run_id",
        order_by="ExecutionEvent.sequence",
    )


class RunCommand(Base):
    """Durable owner-scoped command receipts; keys are stored only as hashes."""

    __tablename__ = "run_commands"
    __table_args__ = (
        CheckConstraint("key_digest ~ '^[a-f0-9]{64}$'", name="key_digest_format"),
        CheckConstraint("request_digest ~ '^[a-f0-9]{64}$'", name="request_digest_format"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_runs.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class NodeRun(Base):
    __tablename__ = "node_runs"
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "node_id", "attempt_number", name="uq_node_runs_run_node_attempt"
        ),
        UniqueConstraint("workflow_run_id", "id", name="uq_node_runs_run_id"),
        CheckConstraint("node_id ~ '^[A-Za-z_][A-Za-z0-9_-]{0,63}$'", name="node_id_format"),
        CheckConstraint("attempt_number >= 1 AND revision >= 0", name="positive_attempt_revision"),
        CheckConstraint(_json_constraint("input_json"), name="input_object"),
        CheckConstraint(_json_constraint("output_json", True), name="output_object"),
        CheckConstraint(
            "(status = 'succeeded') = (output_json IS NOT NULL)", name="success_output"
        ),
        CheckConstraint(
            "(status = 'failed') = (error_code IS NOT NULL)", name="failure_code_required"
        ),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="start_after_creation"
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= coalesce(started_at, created_at)",
            name="completion_after_start",
        ),
        CheckConstraint(
            "(status = 'pending' AND started_at IS NULL AND completed_at IS NULL "
            "AND duration_ms IS NULL) OR (status IN ('running', 'waiting_approval') "
            "AND started_at IS NOT NULL AND completed_at IS NULL AND duration_ms IS NULL) OR "
            "(status IN ('succeeded', 'failed', 'skipped', 'cancelled') "
            "AND completed_at IS NOT NULL "
            "AND duration_ms IS NOT NULL AND (status <> 'succeeded' OR started_at IS NOT NULL) "
            "AND (status <> 'skipped' OR started_at IS NULL))",
            name="lifecycle_timestamps",
        ),
        Index("ix_node_runs_run_created_id", "workflow_run_id", "created_at", "id"),
        Index(
            "ix_node_runs_one_open_attempt",
            "workflow_run_id",
            "node_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running', 'waiting_approval')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
    )
    node_id: Mapped[str] = mapped_column(String(64))
    attempt_number: Mapped[int]
    status: Mapped[NodeStatus] = mapped_column(
        _enum(NodeStatus, "node_status"), server_default=text("'pending'")
    )
    revision: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[FailureCode | None] = mapped_column(_enum(FailureCode, "failure_code"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        server_onupdate=FetchedValue(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    run: Mapped[WorkflowRun] = relationship(
        back_populates="attempts", foreign_keys=[workflow_run_id]
    )


class ExecutionEvent(Base):
    __tablename__ = "execution_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_run_id", "node_run_id"],
            ["node_runs.workflow_run_id", "node_runs.id"],
            name="fk_execution_events_node_run",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("workflow_run_id", "sequence", name="uq_execution_events_run_sequence"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint(
            "(event_type IN ('node.created', 'node.status_changed', 'node.retry_scheduled', "
            "'agent.checkpointed', 'agent.resumed')) "
            "= (node_run_id IS NOT NULL)",
            name="event_node_context",
        ),
        CheckConstraint(_json_constraint("event_payload"), name="payload_object"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workflow_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"),
    )
    node_run_id: Mapped[UUID | None]
    sequence: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[EventType] = mapped_column(_enum(EventType, "event_type"))
    event_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    run: Mapped[WorkflowRun] = relationship(back_populates="events", foreign_keys=[workflow_run_id])
