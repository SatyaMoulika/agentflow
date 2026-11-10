"""Registration validation, unavailable storage and OpenAPI without database I/O."""

from collections.abc import Iterator

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.dependencies import get_database_resource
from app.infrastructure.database.session import Database
from app.main import create_app

pytestmark = pytest.mark.anyio
PAYLOAD = {
    "email": "owner@example.com",
    "display_name": "Owner",
    "password": "private-test-passphrase",
}


@pytest.fixture
def unconnected_database() -> Iterator[Database]:
    database = Database(SecretStr("postgresql+psycopg://unconnected@localhost/unused"))
    yield database
    database.dispose()


async def test_missing_database_returns_safe_503_and_preserves_health(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/register", json=PAYLOAD)
        assert (await client.get("/api/v1/health")).json() == {
            "status": "ok",
            "service": "agentflow",
        }

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "The service is temporarily unavailable.",
            "details": None,
        },
        "request_id": response.headers["x-request-id"],
    }
    assert PAYLOAD["password"] not in response.text + caplog.text


@pytest.mark.parametrize(
    "changes",
    [
        {"password": "private"},
        {"password": "x" * 129},
        {"password": " " * 8},
        {"email": "private-invalid-email"},
        {"display_name": " "},
        {"is_active": True},
    ],
)
async def test_invalid_registration_is_422_without_echoed_fields(
    changes: dict,
    unconnected_database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = create_app()

    async def resource_override() -> Database:
        return unconnected_database

    application.dependency_overrides[get_database_resource] = resource_override
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post("/api/v1/auth/register", json=PAYLOAD | changes)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"] is None
    assert response.json()["request_id"] == response.headers["x-request-id"]
    for secret in (PAYLOAD["password"], "private", "private-invalid-email"):
        assert secret not in response.text + caplog.text


async def test_openapi_registration_schemas_match_public_contract() -> None:
    schema = create_app().openapi()
    assert set(schema["paths"]) == {
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
    }
    operation = schema["paths"]["/api/v1/auth/register"]["post"]
    assert operation["operationId"] == "register_user"
    for status in ("409", "422", "503"):
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UserResponse"
    }
    password = schema["components"]["schemas"]["RegisterRequest"]["properties"]["password"]
    assert password["writeOnly"] is True
    assert password["minLength"] == 8 and password["maxLength"] == 128
    fields = schema["components"]["schemas"]["UserResponse"]["properties"]
    assert set(fields) == {"id", "email", "display_name", "is_active", "created_at", "updated_at"}
