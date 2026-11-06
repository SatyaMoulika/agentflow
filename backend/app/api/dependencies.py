"""Resolve application resources, never share a mutable request Session."""

import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import SecretStr

from app.api.auth_cookies import cookie_names
from app.core.config import Settings
from app.core.refresh_tokens import RefreshCredentials, valid_opaque_token
from app.core.tokens import AccessTokens, InvalidAccessTokenError
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import CsrfError, RefreshRejectedError
from app.modules.auth.schemas import UserResponse
from app.modules.auth.service import AuthService

bearer = HTTPBearer(auto_error=False, scheme_name="AccessBearer", bearerFormat="JWT")


async def get_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_database_resource(request: Request) -> Database | None:
    """Shared injection point for the optional process-local engine owner."""
    database = getattr(request.app.state, "database", None)
    return database if isinstance(database, Database) else None


async def require_auth_origin(
    request: Request,
    client: Annotated[
        str | None, Header(alias="X-AgentFlow-Client", description="Set to web")
    ] = None,
) -> None:
    settings: Settings = request.app.state.settings
    origins = request.headers.getlist("origin")
    if len(origins) != 1 or origins[0] not in settings.auth_allowed_origins or client != "web":
        raise CsrfError()


def _read_cookie_credentials(
    request: Request, csrf_header: str | None, *, allow_missing: bool
) -> RefreshCredentials | None:
    settings: Settings = request.app.state.settings
    refresh_name, csrf_name = cookie_names(settings.refresh_cookie_secure)
    raw = request.cookies.get(refresh_name, "")
    if not valid_opaque_token(raw):
        if allow_missing:
            return None
        raise RefreshRejectedError()
    csrf_cookie = request.cookies.get(csrf_name, "")
    if (
        csrf_header is None
        or not valid_opaque_token(csrf_header)
        or not valid_opaque_token(csrf_cookie)
        or not secrets.compare_digest(csrf_header, csrf_cookie)
    ):
        raise CsrfError()
    return RefreshCredentials(SecretStr(raw), SecretStr(csrf_header))


async def get_refresh_credentials(
    request: Request,
    origin_check: Annotated[None, Depends(require_auth_origin)],
    csrf_header: Annotated[str | None, Header(alias="X-AgentFlow-CSRF")] = None,
) -> RefreshCredentials:
    credentials = _read_cookie_credentials(request, csrf_header, allow_missing=False)
    assert credentials is not None
    return credentials


async def get_logout_credentials(
    request: Request,
    origin_check: Annotated[None, Depends(require_auth_origin)],
    csrf_header: Annotated[str | None, Header(alias="X-AgentFlow-CSRF")] = None,
) -> RefreshCredentials | None:
    return _read_cookie_credentials(request, csrf_header, allow_missing=True)


async def get_logout_database(
    credentials: Annotated[RefreshCredentials | None, Depends(get_logout_credentials)],
    database: Annotated[Database | None, Depends(get_database_resource)],
) -> Database | None:
    # A browser with no usable credential can clear cookies even in health-only mode.
    if credentials is not None and database is None:
        raise HTTPException(status_code=503)
    return database if credentials is not None else None


async def get_access_tokens(request: Request) -> AccessTokens:
    settings: Settings = request.app.state.settings
    if settings.jwt_secret_key is None:
        raise HTTPException(status_code=503)
    return AccessTokens(
        secret=settings.jwt_secret_key,
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        ttl_seconds=settings.access_token_ttl_seconds,
    )


async def get_access_subject(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> UUID:
    if credentials is None:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    tokens = await get_access_tokens(request)
    try:
        return tokens.subject(credentials.credentials)
    except InvalidAccessTokenError:
        raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"}) from None


async def get_database(
    database: Annotated[Database | None, Depends(get_database_resource)],
) -> Database:
    """The engine owner is safe to pass to a worker; the service opens its own Session."""
    if database is None:
        raise HTTPException(status_code=503)
    return database


def get_current_user(
    user_id: Annotated[UUID, Depends(get_access_subject)],
    database: Annotated[Database, Depends(get_database)],
) -> UserResponse:
    return AuthService(database).current_user(user_id)
