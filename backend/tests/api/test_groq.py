"""The Groq route sends only explicit prompts and never exposes provider errors."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.main import create_app
from app.modules.auth.schemas import UserResponse

pytestmark = pytest.mark.anyio


def signed_in_app():
    application = create_app()

    async def user() -> UserResponse:
        return UserResponse(
            id=uuid4(),
            email="test@example.com",
            display_name="Test",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    application.dependency_overrides[get_current_user] = user
    return application


async def test_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="https://test") as c:
        response = await c.post("/api/v1/ai/completions", json={"prompt": "Hello"})
    assert response.status_code == 401


async def test_groq_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-private-key")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "model": "reported-model",
                "choices": [{"message": {"content": "Real answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    client_class = httpx.Client
    monkeypatch.setattr(
        "app.modules.executions.groq_provider.httpx.Client",
        lambda **kwargs: client_class(transport=httpx.MockTransport(handler), **kwargs),
    )
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as c:
        response = await c.post("/api/v1/ai/completions", json={"prompt": "Say hello"})
    assert response.status_code == 200
    assert (
        response.json()["model"] == "reported-model" and response.json()["content"] == "Real answer"
    )
    assert response.json()["metadata"]["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
    }
    assert response.json()["metadata"]["requested_model"] == "openai/gpt-oss-120b"
    assert response.headers["cache-control"] == "no-store"
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.groq.com/openai/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer test-private-key"
    assert b"Say hello" in requests[0].content
    assert "test-private-key" not in response.text


@pytest.mark.parametrize("status,expected", [(429, 429), (401, 503), (500, 503)])
async def test_provider_errors_are_static(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: int
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-private-key")
    client_class = httpx.Client
    monkeypatch.setattr(
        "app.modules.executions.groq_provider.httpx.Client",
        lambda **kwargs: client_class(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, text="secret")),
            **kwargs,
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as c:
        response = await c.post("/api/v1/ai/completions", json={"prompt": "private prompt"})
    assert response.status_code == expected
    assert "secret" not in response.text and "private prompt" not in response.text


async def test_missing_key_and_invalid_prompts() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as c:
        missing = await c.post("/api/v1/ai/completions", json={"prompt": "Hello"})
        invalid = await c.post("/api/v1/ai/completions", json={"prompt": "   "})
    assert missing.status_code == 503
    assert invalid.status_code == 422


async def test_provider_quota_error_has_distinct_code_and_safe_retry_header(monkeypatch) -> None:
    from app.modules.executions.groq_provider import GroqError

    def limited(*args, **kwargs):
        raise GroqError(429, retry_after=2)

    monkeypatch.setattr("app.api.v1.groq.complete", limited)
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as client:
        response = await client.post("/api/v1/ai/completions", json={"prompt": "Synthetic"})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "PROVIDER_RATE_LIMITED"
    assert response.headers["retry-after"] == "2"
    assert response.headers["cache-control"] == "no-store"
