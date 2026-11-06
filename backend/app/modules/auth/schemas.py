"""Strict credential input and explicit public user/token output, separate from storage."""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
)


class _EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    email: EmailStr = Field(max_length=320)

    @field_validator("email", mode="before")
    @classmethod
    def trim_public_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Case-insensitive account identity, matching the database storage constraint."""
        return value.lower()


class LoginRequest(_EmailInput):
    password: SecretStr = Field(min_length=1, max_length=128, repr=False)


class RegisterRequest(_EmailInput):
    password: SecretStr = Field(min_length=8, max_length=128, repr=False)
    display_name: str = Field(min_length=1, max_length=100)

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("password")
    @classmethod
    def reject_blank_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("Password must contain a non-whitespace character")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    email: str
    display_name: str
    is_active: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def as_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class LoginResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str = Field(repr=False)
    csrf_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(gt=0)
    user: UserResponse
