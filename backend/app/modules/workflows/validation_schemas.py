"""Read-only validation requests and bounded, deliberately public diagnostics."""

from typing import Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.workflows.schemas import WorkflowDefinition, _non_null_patch_schema


class WorkflowValidationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        json_schema_extra={"not": {"required": ["definition", "version_id"]}},
    )

    definition: WorkflowDefinition | None = Field(
        default=None, json_schema_extra=_non_null_patch_schema
    )
    version_id: UUID | None = Field(
        default=None, strict=False, json_schema_extra=_non_null_patch_schema
    )

    @field_validator("definition", "version_id", mode="before")
    @classmethod
    def reject_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Omit a selector instead of providing null")
        return value

    @model_validator(mode="after")
    def one_source(self) -> Self:
        if self.definition is not None and self.version_id is not None:
            raise ValueError("Choose a candidate or a saved version")
        return self


class WorkflowValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    path: str


class WorkflowPlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_node_id: str
    node_count: int = Field(ge=1, le=500)
    edge_count: int = Field(ge=0, le=2000)
    topological_order: list[str] = Field(min_length=1, max_length=500)
    terminal_node_ids: list[str] = Field(min_length=1, max_length=500)


class WorkflowValidationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workflow_id: UUID
    workflow_version_id: UUID | None
    source: Literal["saved", "candidate"]
    valid: bool
    execution_ready: bool = False
    issues: list[WorkflowValidationIssue] = Field(max_length=100)
    issues_truncated: bool
    plan: WorkflowPlanSummary | None

    @model_validator(mode="after")
    def consistent_outcome(self) -> Self:
        if self.valid != (self.plan is not None and not self.issues and not self.issues_truncated):
            raise ValueError("Validation report and plan must agree")
        if not self.valid and not self.issues:
            raise ValueError("Invalid workflows require a diagnostic")
        if self.execution_ready and not self.valid:
            raise ValueError("Invalid workflows cannot be executable")
        return self
