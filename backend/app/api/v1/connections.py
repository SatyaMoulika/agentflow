"""Owner-scoped, write-only credential delivery and non-destructive revocation."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user, get_database, get_settings
from app.core.config import Settings
from app.core.exceptions import error_response
from app.infrastructure.database.session import Database
from app.modules.auth.schemas import UserResponse
from app.modules.connections.schemas import ConnectionCreate, ConnectionPage, ConnectionResponse
from app.modules.connections.secrets import ConnectionUnavailableError
from app.modules.connections.service import ConnectionNotFoundError, ConnectionService

router = APIRouter(prefix="/connections", tags=["connections"])
Configuration = Annotated[Settings, Depends(get_settings)]
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
DatabaseResource = Annotated[Database, Depends(get_database)]


@router.post("", status_code=201, response_model=ConnectionResponse)
def create_connection(
    data: ConnectionCreate,
    user: CurrentUser,
    database: DatabaseResource,
    settings: Configuration,
    response: Response,
) -> ConnectionResponse:
    result = ConnectionService(database, settings).create(user.id, data)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Location"] = f"/api/v1/connections/{result.id}"
    return result


@router.get("", response_model=ConnectionPage)
def list_connections(
    user: CurrentUser,
    database: DatabaseResource,
    settings: Configuration,
    response: Response,
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ConnectionPage:
    response.headers["Cache-Control"] = "no-store"
    return ConnectionService(database, settings).list(user.id, page, page_size)


@router.get("/{connection_id}", response_model=ConnectionResponse)
def get_connection(
    connection_id: UUID,
    user: CurrentUser,
    database: DatabaseResource,
    settings: Configuration,
    response: Response,
) -> ConnectionResponse:
    response.headers["Cache-Control"] = "no-store"
    return ConnectionService(database, settings).get(user.id, connection_id)


@router.delete("/{connection_id}", status_code=204)
def revoke_connection(
    connection_id: UUID, user: CurrentUser, database: DatabaseResource, settings: Configuration
) -> Response:
    ConnectionService(database, settings).revoke(user.id, connection_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


async def connection_not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 404)


async def connection_unavailable(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        request,
        503,
        public_error=("CONNECTION_UNAVAILABLE", "Connection storage or encryption is unavailable."),
    )


def register_connection_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(ConnectionNotFoundError, connection_not_found)
    application.add_exception_handler(ConnectionUnavailableError, connection_unavailable)
