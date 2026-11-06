"""Authenticated discovery of actual configuration contracts, not future executors."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response

from app.api.dependencies import get_current_user
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse
from app.modules.auth.schemas import UserResponse
from app.modules.workflows.node_registry import NodeTypeCatalog, node_type_catalog

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "headers": REQUEST_ID_HEADER, "description": description}
    for code, description in (
        (401, "Active user authentication required"),
        (503, "Authentication storage or signing configuration unavailable"),
    )
}
router = APIRouter(tags=["node-types"], responses=ERRORS)


@router.get(
    "/node-types",
    response_model=NodeTypeCatalog,
    operation_id="list_node_types",
    summary="List registered node configuration contracts",
    description=(
        "Registered configuration schemas, declared handles and current executor readiness."
    ),
    responses={200: {"headers": REQUEST_ID_HEADER}},
)
def list_node_types(
    response: Response, user: Annotated[UserResponse, Depends(get_current_user)]
) -> NodeTypeCatalog:
    response.headers["Cache-Control"] = "no-store"
    return node_type_catalog()
