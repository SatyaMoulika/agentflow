"""Explicit run commands and owner-only history DTOs; business JSON keys stay verbatim."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.modules.agents.schemas import AgentCheckpointResponse, AgentMetadata
from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload
from app.modules.executions.provider_schemas import ProviderMetadata
from app.modules.executions.state import EventType, FailureCode, NodeStatus, RunStatus
from app.modules.workflows.schemas import WorkflowVersionResponse


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    workflow_version_id: UUID = Field(strict=False)
    input: dict[str, JsonValue]
    max_attempts: int = Field(default=1, ge=1, le=3)

    @field_validator("input", mode="before")
    @classmethod
    def bounded_input(cls, value: Any) -> dict[str, Any]:
        try:
            return copy_payload(value)
        except InvalidExecutionPayloadError:
            raise ValueError("Input must be a bounded JSON object") from None


class RunRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    max_attempts: int = Field(default=1, ge=1, le=3)


class HistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)

    id: UUID
    revision: int
    input: dict[str, JsonValue] = Field(validation_alias="input_json")
    output: dict[str, JsonValue] | None = Field(validation_alias="output_json")
    error_code: FailureCode | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None

    @field_validator("created_at", "updated_at", "started_at", "completed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class RetryScheduleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)

    scheduled_at: AwareDatetime = Field(validation_alias="created_at")
    due_at: AwareDatetime
    resumed_at: AwareDatetime | None
    cancelled_at: AwareDatetime | None


class NodeAttemptResponse(HistoryResponse):
    workflow_run_id: UUID
    node_id: str
    attempt_number: int
    status: NodeStatus
    duration_ms: int | None
    retry: RetryScheduleResponse | None = None
    provider: ProviderMetadata | None = None
    agent: AgentMetadata | None = None
    checkpoint: AgentCheckpointResponse | None = None


class RunSummary(HistoryResponse):
    workflow_id: UUID
    workflow_version_id: UUID
    parent_run_id: UUID | None
    max_attempts: int
    trigger_type: Literal["manual"]
    status: RunStatus
    event_sequence: int
    execution_mode: Literal["synchronous", "background"] = "synchronous"
    next_retry_at: AwareDatetime | None = None
    retry_node_id: str | None = None
    next_retry_attempt: int | None = None


class RunResponse(RunSummary):
    version: WorkflowVersionResponse
    node_runs: list[NodeAttemptResponse]


class ExecutionEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True, populate_by_name=True)

    sequence: int
    node_run_id: UUID | None
    event_type: EventType
    payload: dict[str, JsonValue] = Field(validation_alias="event_payload")
    created_at: AwareDatetime


class ExecutionEventPage(BaseModel):
    items: list[ExecutionEventResponse]
    next_after_sequence: int


class RunListParams(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=25, ge=1, le=100)
    status: RunStatus | None = None
    workflow_id: UUID | None = None


class RunListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_name: str
    version_number: int
    status: RunStatus
    execution_mode: Literal["synchronous", "background"] = "synchronous"
    error_code: FailureCode | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None

    @field_validator("created_at", "started_at", "completed_at")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class RunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RunListItem]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
