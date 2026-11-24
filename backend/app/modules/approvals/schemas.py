"""Public approval contracts; business input is returned only on owned detail reads."""

from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

ApprovalStatus = Literal["pending", "approved", "rejected", "expired", "cancelled"]


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workflow_run_id: UUID
    node_run_id: UUID
    node_id: str
    assigned_to: UUID
    title: str
    status: ApprovalStatus
    note: str | None
    created_at: AwareDatetime
    expires_at: AwareDatetime
    resolved_at: AwareDatetime | None


class ApprovalDetail(ApprovalResponse):
    input: dict[str, Any]


class ApprovalPage(BaseModel):
    items: list[ApprovalResponse]
    total: int
    page: int
    page_size: int


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=2000)
