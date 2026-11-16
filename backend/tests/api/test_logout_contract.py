"""Idempotent local logout and cookie/CSRF boundaries without database I/O."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = pytest.mark.anyio
HEADERS = {"Origin": "http://127.0.0.1:8000", "X-AgentFlow-Client": "web"}


@pytest.mark.parametrize("cookie", [None, "__Host-agentflow_refresh=malformed-private-value"])
async def test_absent_or_malformed_cookie_clears_pair_without_database_or_jwt_key(
    cookie: str | None,
) -> None:
    headers = HEADERS if cookie is None else HEADERS | {"Cookie": cookie}
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        for _ in range(2):
            response = await client.post("/api/v1/auth/logout", headers=headers)
            assert response.status_code == 204 and response.content == b""
            assert "content-type" not in response.headers
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["pragma"] == "no-cache"
            cookies = response.headers.get_list("set-cookie")
            assert len(cookies) == 2 and all("Max-Age=0" in h for h in cookies)
            assert all("Secure" in h and "Path=/" in h and "SameSite=strict" in h for h in cookies)
            assert "HttpOnly" in cookies[0] and "HttpOnly" not in cookies[1]
            assert "x-request-id" in response.headers


@pytest.mark.parametrize("csrf", [None, "short", "b" * 43])
async def test_present_cookie_requires_matching_csrf_and_preserves_cookies_on_403(
    csrf: str | None,
) -> None:
    headers = HEADERS | {
        "Cookie": f"__Host-agentflow_refresh={'r' * 43}; __Host-agentflow_csrf={'a' * 43}"
    }
    if csrf is not None:
        headers["X-AgentFlow-CSRF"] = csrf
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 403 and "set-cookie" not in response.headers
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert response.json()["request_id"] == response.headers["x-request-id"]


async def test_present_credential_needs_database_and_cannot_fake_logout_success() -> None:
    raw, csrf = "r" * 43, "c" * 43
    headers = HEADERS | {
        "Cookie": f"__Host-agentflow_refresh={raw}; __Host-agentflow_csrf={csrf}",
        "X-AgentFlow-CSRF": csrf,
    }
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post("/api/v1/auth/logout", headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "set-cookie" not in response.headers
    assert raw not in response.text and csrf not in response.text


async def test_logout_openapi_declares_no_body_bearer_or_204_json() -> None:
    schema = create_app().openapi()
    assert len(schema["paths"]) == 28
    assert not any("_test" in path for path in schema["paths"])
    operation = schema["paths"]["/api/v1/auth/logout"]["post"]
    assert "requestBody" not in operation and not operation.get("security")
    assert "content" not in operation["responses"]["204"]
    assert {p["name"] for p in operation["parameters"]} == {
        "X-AgentFlow-Client",
        "X-AgentFlow-CSRF",
    }
    for code in ("403", "503"):
        assert operation["responses"][code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
