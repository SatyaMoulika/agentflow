"""Authenticated, explicitly requested Groq completions; no workflow side effects."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies import get_current_user, get_settings
from app.core.config import Settings
from app.core.exceptions import REQUEST_ID_HEADER, ErrorResponse
from app.modules.auth.schemas import UserResponse
from app.modules.executions.groq_provider import GroqError, complete

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
    try:
        result = complete(settings, data.prompt)
    except GroqError as error:
        raise HTTPException(status_code=error.status) from None
    response.headers["Cache-Control"] = "no-store"
    return GroqResponse(**result)
