"""Bounded, single-attempt provider I/O and metadata privacy; no external requests."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.modules.executions import groq_provider as provider

KEY = "private-test-provider-key"


def settings() -> Settings:
    return Settings(groq_api_key=SecretStr(KEY))


def payload(**changes: Any) -> dict:
    return {
        "model": "reported-model",
        "choices": [{"message": {"content": "Synthetic answer"}, "finish_reason": "stop"}],
        "usage": {
            "prompt_tokens": 4,
            "completion_tokens": 3,
            "total_tokens": 7,
            "prompt_time": 0.1,
            "completion_time": 0.2,
        },
    } | changes


def transport(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    calls = []
    original = httpx.Client

    def handle(request):
        calls.append(request)
        return handler(request)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(provider.httpx, "Client", client)
    return calls


def test_reports_actual_model_and_only_reported_usage_without_reasoning_or_extra_fields(
    monkeypatch,
) -> None:
    calls = transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=payload(
                system_fingerprint="private-fingerprint", x_groq={"id": "private-request-id"}
            ),
        ),
    )
    result = provider.complete(settings(), "synthetic input", json_mode=True)
    assert result["model"] == "reported-model" and result["content"] == "Synthetic answer"
    metadata = result["metadata"]
    assert metadata["requested_model"] == "openai/gpt-oss-120b"
    assert metadata["model"] == "reported-model" and metadata["duration_ms"] >= 0
    assert metadata["usage"] == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}
    assert len(calls) == 1
    request = json.loads(calls[0].content)
    assert request["max_completion_tokens"] == 2048
    assert request["response_format"] == {"type": "json_object"}
    assert "tools" not in request and "service_tier" not in request
    for value in (KEY, "private-fingerprint", "private-request-id", "synthetic input"):
        assert value not in json.dumps(metadata)


def test_missing_usage_stays_unknown(monkeypatch) -> None:
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload(usage=None)))
    result = provider.complete(settings(), "synthetic input")
    assert "usage" not in result["metadata"] and "cost" not in result["metadata"]


def test_workflow_proposal_gets_a_larger_bounded_budget_without_retries(monkeypatch) -> None:
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=payload()))
    provider.complete(settings(), "synthetic proposal", json_mode=True, workflow_proposal=True)
    assert len(calls) == 1
    request = json.loads(calls[0].content)
    assert request["max_completion_tokens"] == 4096
    assert request["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("budget", [1, 45])
def test_connection_setup_cannot_consume_the_entire_response_budget(monkeypatch, budget) -> None:
    original = httpx.Client
    calls = []
    clock = [0.0]
    monkeypatch.setattr(provider, "monotonic", lambda: clock[0])

    def client(**kwargs):
        timeout = httpx.Timeout(kwargs["timeout"])
        assert timeout.read == budget and timeout.write == budget and timeout.pool == budget
        connect_timeout = timeout.connect
        assert connect_timeout is not None and 0 < connect_timeout <= budget

        def handle(request):
            calls.append(request)
            if budget == 45:
                # Simulate an unreachable first address spending its connect timeout,
                # followed by a reachable address returning a response immediately.
                # The former 45-second connect timeout exhausted the total deadline here.
                clock[0] += connect_timeout + 0.25
            return httpx.Response(200, json=payload())

        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(provider.httpx, "Client", client)
    configured = settings().model_copy(update={"groq_timeout_seconds": budget})
    assert provider.complete(configured, "synthetic input")["content"] == "Synthetic answer"
    assert len(calls) == 1


def test_agent_remaining_budget_also_caps_connection_setup(monkeypatch) -> None:
    original = httpx.Client

    def client(**kwargs):
        assert kwargs["timeout"].connect == kwargs["timeout"].read == 0.25
        return original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload())),
            **kwargs,
        )

    monkeypatch.setattr(provider.httpx, "Client", client)
    result = provider.complete_tools(
        settings(), [{"role": "user", "content": "synthetic input"}], [], timeout_seconds=0.25
    )
    assert result["content"] == "Synthetic answer"


@pytest.mark.parametrize(
    ("status", "body", "code", "expected"),
    [
        (401, {}, "PROVIDER_AUTH_FAILED", 503),
        (403, {}, "PROVIDER_AUTH_FAILED", 503),
        (404, {}, "PROVIDER_MODEL_UNAVAILABLE", 503),
        (400, {"error": {"code": "model_decommissioned"}}, "PROVIDER_MODEL_UNAVAILABLE", 503),
        (400, {"error": {"code": "context_length_exceeded"}}, "PROVIDER_CONTEXT_LIMIT", 422),
        (413, {}, "PROVIDER_CONTEXT_LIMIT", 422),
        (429, {}, "PROVIDER_RATE_LIMITED", 429),
        (500, {}, "PROVIDER_UNAVAILABLE", 503),
        (302, {}, "PROVIDER_INVALID_RESPONSE", 502),
    ],
)
def test_errors_are_static_and_never_retry(monkeypatch, status, body, code, expected) -> None:
    calls = transport(
        monkeypatch,
        lambda request: httpx.Response(
            status, json=body | {"private": "private-upstream-body"}, headers={"Retry-After": "2"}
        ),
    )
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "private-prompt")
    assert error.value.code == code and error.value.status == expected and len(calls) == 1
    assert error.value.retry_after == (2 if status == 429 else None)
    exposed = str(error.value) + json.dumps(error.value.metadata)
    for value in (KEY, "private-prompt", "private-upstream-body"):
        assert value not in exposed


@pytest.mark.parametrize("value", ["secret-header", "0", "9999999", "-1", "2.5", "86401"])
def test_arbitrary_or_unbounded_retry_after_is_not_forwarded(monkeypatch, value) -> None:
    transport(monkeypatch, lambda request: httpx.Response(429, headers={"Retry-After": value}))
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "synthetic")
    assert error.value.code == "PROVIDER_RATE_LIMITED" and error.value.retry_after is None


@pytest.mark.parametrize(
    "body",
    [
        {"model": None},
        {"model": ""},
        {"model": "private model with spaces"},
        {"model": KEY},
        {"choices": [{"message": {"content": "\x00" * 50000}}]},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {"content": KEY}}]},
        {"choices": [{"message": {"content": "Text", "tool_calls": [{"name": "private_tool"}]}}]},
        {"choices": [{"message": {"content": "Text"}, "finish_reason": "unknown"}]},
        {"usage": {"total_tokens": -1}},
        {"usage": {"prompt_tokens": True}},
        {"usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 2}},
    ],
)
def test_malformed_model_content_and_usage_fail_closed(monkeypatch, body) -> None:
    transport(monkeypatch, lambda request: httpx.Response(200, json=payload(**body)))
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "synthetic")
    assert error.value.code == "PROVIDER_INVALID_RESPONSE"
    assert KEY not in json.dumps(error.value.metadata)


@pytest.mark.parametrize("workflow_proposal", [False, True])
def test_truncated_response_preserves_reported_usage_but_is_not_accepted(
    monkeypatch, workflow_proposal
) -> None:
    calls = transport(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json=payload(
                choices=[{"message": {"content": "Partial result"}, "finish_reason": "length"}]
            ),
        ),
    )
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "synthetic", workflow_proposal=workflow_proposal)
    assert error.value.code == "PROVIDER_OUTPUT_LIMIT"
    assert len(calls) == 1
    assert error.value.metadata is not None
    assert error.value.metadata["usage"]["total_tokens"] == 7


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, content=b'{"model":"a","model":"b"}'),
        httpx.Response(200, content=b"x" * (provider.MAX_RESPONSE_BYTES + 1)),
        httpx.Response(200, content=b"bad-compression", headers={"Content-Encoding": "br"}),
    ],
)
def test_response_bytes_are_bounded_and_ambiguous_json_is_rejected(monkeypatch, response) -> None:
    transport(monkeypatch, lambda request: response)
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "synthetic")
    assert error.value.code == "PROVIDER_INVALID_RESPONSE"


def test_timeout_does_not_replay_the_request(monkeypatch) -> None:
    def timeout(request):
        raise httpx.ReadTimeout("private-transport-detail")

    calls = transport(monkeypatch, timeout)
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "synthetic")
    assert error.value.code == "DEADLINE_EXCEEDED" and error.value.status == 504
    assert len(calls) == 1 and "private-transport-detail" not in str(error.value)


def test_unconfigured_provider_and_oversized_prompt_do_not_open_network(monkeypatch) -> None:
    def forbidden(**kwargs):
        pytest.fail("Invalid configuration/input must not open a network client")

    monkeypatch.setattr(provider.httpx, "Client", forbidden)
    with pytest.raises(provider.GroqError) as error:
        provider.complete(Settings(), "synthetic")
    assert error.value.code == "PROVIDER_NOT_CONFIGURED"
    with pytest.raises(provider.GroqError) as error:
        provider.complete(settings(), "x" * 65537)
    assert error.value.code == "PROVIDER_CONTEXT_LIMIT"
