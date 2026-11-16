"""Code-owned calculator arguments and bounded operational agent history."""

from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.executions.provider_schemas import ProviderMetadata
from app.modules.workflows.node_configs import NodeConfig, Number


class CalculatorArguments(NodeConfig):
    operation: Literal["add", "subtract", "multiply", "divide"]
    operands: list[Number] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def binary_operations(self) -> Self:
        if self.operation in {"subtract", "divide"} and len(self.operands) != 2:
            raise ValueError("This operation requires exactly two operands")
        return self


class HttpGetArguments(NodeConfig):
    connection_id: str = Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


class HttpToolMetadata(HttpGetArguments):
    status_code: int | None = Field(default=None, ge=200, le=299)
    error_code: (
        Literal[
            "CONNECTION_UNAVAILABLE",
            "HTTP_TARGET_BLOCKED",
            "HTTP_REQUEST_FAILED",
            "DEADLINE_EXCEEDED",
        ]
        | None
    ) = None


class AgentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    tool_rounds: int = Field(ge=0, le=5)
    thread_id: str | None = Field(default=None, max_length=80)
    checkpoint_id: str | None = Field(default=None, max_length=80)
    http_tool_attempts: int = Field(default=0, ge=0, le=5)
    http_calls: list[HttpToolMetadata] = Field(default_factory=list, max_length=5)
    provider_calls: list[ProviderMetadata] = Field(max_length=6)
    failure_reason: (
        Literal[
            "invalid_input",
            "unknown_tool",
            "invalid_arguments",
            "tool_failed",
            "iteration_limit",
            "deadline",
            "provider_failure",
            "connection_unavailable",
            "http_failure",
            "duplicate_http_call",
            "tool_result_too_large",
            "checkpoint_invalid",
        ]
        | None
    ) = None


class AgentCheckpointResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    thread_id: UUID
    status: Literal["running", "paused", "completed", "failed", "cancelled"]
    checkpoint_id: str | None
    resume_count: int


class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    node_run_id: UUID = Field(strict=False)
    checkpoint_id: str = Field(min_length=1, max_length=80, pattern=r"^[0-9a-f-]+$")
