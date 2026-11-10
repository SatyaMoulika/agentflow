"""Origin, header and cookie boundaries reject requests before storage or hashing."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = pytest.mark.anyio
ORIGIN = "http://127.0.0.1:8000"
GOOD = {"Origin": ORIGIN, "X-AgentFlow-Client": "web"}


@pytest.mark.parametrize("endpoint", ["login", "refresh", "logout"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null", "X-AgentFlow-Client": "web"},
        {"Origin": "https://evil.test", "X-AgentFlow-Client": "web"},
        {"Origin": ORIGIN},
    ],
)
async def test_auth_cookie_operations_require_exact_origin_and_custom_marker(
    endpoint: str, headers: dict
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post(f"/api/v1/auth/{endpoint}", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "set-cookie" not in response.headers


async def test_refresh_requires_cookie_not_body_query_or_bearer_and_clears_stale_pair() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/refresh?refresh_token=private-query",
            json={"refresh_token": "private-body"},
            headers=GOOD | {"Authorization": "Bearer private-bearer"},
        )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "private" not in response.text
    assert len(response.headers.get_list("set-cookie")) == 2
    assert all("Max-Age=0" in value for value in response.headers.get_list("set-cookie"))


@pytest.mark.parametrize("proof", [None, "short", "b" * 43])
async def test_missing_or_mismatched_csrf_never_reaches_database_or_clears_cookies(
    proof: str | None,
) -> None:
    headers = GOOD | {
        "Cookie": f"__Host-agentflow_refresh={'r' * 43}; __Host-agentflow_csrf={'a' * 43}"
    }
    if proof is not None:
        headers["X-AgentFlow-CSRF"] = proof
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post("/api/v1/auth/refresh", headers=headers)
    assert response.status_code == 403
    assert "set-cookie" not in response.headers


async def test_duplicate_origin_is_rejected() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            headers=[("Origin", ORIGIN), ("Origin", ORIGIN), ("X-AgentFlow-Client", "web")],
        )
    assert response.status_code == 403


async def test_refresh_openapi_has_no_body_credentials_and_safe_error_schemas() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/auth/refresh"]["post"]
    assert "requestBody" not in operation and not operation.get("security")
    assert {p["name"] for p in operation["parameters"]} == {
        "X-AgentFlow-Client",
        "X-AgentFlow-CSRF",
    }
    for code in ("401", "403", "503"):
        assert operation["responses"][code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
