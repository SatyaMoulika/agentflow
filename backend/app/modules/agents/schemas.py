"""Code-owned calculator arguments and bounded operational agent history."""

from typing import Literal, Self

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


class AgentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    tool_rounds: int = Field(ge=0, le=5)
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
        ]
        | None
    ) = None
