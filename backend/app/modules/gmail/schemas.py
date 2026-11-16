"""Gmail OAuth DTOs never include saved credentials or provider responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class GmailAuthorizationUrl(BaseModel):
    url: str


class GmailCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    state: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    code: SecretStr = Field(min_length=1, max_length=4096)


class GmailConnectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    created_at: datetime
    revoked_at: datetime | None
