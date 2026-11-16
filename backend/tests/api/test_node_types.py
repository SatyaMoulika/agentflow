"""Authenticated catalog exposes schemas without claiming unavailable runtime features."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.main import create_app
from app.modules.auth.schemas import UserResponse

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("headers", [{}, {"Cookie": "agentflow_refresh=private-cookie"}])
async def test_catalog_requires_bearer_before_resource_lookup(headers: dict[str, str]) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.get("/api/v1/node-types", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-cookie" not in response.text


async def test_catalog_returns_contracts_and_handles_with_no_external_configuration() -> None:
    application = create_app()

    async def user() -> UserResponse:
        return UserResponse(
            id=uuid4(),
            email="catalog@example.com",
            display_name="Catalog",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    application.dependency_overrides[get_current_user] = user
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="https://test"
    ) as client:
        first = await client.get("/api/v1/node-types")
        second = await client.get("/api/v1/node-types")
    assert first.status_code == 200 and first.json() == second.json()
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["x-request-id"] != second.headers["x-request-id"]
    catalog = first.json()
    assert catalog["schema_version"] == "1.0"
    items = {item["type"]: item for item in catalog["items"]}
    assert set(items) == {
        "manual",
        "transform",
        "condition",
        "calculator",
        "merge",
        "end",
        "groq",
        "json_parser",
        "classify",
        "extract",
        "http",
        "agent",
        "gmail_read",
    }
    for kind, item in items.items():
        ready = kind in {
            "manual",
            "transform",
            "condition",
            "calculator",
            "merge",
            "end",
            "groq",
            "json_parser",
            "classify",
            "extract",
            "http",
            "agent",
            "gmail_read",
        }
        assert item["execution_ready"] is ready
        assert item["capabilities"] == (
            ["validate_config", "execute"] if ready else ["validate_config"]
        )
    assert items["condition"]["output_handles"] == ["true", "false"]
    assert items["end"]["output_handles"] == []
    assert items["calculator"]["config_schema"]["discriminator"]["propertyName"] == "operation"
    assert "gpt-4" not in first.text


async def test_catalog_openapi_uses_bearer_and_static_readiness_contract() -> None:
    schema = create_app().openapi()
    route = schema["paths"]["/api/v1/node-types"]
    assert set(route) == {"get"}
    operation = route["get"]
    assert operation["operationId"] == "list_node_types"
    assert operation["security"] == [{"AccessBearer": []}]
    for code in ("401", "503"):
        assert operation["responses"][code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse",
        }
    response = schema["components"]["schemas"]["NodeTypeResponse"]
    assert response["additionalProperties"] is False
    assert response["properties"]["execution_ready"]["type"] == "boolean"
    assert response["properties"]["capabilities"]["items"]["enum"] == ["validate_config", "execute"]
