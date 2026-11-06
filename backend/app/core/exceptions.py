"""Public HTTP error schemas and mappings; never serialize raw exceptions."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

REQUEST_ID_PATTERN = r"^req_[0-9a-f]{32}$"
REQUEST_ID_HEADER = {
    "X-Request-ID": {
        "description": "Server-generated correlation ID, also present in error bodies and logs.",
        "schema": {"type": "string", "pattern": REQUEST_ID_PATTERN},
    }
}


class ErrorDetail(BaseModel):
    """Only deliberately public information belongs in an error response."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: None


class ErrorResponse(BaseModel):
    """The shared error envelope; details stay null in this foundation increment."""

    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)


HTTP_ERRORS = {
    400: ("BAD_REQUEST", "The request could not be processed."),
    401: ("UNAUTHENTICATED", "Authentication is required."),
    403: ("FORBIDDEN", "You do not have permission to perform this operation."),
    404: ("NOT_FOUND", "The requested resource does not exist."),
    405: ("METHOD_NOT_ALLOWED", "This HTTP method is not allowed."),
    409: ("CONFLICT", "The request conflicts with the current resource state."),
    413: ("REQUEST_TOO_LARGE", "The request is too large."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "The request content type is not supported."),
    422: ("VALIDATION_ERROR", "The request is invalid."),
    429: ("RATE_LIMITED", "Too many requests. Please try again later."),
    503: ("SERVICE_UNAVAILABLE", "The service is temporarily unavailable."),
}
INTERNAL_ERROR = ("INTERNAL_ERROR", "An unexpected error occurred.")


def error_response(
    request: Request,
    status_code: int,
    headers: dict[str, str] | None = None,
    *,
    public_error: tuple[str, str] | None = None,
) -> JSONResponse:
    """Build a validated envelope from static messages and request state."""
    fallback = (
        INTERNAL_ERROR
        if status_code >= 500
        else ("HTTP_ERROR", "The request could not be processed.")
    )
    code, message = (
        public_error if public_error is not None else HTTP_ERRORS.get(status_code, fallback)
    )
    payload = ErrorResponse(
        error=ErrorDetail(code=code, message=message, details=None),
        request_id=request.state.request_id,
    )
    return JSONResponse(payload.model_dump(), status_code=status_code, headers=headers)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Preserve protocol headers, not arbitrary detail strings or custom headers."""
    # Framework callbacks accept Exception; registration dispatches the subtype.
    assert isinstance(exc, HTTPException)
    headers = {
        key: value
        for key, value in (exc.headers or {}).items()
        if key.lower() in {"allow", "www-authenticate", "retry-after"}
    }
    return error_response(request, exc.status_code, headers)


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Raw validation messages, input, locations, and contexts can contain private data."""
    assert isinstance(exc, RequestValidationError)
    return error_response(request, 422)


def register_exception_handlers(application: FastAPI) -> None:
    """Cover both framework routing errors and FastAPI request validation."""
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
