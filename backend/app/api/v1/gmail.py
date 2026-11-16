"""Owner-authenticated Gmail OAuth setup and manual inbox discovery."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.dependencies import get_current_user, get_database, get_settings
from app.core.config import Settings
from app.core.exceptions import error_response
from app.infrastructure.database.session import Database
from app.modules.auth.schemas import UserResponse
from app.modules.gmail.provider import GmailProviderError
from app.modules.gmail.schemas import (
    GmailAuthorizationUrl,
    GmailCompleteRequest,
    GmailConnectionResponse,
)
from app.modules.gmail.service import (
    GmailAuthorizationRejected,
    GmailConnectionNotFound,
    GmailNotConfigured,
    GmailService,
)

router = APIRouter(prefix="/gmail", tags=["gmail"])
CurrentUser = Annotated[UserResponse, Depends(get_current_user)]
DatabaseResource = Annotated[Database, Depends(get_database)]
Configuration = Annotated[Settings, Depends(get_settings)]


@router.post("/authorize", response_model=GmailAuthorizationUrl)
def authorize(
    user: CurrentUser, database: DatabaseResource, settings: Configuration, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return GmailAuthorizationUrl(url=GmailService(database, settings).begin(user.id))


@router.post("/complete", response_model=GmailConnectionResponse, status_code=201)
def complete(
    data: GmailCompleteRequest,
    user: CurrentUser,
    database: DatabaseResource,
    settings: Configuration,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    return GmailService(database, settings).complete(user.id, data.state, data.code)


@router.get("/connections", response_model=list[GmailConnectionResponse])
def list_connections(
    user: CurrentUser, database: DatabaseResource, settings: Configuration, response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return GmailService(database, settings).list_connections(user.id)


@router.get("/connections/{connection_id}/messages", response_model=list[str])
def list_messages(
    connection_id: UUID,
    user: CurrentUser,
    database: DatabaseResource,
    settings: Configuration,
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    return GmailService(database, settings).list_messages(user.id, connection_id)


@router.delete("/connections/{connection_id}", status_code=204)
def revoke(
    connection_id: UUID, user: CurrentUser, database: DatabaseResource, settings: Configuration
):
    GmailService(database, settings).revoke(user.id, connection_id)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


async def authorization_rejected(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 409, headers={"Cache-Control": "no-store"})


async def connection_not_found(request: Request, exc: Exception) -> JSONResponse:
    return error_response(request, 404, headers={"Cache-Control": "no-store"})


async def provider_error(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        request,
        502,
        headers={"Cache-Control": "no-store"},
        public_error=("GMAIL_PROVIDER_ERROR", "The Gmail request could not be completed."),
    )


async def not_configured(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        request,
        503,
        headers={"Cache-Control": "no-store"},
        public_error=("GMAIL_NOT_CONFIGURED", "Gmail OAuth is not configured on the server."),
    )


def register_gmail_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(GmailAuthorizationRejected, authorization_rejected)
    application.add_exception_handler(GmailConnectionNotFound, connection_not_found)
    application.add_exception_handler(GmailProviderError, provider_error)
    application.add_exception_handler(GmailNotConfigured, not_configured)
