"""Only bounded operational metadata may enter API responses and durable events."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

ProviderFailure = Literal[
    "PROVIDER_NOT_CONFIGURED",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_MODEL_UNAVAILABLE",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_CONTEXT_LIMIT",
    "PROVIDER_UNAVAILABLE",
    "PROVIDER_INVALID_RESPONSE",
    "PROVIDER_OUTPUT_LIMIT",
    "DEADLINE_EXCEEDED",
]


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    prompt_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    completion_tokens: int | None = Field(default=None, ge=0, le=100_000_000)
    total_tokens: int | None = Field(default=None, ge=0, le=200_000_000)

    @model_validator(mode="after")
    def consistent_total(self) -> Self:
        if self.total_tokens is not None:
            reported = sum(
                value for value in (self.prompt_tokens, self.completion_tokens) if value is not None
            )
            if reported > self.total_tokens:
                raise ValueError("Reported usage is inconsistent")
        return self


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    provider: Literal["groq"] = "groq"
    requested_model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
    model: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
    duration_ms: int = Field(ge=0, le=86_400_000)
    usage: TokenUsage | None = None
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter"] | None = None
    error_code: ProviderFailure | None = None
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86400)
