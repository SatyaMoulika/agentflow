"""Registration/login and authenticated identity with safe application-error mapping."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.auth_cookies import clear_auth_cookies, set_auth_cookies
from app.api.dependencies import (
    get_access_tokens,
    get_current_user,
    get_database,
    get_logout_credentials,
    get_logout_database,
    get_refresh_credentials,
    get_settings,
    require_auth_origin,
)
from app.core.config import Settings
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse, error_response
from app.core.refresh_tokens import RefreshCredentials
from app.core.tokens import AccessTokens
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import (
    AuthenticationError,
    AuthStorageUnavailableError,
    CsrfError,
    EmailAlreadyRegisteredError,
    RefreshRejectedError,
)
from app.modules.auth.schemas import LoginRequest, LoginResponse, RegisterRequest, UserResponse
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    operation_id="register_user",
    summary="Register a user",
    description="Creates a user with an Argon2id password hash. Does not issue tokens or cookies.",
    responses={
        201: {"headers": REQUEST_ID_HEADER},
        409: {
            "model": ErrorResponse,
            "description": "Email is already registered",
            "headers": REQUEST_ID_HEADER,
        },
        422: {
            "model": ErrorResponse,
            "description": "Invalid registration input",
            "headers": REQUEST_ID_HEADER,
        },
        503: {
            "model": ErrorResponse,
            "description": "Registration storage unavailable",
            "headers": REQUEST_ID_HEADER,
        },
    },
)
def register_user(
    data: RegisterRequest,
    response: Response,
    database: Annotated[Database, Depends(get_database)],
) -> UserResponse:
    """Hashing and all session work execute in this synchronous route's worker thread."""
    result = AuthService(database).register(data)
    response.headers["Cache-Control"] = "no-store"
    return result


AUTH_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"headers": REQUEST_ID_HEADER},
    401: {
        "model": ErrorResponse,
        "description": "Credentials do not identify an active account",
        "headers": {
            **REQUEST_ID_HEADER,
            "WWW-Authenticate": {"schema": {"type": "string"}, "description": "Bearer challenge"},
        },
    },
    503: {
        "model": ErrorResponse,
        "description": "Authentication configuration or storage unavailable",
        "headers": REQUEST_ID_HEADER,
    },
    403: {
        "model": ErrorResponse,
        "description": "Origin/client marker or CSRF proof rejected",
        "headers": REQUEST_ID_HEADER,
    },
}


@router.post(
    "/login",
    response_model=LoginResponse,
    operation_id="login_user",
    summary="Log in with email and password",
    description=(
        "Requires an allowed Origin and X-AgentFlow-Client: web. "
        "Returns an access JWT and CSRF token; sets refresh/CSRF cookies."
    ),
    dependencies=[Depends(require_auth_origin)],
    responses={
        **AUTH_RESPONSES,
        422: {"model": ErrorResponse, "headers": REQUEST_ID_HEADER, "description": "Invalid input"},
    },
)
def login_user(
    data: LoginRequest,
    response: Response,
    database: Annotated[Database, Depends(get_database)],
    tokens: Annotated[AccessTokens, Depends(get_access_tokens)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    result = AuthService(database).login(data, tokens, settings.refresh_token_ttl_seconds)
    set_auth_cookies(response, result, secure=settings.refresh_cookie_secure)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return result.body


@router.post(
    "/refresh",
    response_model=LoginResponse,
    operation_id="refresh_session",
    summary="Rotate the refresh cookie and issue a new access token",
    description=(
        "Requires refresh/CSRF cookies, allowed Origin, X-AgentFlow-Client: web, "
        "and X-AgentFlow-CSRF matching the CSRF cookie. No body credentials accepted. "
        "Reusing a consumed token revokes its entire refresh family."
    ),
    responses=AUTH_RESPONSES,
)
def refresh_session(
    response: Response,
    credentials: Annotated[RefreshCredentials, Depends(get_refresh_credentials)],
    database: Annotated[Database, Depends(get_database)],
    tokens: Annotated[AccessTokens, Depends(get_access_tokens)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    result = AuthService(database).refresh(credentials, tokens)
    set_auth_cookies(response, result, secure=settings.refresh_cookie_secure)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return result.body


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="logout_session",
    summary="Revoke the current refresh family and clear its cookies",
    description=(
        "Requires allowed Origin and X-AgentFlow-Client: web. When a refresh cookie "
        "is present, requires its matching CSRF cookie/header and server binding. "
        "Idempotent 204 for absent/malformed/unknown or already revoked credentials. "
        "Existing access JWTs retain their expiry; no Bearer token or body is required."
    ),
    responses={
        **{code: definition for code, definition in AUTH_RESPONSES.items() if code in {403, 503}},
        204: {
            "description": "Refresh family revoked or already absent",
            "headers": REQUEST_ID_HEADER,
        },
    },
)
def logout_session(
    credentials: Annotated[RefreshCredentials | None, Depends(get_logout_credentials)],
    database: Annotated[Database | None, Depends(get_logout_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    if credentials is not None:
        assert database is not None
        AuthService(database).logout(credentials)
    response = Response(
        status_code=204, headers={"Cache-Control": "no-store", "Pragma": "no-cache"}
    )
    clear_auth_cookies(response, secure=settings.refresh_cookie_secure)
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    operation_id="get_current_user",
    summary="Get the current active user",
    responses=AUTH_RESPONSES,
)
def read_current_user(
    response: Response,
    user: Annotated[UserResponse, Depends(get_current_user)],
) -> UserResponse:
    response.headers["Cache-Control"] = "no-store"
    return user


async def email_conflict_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, EmailAlreadyRegisteredError)
    return error_response(
        request,
        409,
        public_error=("EMAIL_ALREADY_REGISTERED", "An account with this email already exists."),
    )


async def storage_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthStorageUnavailableError)
    return error_response(request, 503)


async def authentication_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AuthenticationError)
    response = error_response(request, 401, headers={"WWW-Authenticate": "Bearer"})
    if isinstance(exc, RefreshRejectedError):
        clear_auth_cookies(response, secure=request.app.state.settings.refresh_cookie_secure)
        response.headers["Cache-Control"] = "no-store"
    return response


async def csrf_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, CsrfError)
    return error_response(request, 403)


def register_auth_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(EmailAlreadyRegisteredError, email_conflict_handler)
    application.add_exception_handler(AuthStorageUnavailableError, storage_unavailable_handler)
    application.add_exception_handler(AuthenticationError, authentication_handler)
    application.add_exception_handler(CsrfError, csrf_handler)
