"""Authenticated, explicitly requested Groq completions; no workflow side effects."""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies import get_current_user, get_settings
from app.core.config import Settings
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse, error_response
from app.modules.auth.schemas import UserResponse
from app.modules.executions.groq_provider import GroqError, complete
from app.modules.executions.provider_schemas import ProviderMetadata

router = APIRouter(prefix="/ai", tags=["ai"])


class GroqRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=4000)

    @field_validator("prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must not be blank")
        return value


class GroqResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    content: str
    metadata: ProviderMetadata | None = None


@router.post(
    "/completions",
    response_model=GroqResponse,
    operation_id="create_groq_completion",
    summary="Send a prompt to the configured Groq model",
    description="Sends the submitted prompt to Groq. Does not execute or modify workflows.",
    responses={
        code: {"model": ErrorResponse, "headers": REQUEST_ID_HEADER, "description": description}
        for code, description in (
            (401, "Authentication required"),
            (422, "Invalid prompt"),
            (429, "Provider rate limit reached"),
            (503, "Provider or configuration unavailable"),
        )
    },
)
def create_completion(
    data: GroqRequest,
    response: Response,
    user: Annotated[UserResponse, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GroqResponse:
    result = complete(settings, data.prompt)
    response.headers["Cache-Control"] = "no-store"
    return GroqResponse(**result)


async def provider_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, GroqError)
    headers = {"Cache-Control": "no-store"}
    if exc.retry_after is not None:
        headers["Retry-After"] = str(exc.retry_after)
    return error_response(request, exc.status, headers, public_error=(exc.code, str(exc)))


def register_provider_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(GroqError, provider_error)
