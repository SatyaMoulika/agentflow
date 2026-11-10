"""Credential inputs are write-only; metadata responses have no secret field."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.modules.connections.policy import endpoint_url


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    name: str = Field(min_length=1, max_length=100)
    endpoint_url: str = Field(min_length=1, max_length=1000)
    auth_type: Literal["none", "bearer", "api_key"] = "none"
    secret: SecretStr | None = Field(default=None, repr=False)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name must not be blank")
        return value.strip()

    @field_validator("endpoint_url")
    @classmethod
    def check_endpoint(cls, value: str) -> str:
        return endpoint_url(value)

    @model_validator(mode="after")
    def check_credential(self) -> Self:
        if self.auth_type == "none":
            if self.secret is not None:
                raise ValueError("An unauthenticated connection must not include a secret")
        else:
            value = self.secret.get_secret_value() if self.secret is not None else ""
            if (
                not 8 <= len(value) <= 4096
                or not value.isascii()
                or any(ord(char) <= 32 or ord(char) == 127 for char in value)
            ):
                raise ValueError("Credentials require 8–4096 printable ASCII characters")
        return self


class ConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    name: str
    endpoint_url: str
    auth_type: Literal["none", "bearer", "api_key"]
    created_at: datetime
    revoked_at: datetime | None


class ConnectionPage(BaseModel):
    items: list[ConnectionResponse]
    total: int
    page: int
    page_size: int


class PlannerConnection(BaseModel):
    """The complete metadata allowlist that may be sent to the workflow planner."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: str
    endpoint_url: str
