"""Public HTTP, validation and OpenAPI contracts without real database work."""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.main import create_app

pytestmark = pytest.mark.anyio
KEY = "test-only-signing-key-not-a-deployment-secret-12345"
PAYLOAD = {"email": "owner@example.com", "password": "private-login-passphrase"}


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer"])
async def test_me_requires_a_bearer_header_without_token_urls_or_cookies(
    header: str | None,
) -> None:
    headers = {} if header is None else {"Authorization": header}
    async with AsyncClient(
        transport=ASGITransport(app=create_app()),
        base_url="http://test",
        headers={"Origin": "http://127.0.0.1:8000", "X-AgentFlow-Client": "web"},
    ) as client:
        response = await client.get(
            "/api/v1/auth/me?access_token=private-url-token",
            headers=headers | {"Cookie": "access_token=private-cookie-token"},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private" not in response.text


async def test_login_requires_configured_signing_key_but_health_stays_public() -> None:
    database = Database(SecretStr("postgresql+psycopg://unconnected@localhost/unused"))
    application = create_app()

    async def resource() -> Database:
        return database

    application.dependency_overrides[get_database_resource] = resource
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
            headers={"Origin": "http://127.0.0.1:8000", "X-AgentFlow-Client": "web"},
        ) as client:
            response = await client.post("/api/v1/auth/login", json=PAYLOAD)
            assert response.status_code == 503
            assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
            assert (await client.get("/api/v1/health")).status_code == 200
    finally:
        database.dispose()


@pytest.mark.parametrize("changes", [{"password": ""}, {"password": 123}, {"extra": "private"}])
async def test_login_invalid_input_never_echoes_private_values(changes: dict) -> None:
    database = Database(SecretStr("postgresql+psycopg://unconnected@localhost/unused"))
    application = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return database

    application.dependency_overrides[get_database_resource] = resource
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="http://test",
            headers={"Origin": "http://127.0.0.1:8000", "X-AgentFlow-Client": "web"},
        ) as client:
            response = await client.post("/api/v1/auth/login", json=PAYLOAD | changes)
        assert response.status_code == 422
        assert response.json()["error"]["details"] is None
        assert "private" not in response.text
    finally:
        database.dispose()


async def test_openapi_has_public_json_login_and_bearer_protected_me() -> None:
    schema = create_app().openapi()
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    me = schema["paths"]["/api/v1/auth/me"]["get"]
    assert not login.get("security")
    assert me["security"] == [{"AccessBearer": []}]
    assert schema["components"]["securitySchemes"]["AccessBearer"]["scheme"] == "bearer"
    assert set(login["requestBody"]["content"]) == {"application/json"}
    for operation in (login, me):
        for status in ("401", "503"):
            assert operation["responses"][status]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    assert schema["components"]["schemas"]["LoginRequest"]["properties"]["password"]["writeOnly"]
    assert set(schema["components"]["schemas"]["LoginResponse"]["properties"]) == {
        "access_token",
        "csrf_token",
        "token_type",
        "expires_in",
        "user",
    }
