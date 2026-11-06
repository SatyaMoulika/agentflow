"""Metadata and bounded draft snapshots; semantic graph validation arrives separately."""

import json
import math
from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.modules.workflows.models import WorkflowStatus


def _non_null_patch_schema(schema: dict[str, Any]) -> None:
    """Omitted fields are allowed; explicit null is rejected, including in OpenAPI."""
    for branch in schema.pop("anyOf", []):
        if branch.get("type") != "null":
            schema.update(branch)
    schema.pop("default", None)


class WorkflowDefinition(BaseModel):
    """Preserve business keys verbatim; acceptance does not mean executable or valid DAG."""

    model_config = ConfigDict(extra="allow", strict=True, hide_input_in_errors=True)

    schema_version: Literal["1.0"]
    nodes: list[dict[str, JsonValue]] = Field(max_length=500)
    edges: list[dict[str, JsonValue]] = Field(max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value: Any) -> Any:
        if isinstance(value, cls):
            return value
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 32:
                raise ValueError("Definition nesting exceeds 32 levels")
            if isinstance(item, dict):
                if any(not isinstance(key, str) for key in item):
                    raise ValueError("Definition keys must be strings")
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif type(item) not in (str, int, float, bool, type(None)):
                raise ValueError("Definition must contain JSON values")
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Definition numbers must be finite")
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            size = len(encoded.encode("utf-8"))
        except (ValueError, TypeError, UnicodeError):
            raise ValueError("Definition must be valid UTF-8 JSON") from None
        if size > 262144:
            raise ValueError("Definition exceeds 256 KiB")
        return value


class WorkflowCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    definition: WorkflowDefinition | None = Field(
        default=None, json_schema_extra=_non_null_patch_schema
    )

    @field_validator("definition", mode="before")
    @classmethod
    def reject_null_definition(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Provided definition must not be null")
        return value

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class WorkflowUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        json_schema_extra={
            "minProperties": 1,
            "dependentRequired": {
                "definition": ["expected_version"],
                "expected_version": ["definition"],
            },
        },
    )

    name: str | None = Field(
        default=None, min_length=1, max_length=200, json_schema_extra=_non_null_patch_schema
    )
    description: str | None = Field(
        default=None, max_length=5000, json_schema_extra=_non_null_patch_schema
    )
    definition: WorkflowDefinition | None = Field(
        default=None, json_schema_extra=_non_null_patch_schema
    )
    expected_version: int | None = Field(
        default=None, ge=0, le=2147483647, json_schema_extra=_non_null_patch_schema
    )

    @field_validator("definition", "expected_version", mode="before")
    @classmethod
    def reject_null_save_fields(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Provided save fields must not be null")
        return value

    @field_validator("name", "description", mode="before")
    @classmethod
    def trim_provided_text(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("Provided metadata must not be null")
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Provide metadata or a definition")
        if (self.definition is None) != (self.expected_version is None):
            raise ValueError("Definition and expected_version must be provided together")
        return self


class WorkflowListParams(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    page: int = Field(default=1, ge=1, le=1000000)
    page_size: int = Field(default=25, ge=1, le=100)
    status: WorkflowStatus | None = None
    q: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("q", mode="before")
    @classmethod
    def trim_search(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str
    status: WorkflowStatus
    current_version_id: UUID | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def as_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class WorkflowPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[WorkflowResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class WorkflowVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    workflow_id: UUID
    version_number: int = Field(ge=1)
    definition: dict[str, JsonValue] = Field(validation_alias="definition_json")
    created_by: UUID
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def as_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class WorkflowDetailResponse(WorkflowResponse):
    current_version_number: int = Field(ge=0)
    version: WorkflowVersionResponse | None
