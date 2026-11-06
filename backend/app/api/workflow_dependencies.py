"""Reusable ownership dependencies and safe workflow API error mappings."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user, get_database
from app.core.exceptions import error_response
from app.infrastructure.database.session import Database
from app.modules.auth.schemas import UserResponse
from app.modules.workflows.access import OwnedWorkflow, OwnedWorkflowVersion, WorkflowAccessService
from app.modules.workflows.exceptions import (
    WorkflowArchivedError,
    WorkflowNotFoundError,
    WorkflowStorageUnavailableError,
    WorkflowVersionConflictError,
)


def get_owned_workflow(
    workflow_id: UUID,
    user: Annotated[UserResponse, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
) -> OwnedWorkflow:
    return WorkflowAccessService(database).require_workflow(
        workflow_id=workflow_id, owner_id=user.id
    )


def get_owned_workflow_version(
    workflow_id: UUID,
    version_id: UUID,
    user: Annotated[UserResponse, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
) -> OwnedWorkflowVersion:
    return WorkflowAccessService(database).require_version(
        workflow_id=workflow_id, version_id=version_id, owner_id=user.id
    )


async def workflow_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, WorkflowNotFoundError)
    return error_response(request, 404)


async def workflow_storage_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, WorkflowStorageUnavailableError)
    return error_response(request, 503)


async def workflow_archived_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, WorkflowArchivedError)
    return error_response(
        request, 409, public_error=("WORKFLOW_ARCHIVED", "Archived workflows cannot be edited.")
    )


def register_workflow_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(WorkflowNotFoundError, workflow_not_found_handler)
    application.add_exception_handler(WorkflowStorageUnavailableError, workflow_storage_handler)
    application.add_exception_handler(WorkflowArchivedError, workflow_archived_handler)
    application.add_exception_handler(
        WorkflowVersionConflictError, workflow_version_conflict_handler
    )


async def workflow_version_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, WorkflowVersionConflictError)
    return error_response(
        request,
        409,
        public_error=(
            "WORKFLOW_VERSION_CONFLICT",
            "The workflow version changed. Reload before saving.",
        ),
    )
