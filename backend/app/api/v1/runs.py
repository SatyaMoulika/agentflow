"""Owner-authenticated run commands with explicit queued/synchronous delivery."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    Security,
)
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import (
    bearer,
    get_access_tokens,
    get_current_user,
    get_database,
    get_settings,
)
from app.core.config import Settings
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse, error_response
from app.core.tokens import AccessTokens
from app.infrastructure.database.session import Database
from app.modules.auth.schemas import UserResponse
from app.modules.executions.event_stream import stream_events
from app.modules.executions.exceptions import (
    ExecutionConflictError,
    ExecutionNotFoundError,
    ExecutionStorageUnavailableError,
    WorkflowNotExecutableError,
)
from app.modules.executions.schemas import (
    ExecutionEventPage,
    RunCreateRequest,
    RunListParams,
    RunPage,
    RunResponse,
    RunRetryRequest,
)
from app.modules.executions.service import ExecutionService

ERRORS: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorResponse, "headers": REQUEST_ID_HEADER, "description": description}
    for code, description in (
        (401, "Active user authentication required"),
        (404, "Missing or not-owned workflow, version or run"),
        (409, "Archived workflow or incompatible execution state"),
        (422, "Invalid command or saved version not executable by this runner"),
        (503, "Storage unavailable; Location may identify a previously committed run"),
    )
}
router = APIRouter(tags=["runs"], responses=ERRORS)
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
DatabaseResource = Annotated[Database, Depends(get_database)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_idempotency_key(
    request: Request,
    key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
        ),
    ] = None,
) -> str | None:
    if len(request.headers.getlist("idempotency-key")) > 1:
        raise HTTPException(status_code=422)
    return key


IdempotencyKey = Annotated[str | None, Depends(get_idempotency_key)]


@router.get(
    "/runs",
    response_model=RunPage,
    operation_id="list_workflow_runs",
    summary="List owned run summaries without business payloads",
)
def list_workflow_runs(
    params: Annotated[RunListParams, Query()],
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
) -> RunPage:
    result = ExecutionService(database).list(owner_id=user.id, params=params)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/workflows/{workflow_id}/runs",
    response_model=RunResponse,
    status_code=201,
    operation_id="create_workflow_run",
    summary="Execute an exact saved workflow with exclusive branch routing",
    description=(
        "Requires workflow_version_id and object input. With background execution enabled, "
        "pure graphs create durable queued work and return 202 without calling the broker. "
        "Otherwise, including Groq graphs, execution stays synchronous and returns 201. "
        "execution_mode records the original mode, including on idempotent replay. An optional "
        "Idempotency-Key is owner-scoped across create/retry commands; "
        "changed commands return 409. "
        "Conditions choose one branch; unvisited nodes are skipped at successful completion. "
        "max_attempts (1–3, default 1) bounds pure-node attempts on internal/deadline failures. "
        "Background retries use a saved exponential delay; synchronous retries are immediate. "
        "Groq nodes send selected input to the configured provider once. "
        "Background workers never replay Groq calls."
    ),
    responses={
        201: {"headers": REQUEST_ID_HEADER},
        202: {
            "model": RunResponse,
            "headers": REQUEST_ID_HEADER,
            "description": "Durably queued run",
        },
    },
)
def create_workflow_run(
    workflow_id: UUID,
    data: RunCreateRequest,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
) -> RunResponse:
    result = ExecutionService(database, settings).create_and_execute(
        workflow_id=workflow_id,
        owner_id=user.id,
        data=data,
        idempotency_key=idempotency_key,
    )
    response.headers["Location"] = f"/api/v1/runs/{result.id}"
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 202 if result.execution_mode == "background" else 201
    return result


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunResponse,
    operation_id="cancel_workflow_run",
    summary="Cancel an owned active run and its open attempts atomically",
    description=(
        "Repeated cancellation returns cancelled history; other terminal states return 409. "
        "Pure computation may finish, but its result cannot overwrite cancellation."
    ),
)
def cancel_workflow_run(
    run_id: UUID, response: Response, user: CurrentUser, database: DatabaseResource
) -> RunResponse:
    result = ExecutionService(database).cancel(run_id=run_id, owner_id=user.id)
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/runs/{run_id}/retry",
    response_model=RunResponse,
    status_code=201,
    operation_id="retry_workflow_run",
    summary="Create a new pure run from a failed or cancelled run",
    description=(
        "Re-executes the full saved version/input with parent_run_id lineage. "
        "JSON max_attempts is optional (1–3). Idempotency-Key prevents duplicate retry runs. "
        "Active/succeeded sources and archived workflows return 409. No partial external replay."
    ),
    responses={
        202: {
            "model": RunResponse,
            "headers": REQUEST_ID_HEADER,
            "description": "Durably queued full-workflow retry",
        }
    },
)
def retry_workflow_run(
    run_id: UUID,
    data: RunRetryRequest,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
) -> RunResponse:
    result = ExecutionService(database, settings).retry(
        run_id=run_id,
        owner_id=user.id,
        max_attempts=data.max_attempts,
        idempotency_key=idempotency_key,
    )
    response.headers["Location"] = f"/api/v1/runs/{result.id}"
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 202 if result.execution_mode == "background" else 201
    return result


@router.get(
    "/runs/{run_id}/events",
    response_model=ExecutionEventPage,
    operation_id="list_workflow_run_events",
    summary="Read ordered events for an owned run",
    description="Poll with next_after_sequence to continue from the last returned event.",
)
def list_workflow_run_events(
    run_id: UUID,
    response: Response,
    user: CurrentUser,
    database: DatabaseResource,
    after_sequence: Annotated[int, Query(ge=0, le=9223372036854775807)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> ExecutionEventPage:
    result = ExecutionService(database).events(
        run_id=run_id, owner_id=user.id, after_sequence=after_sequence, limit=limit
    )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get(
    "/runs/{run_id}/events/stream",
    operation_id="stream_workflow_run_events",
    summary="Stream authorized execution events with sequence replay",
    description="Reconnect with Last-Event-ID. Connections close periodically to reauthenticate.",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def stream_workflow_run_events(
    run_id: UUID,
    request: Request,
    user: CurrentUser,
    database: DatabaseResource,
    tokens: Annotated[AccessTokens, Depends(get_access_tokens)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID", max_length=19)] = None,
) -> StreamingResponse:
    if credentials is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    if len(request.headers.getlist("last-event-id")) > 1:
        raise HTTPException(status_code=422)
    if last_event_id is not None and (
        not last_event_id.isascii()
        or not last_event_id.isdecimal()
        or int(last_event_id) > 9223372036854775807
    ):
        raise HTTPException(status_code=422)
    cursor = int(last_event_id) if last_event_id is not None else 0
    page = await run_in_threadpool(
        lambda: ExecutionService(database).events(
            run_id=run_id, owner_id=user.id, after_sequence=cursor, limit=100
        )
    )
    return StreamingResponse(
        stream_events(database, run_id, user.id, credentials.credentials, tokens, page),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    operation_id="get_workflow_run",
    summary="Read an owned run, its exact saved version and node-attempt history",
    responses={200: {"headers": REQUEST_ID_HEADER}},
)
def get_workflow_run(
    run_id: UUID, response: Response, user: CurrentUser, database: DatabaseResource
) -> RunResponse:
    result = ExecutionService(database).get(run_id=run_id, owner_id=user.id)
    response.headers["Cache-Control"] = "no-store"
    return result


async def execution_not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 404)


async def execution_conflict(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 409)


async def workflow_not_executable(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        request,
        422,
        public_error=(
            "WORKFLOW_NOT_EXECUTABLE",
            "The saved version cannot run with the currently supported executors.",
        ),
    )


async def execution_storage_unavailable(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ExecutionStorageUnavailableError)
    headers = {"Cache-Control": "no-store"}
    if exc.run_id is not None:
        headers["Location"] = f"/api/v1/runs/{exc.run_id}"
    return error_response(request, 503, headers)


def register_execution_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ExecutionNotFoundError, execution_not_found)
    application.add_exception_handler(ExecutionConflictError, execution_conflict)
    application.add_exception_handler(WorkflowNotExecutableError, workflow_not_executable)
    application.add_exception_handler(
        ExecutionStorageUnavailableError, execution_storage_unavailable
    )
