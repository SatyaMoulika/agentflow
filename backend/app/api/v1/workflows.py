"""Bearer-authenticated metadata, immutable draft saves and owner-scoped historical reads."""

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user, get_database, get_database_resource, get_settings
from app.core.config import Settings
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse, error_response
from app.infrastructure.database.session import Database
from app.modules.auth.schemas import UserResponse
from app.modules.connections.schemas import PlannerConnection
from app.modules.connections.secrets import ConnectionUnavailableError
from app.modules.connections.service import ConnectionService
from app.modules.workflows.connection_bindings import node_connection_ids
from app.modules.workflows.exceptions import WorkflowArchivedError, WorkflowVersionConflictError
from app.modules.workflows.generation import (
    EditProposalRequest,
    EditProposalResponse,
    GenerateRequest,
    GenerationResponse,
    InvalidProposalError,
    generate,
)
from app.modules.workflows.schemas import (
    WorkflowCreateRequest,
    WorkflowDetailResponse,
    WorkflowListParams,
    WorkflowPage,
    WorkflowUpdateRequest,
)
from app.modules.workflows.service import WorkflowService
from app.modules.workflows.validation_schemas import (
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)
from app.modules.workflows.validation_service import WorkflowValidationService

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "headers": REQUEST_ID_HEADER, "description": description}
    for code, description in (
        (401, "Active user authentication required"),
        (404, "Missing or not-owned workflow"),
        (422, "Invalid metadata, definition, path or query"),
        (503, "Storage unavailable"),
    )
}
router = APIRouter(prefix="/workflows", tags=["workflows"], responses=ERRORS)
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
DatabaseResource = Annotated[Database, Depends(get_database)]


def _planner_catalog(
    database: Database | None,
    settings: Settings,
    owner_id: UUID,
    selected: list[UUID],
    definition: dict | None = None,
) -> list[PlannerConnection]:
    identities = list(selected)
    for node in (definition or {}).get("nodes", []):
        if isinstance(node, dict) and node.get("type") in {"http", "agent"}:
            try:
                bindings = node_connection_ids(node["type"], node.get("config"))
            except (ValueError, KeyError, TypeError):
                raise HTTPException(status_code=422) from None
            for value in bindings:
                identity = UUID(value)
                if identity not in identities:
                    identities.append(identity)
    if len(identities) > 20:
        raise HTTPException(status_code=422)
    if not identities:
        return []
    if database is None:
        raise ConnectionUnavailableError()
    return ConnectionService(database, settings).planner_catalog(owner_id, identities)


@router.post(
    "/generate",
    response_model=GenerationResponse,
    operation_id="generate_workflow_proposal",
    summary="Propose a workflow from a natural-language request",
    description="Sends the request to Groq; validates but does not save or run the proposal.",
    responses={
        429: {"model": ErrorResponse, "headers": REQUEST_ID_HEADER, "description": "Groq limit"},
        502: {
            "model": ErrorResponse,
            "headers": REQUEST_ID_HEADER,
            "description": "Invalid proposal",
        },
    },
)
def generate_workflow(
    data: GenerateRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database | None, Depends(get_database_resource)],
) -> GenerationResponse | JSONResponse:
    catalog = _planner_catalog(database, settings, user.id, data.connection_ids)
    try:
        result = generate(settings, data.prompt, connections=catalog)
    except InvalidProposalError:
        return error_response(
            request,
            502,
            headers={"Cache-Control": "no-store"},
            public_error=(
                "GENERATION_INVALID",
                "The generated workflow was invalid. Try a simpler request.",
            ),
        )
    response.headers["Cache-Control"] = "no-store"
    _planner_catalog(database, settings, user.id, data.connection_ids)
    return result


