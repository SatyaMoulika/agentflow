"""An optional worker broker is not an API liveness dependency."""

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


@pytest.mark.anyio
async def test_health_starts_when_configured_worker_broker_is_unreachable() -> None:
    application = create_app(Settings(redis_url=SecretStr("redis://127.0.0.1:1/0")))
    async with LifespanManager(application):
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentflow"}
