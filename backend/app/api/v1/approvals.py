"""Authenticated review endpoints; owner identity always comes from the bearer session."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from app.api.dependencies import get_current_user, get_database
from app.infrastructure.database.session import Database
from app.modules.approvals.schemas import (
    ApprovalDecision,
    ApprovalDetail,
    ApprovalPage,
    ApprovalResponse,
    ApprovalStatus,
)
from app.modules.approvals.service import ApprovalService
from app.modules.auth.schemas import UserResponse

router = APIRouter(prefix="/approvals", tags=["approvals"])
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
DatabaseResource = Annotated[Database, Depends(get_database)]


@router.get("", response_model=ApprovalPage)
def list_approvals(
    user: CurrentUser,
    database: DatabaseResource,
    response: Response,
    status: ApprovalStatus | None = "pending",
    run_id: UUID | None = None,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApprovalPage:
    response.headers["Cache-Control"] = "no-store"
    return ApprovalService(database).list(
        user.id, status=status, run_id=run_id, page=page, page_size=page_size
    )


@router.get("/{approval_id}", response_model=ApprovalDetail)
def get_approval(
    approval_id: UUID,
    user: CurrentUser,
    database: DatabaseResource,
    response: Response,
) -> ApprovalDetail:
    response.headers["Cache-Control"] = "no-store"
    return ApprovalService(database).get(user.id, approval_id)


@router.post("/{approval_id}/decision", response_model=ApprovalResponse)
def decide_approval(
    approval_id: UUID,
    data: ApprovalDecision,
    user: CurrentUser,
    database: DatabaseResource,
    response: Response,
) -> ApprovalResponse:
    response.headers["Cache-Control"] = "no-store"
    return ApprovalService(database).decide(user.id, approval_id, data)
