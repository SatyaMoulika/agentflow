"""Public liveness check, independent of databases and external providers."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.core.exceptions import REQUEST_ID_HEADER

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """The deliberately small, non-sensitive liveness response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    service: Literal["agentflow"]


@router.get(
    "/health",
    response_model=HealthResponse,
    operation_id="get_health",
    responses={200: {"headers": REQUEST_ID_HEADER}},
    summary="Check API liveness",
    description=(
        "Confirms that the API can handle a request. "
        "Does not check PostgreSQL, Redis, Groq, or worker readiness."
    ),
)
async def get_health() -> HealthResponse:
    """Return liveness without network calls, credentials, or database sessions."""
    return HealthResponse(status="ok", service="agentflow")