@router.post(
    "/{workflow_id}/edit-proposal",
    response_model=EditProposalResponse,
    operation_id="generate_workflow_edit_proposal",
    summary="Propose changes to an owned saved workflow",
    description=(
        "Sends the saved definition and request to Groq. Requires the current version ID; "
        "the proposal is validated but never saved or executed."
    ),
    responses={
        409: {"model": ErrorResponse, "description": "Archived or stale workflow version"},
        429: {"model": ErrorResponse, "description": "Groq limit"},
        502: {"model": ErrorResponse, "description": "Invalid proposal"},
    },
)
def generate_workflow_edit_proposal(
    workflow_id: UUID,
    data: EditProposalRequest,
    request: Request,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
    settings: Annotated[Settings, Depends(get_settings)],
) -> EditProposalResponse | JSONResponse:
    workflow = WorkflowService(database).get(workflow_id=workflow_id, owner_id=user.id)
    if workflow.status.value == "archived":
        raise WorkflowArchivedError()
    if workflow.current_version_id != data.base_version_id or workflow.version is None:
        raise WorkflowVersionConflictError()
    definition = workflow.version.definition
    nodes = definition.get("nodes", [])
    if not isinstance(nodes, list):
        raise HTTPException(status_code=422)
    if any(isinstance(node, dict) and node.get("type") == "gmail_read" for node in nodes):
        return error_response(
            request,
            422,
            headers={"Cache-Control": "no-store"},
            public_error=(
                "GMAIL_PROPOSAL_UNAVAILABLE",
                "AI edits for workflows with Gmail nodes are not available yet.",
            ),
        )
    if any(isinstance(node, dict) and node.get("type") == "approval" for node in nodes):
        return error_response(
            request,
            422,
            headers={"Cache-Control": "no-store"},
            public_error=(
                "APPROVAL_PROPOSAL_UNAVAILABLE",
                "AI edits for workflows with approval nodes are not available yet.",
            ),
        )
    if len(json.dumps(definition, ensure_ascii=False).encode("utf-8")) > 32000:
        return error_response(
            request,
            422,
            headers={"Cache-Control": "no-store"},
            public_error=(
                "DEFINITION_TOO_LARGE",
                "The saved definition is too large for an AI edit proposal.",
            ),
        )
    try:
        catalog = _planner_catalog(database, settings, user.id, data.connection_ids, definition)
        result = generate(settings, data.prompt, source_definition=definition, connections=catalog)
    except InvalidProposalError:
        return error_response(
            request,
            502,
            headers={"Cache-Control": "no-store"},
            public_error=(
                "GENERATION_INVALID",
                "The generated workflow was invalid. Try a simpler request.",
            ),
        )
    response.headers["Cache-Control"] = "no-store"
    _planner_catalog(database, settings, user.id, data.connection_ids, definition)
    return EditProposalResponse(
        **result.model_dump(),
        base_version_id=data.base_version_id,
        base_version_number=workflow.version.version_number,
    )


@router.post(
    "",
    response_model=WorkflowDetailResponse,
    status_code=201,
    operation_id="create_workflow",
    summary="Create an owned draft with an optional initial definition",
    responses={201: {"headers": REQUEST_ID_HEADER}},
    description="Omit definition for a versionless draft; include it to save immutable version 1.",
)
def create_workflow(
    data: WorkflowCreateRequest, response: Response, user: CurrentUser, database: DatabaseResource
) -> WorkflowDetailResponse:
    result = WorkflowService(database).create(owner_id=user.id, data=data)
    response.headers["Location"] = f"/api/v1/workflows/{result.id}"
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "",
    response_model=WorkflowPage,
    operation_id="list_workflows",
    summary="List owned workflow metadata",
    responses={200: {"headers": REQUEST_ID_HEADER}},
    description="List metadata; archived rows require status=archived. q searches names.",
)
def list_workflows(
    params: Annotated[WorkflowListParams, Query()],
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
) -> WorkflowPage:
    result = WorkflowService(database).list(owner_id=user.id, params=params)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/{workflow_id}",
    response_model=WorkflowDetailResponse,
    operation_id="get_workflow",
    summary="Read current or historical owned draft",
    responses={200: {"headers": REQUEST_ID_HEADER}},
)
def get_workflow(
    workflow_id: UUID,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
    version_id: UUID | None = None,
) -> WorkflowDetailResponse:
    result = WorkflowService(database).get(
        workflow_id=workflow_id, owner_id=user.id, version_id=version_id
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.patch(
    "/{workflow_id}",
    response_model=WorkflowDetailResponse,
    operation_id="update_workflow",
    summary="Update metadata or append an immutable draft with expected_version",
    responses={
        200: {"headers": REQUEST_ID_HEADER},
        409: {
            "model": ErrorResponse,
            "headers": REQUEST_ID_HEADER,
            "description": "Workflow archived or expected version is stale",
        },
    },
)
def update_workflow(
    workflow_id: UUID,
    data: WorkflowUpdateRequest,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
) -> WorkflowDetailResponse:
    result = WorkflowService(database).update(workflow_id=workflow_id, owner_id=user.id, data=data)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.delete(
    "/{workflow_id}",
    status_code=204,
    response_class=Response,
    operation_id="archive_workflow",
    summary="Archive without deleting saved history",
    responses={204: {"headers": REQUEST_ID_HEADER}},
)
def archive_workflow(workflow_id: UUID, user: CurrentUser, database: DatabaseResource) -> Response:
    WorkflowService(database).archive(workflow_id=workflow_id, owner_id=user.id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.post(
    "/{workflow_id}/validate",
    response_model=WorkflowValidationResponse,
    operation_id="validate_workflow",
    summary="Validate an owned saved version or unsaved candidate without executing",
    description=(
        "Send {} for current version, version_id for history, or definition for a candidate. "
        "Semantic errors return 200 with valid=false. Validation never saves or activates."
    ),
    responses={200: {"headers": REQUEST_ID_HEADER}},
)
def validate_workflow(
    workflow_id: UUID,
    data: WorkflowValidationRequest,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
) -> WorkflowValidationResponse:
    result = WorkflowValidationService(database).validate(
        workflow_id=workflow_id, owner_id=user.id, data=data
    )
    response.headers["Cache-Control"] = "no-store"
    return result
