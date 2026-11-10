"""Configuration drives the app without changing the public health contract."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_injected_settings_control_application_metadata() -> None:
    settings = Settings(app_name="Test API", environment="testing", debug=True)
    application = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        schema = (await client.get("/openapi.json")).json()
        health = await client.get("/api/v1/health")

    assert application.state.settings is settings
    assert application.debug is True
    assert schema["info"]["title"] == "Test API"
    assert health.json() == {"status": "ok", "service": "agentflow"}


async def test_disabling_docs_removes_all_documentation_routes_but_keeps_health() -> None:
    application = create_app(Settings(docs_enabled=False))

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentflow"}
