"""HTTP contract and application-factory checks for Phase 1A."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_health_returns_the_public_json_contract() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "service": "agentflow"}


@pytest.mark.parametrize("path", ["/health", "/api/health", "/api/v2/health"])
async def test_health_is_only_available_under_the_versioned_prefix(path: str) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get(path)

    assert response.status_code == 404


async def test_health_requires_neither_authentication_nor_external_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("DATABASE_URL", "REDIS_URL", "GROQ_API_KEY", "LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentflow"}


async def test_openapi_documents_health_and_only_the_implemented_endpoints() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert set(schema["paths"]) == {
        "/api/v1/approvals",
        "/api/v1/approvals/{approval_id}",
        "/api/v1/approvals/{approval_id}/decision",
        "/api/v1/connections",
        "/api/v1/connections/{connection_id}",
        "/api/v1/workflows/generate",
        "/api/v1/workflows/{workflow_id}/edit-proposal",
        "/api/v1/ai/completions",
        "/api/v1/health",
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/node-types",
        "/api/v1/workflows",
        "/api/v1/workflows/{workflow_id}",
        "/api/v1/workflows/{workflow_id}/validate",
        "/api/v1/workflows/{workflow_id}/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/events",
        "/api/v1/runs/{run_id}/events/stream",
        "/api/v1/runs",
        "/api/v1/runs/{run_id}/cancel",
        "/api/v1/runs/{run_id}/retry",
        "/api/v1/runs/{run_id}/agent-resume",
        "/api/v1/gmail/authorize",
        "/api/v1/gmail/complete",
        "/api/v1/gmail/connections",
        "/api/v1/gmail/connections/{connection_id}",
        "/api/v1/gmail/connections/{connection_id}/messages",
    }
    operation = schema["paths"]["/api/v1/health"]["get"]
    assert operation["operationId"] == "get_health"
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthResponse",
    }
    response_schema = schema["components"]["schemas"]["HealthResponse"]
    assert set(response_schema["required"]) == {"status", "service"}
    assert response_schema["properties"]["status"]["const"] == "ok"
    assert response_schema["properties"]["service"]["const"] == "agentflow"
    assert response_schema["additionalProperties"] is False


async def test_factory_instances_do_not_share_routes_or_application_state() -> None:
    first = create_app()
    second = create_app()
    first.state.test_marker = "first application only"

    @first.get("/test-only", include_in_schema=False)
    async def test_only_route() -> dict[str, str]:
        return {"instance": "first"}

    assert first is not second
    assert not hasattr(second.state, "test_marker")
    async with (
        AsyncClient(transport=ASGITransport(app=first), base_url="http://test") as first_client,
        AsyncClient(transport=ASGITransport(app=second), base_url="http://test") as second_client,
    ):
        assert (await first_client.get("/test-only")).status_code == 200
        assert (await second_client.get("/test-only")).status_code == 404
        assert (await second_client.get("/api/v1/health")).status_code == 200


async def test_interactive_api_documentation_is_served() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.get("/docs")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
