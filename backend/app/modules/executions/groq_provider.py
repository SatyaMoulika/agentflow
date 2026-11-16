"""Single-attempt bounded Groq calls; callers own no open database transaction."""

import json
import re
from time import monotonic
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.tracing import traced
from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload
from app.modules.executions.provider_schemas import ProviderFailure, ProviderMetadata, TokenUsage

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RESPONSE_BYTES = 524288
CONNECT_TIMEOUT_SECONDS = 5.0
PROPOSAL_COMPLETION_TOKENS = 4096
ERROR_MESSAGES: dict[str, str] = {
    "PROVIDER_NOT_CONFIGURED": "Groq is not configured on the server.",
    "PROVIDER_AUTH_FAILED": "Groq rejected the configured credentials or permissions.",
    "PROVIDER_MODEL_UNAVAILABLE": "The configured Groq model is unavailable for this account.",
    "PROVIDER_RATE_LIMITED": "Groq quota is temporarily exhausted. Wait before trying again.",
    "PROVIDER_CONTEXT_LIMIT": "The request exceeds the configured model's input limit.",
    "PROVIDER_UNAVAILABLE": "Groq is temporarily unavailable.",
    "PROVIDER_INVALID_RESPONSE": "Groq returned an invalid response.",
    "PROVIDER_OUTPUT_LIMIT": "Groq reached the output limit before completing the response.",
    "DEADLINE_EXCEEDED": "The Groq request timed out. It was not retried.",
}


class GroqError(Exception):
    def __init__(
        self,
        status: int = 503,
        *,
        code: ProviderFailure | None = None,
        retry_after: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.code: ProviderFailure = code or (
            "PROVIDER_RATE_LIMITED" if status == 429 else "PROVIDER_UNAVAILABLE"
        )
        self.retry_after = retry_after
        self.metadata = metadata
        super().__init__(ERROR_MESSAGES[self.code])


def _retry_after(value: str | None) -> int | None:
    # Groq documents delta seconds. Never forward an arbitrary upstream header.
    if value is None or re.fullmatch(r"[0-9]{1,6}", value) is None:
        return None
    seconds = int(value)
    return seconds if 1 <= seconds <= 86400 else None


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def _failure(status: int, payload: Any) -> ProviderFailure:
    if status == 429:
        return "PROVIDER_RATE_LIMITED"
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    if (
        code in {"model_not_found", "model_decommissioned", "model_permission_blocked"}
        or status == 404
    ):
        return "PROVIDER_MODEL_UNAVAILABLE"
    if status in {401, 403}:
        return "PROVIDER_AUTH_FAILED"
    if status == 413 or code in {"context_length_exceeded", "context_window_exceeded"}:
        return "PROVIDER_CONTEXT_LIMIT"
    return "PROVIDER_UNAVAILABLE" if status >= 500 else "PROVIDER_INVALID_RESPONSE"


def complete(
    settings: Settings, prompt: str, *, json_mode: bool = False, workflow_proposal: bool = False
) -> dict[str, Any]:
    return _request(
        settings,
        [{"role": "user", "content": prompt}],
        json_mode=json_mode,
        workflow_proposal=workflow_proposal,
    )


def complete_tools(
    settings: Settings,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Internal agent boundary; only the code-owned tool catalog is passed by callers."""
    return _request(settings, messages, tools=tools, timeout_seconds=timeout_seconds)


@traced("agentflow.groq")
def _request(
    settings: Settings,
    messages: list[dict[str, Any]],
    *,
    json_mode: bool = False,
    tools: list[dict[str, Any]] | None = None,
    timeout_seconds: float | None = None,
    workflow_proposal: bool = False,
) -> dict[str, Any]:
    started = monotonic()
    metadata = ProviderMetadata(requested_model=settings.groq_model, duration_ms=0)

    def fail(code: ProviderFailure, status: int = 503, retry_after: int | None = None) -> GroqError:
        metadata.duration_ms = max(0, min(86400000, int((monotonic() - started) * 1000)))
        metadata.error_code, metadata.retry_after_seconds = code, retry_after
        return GroqError(
            status,
            code=code,
            retry_after=retry_after,
            metadata=metadata.model_dump(exclude_none=True),
        )

    key = settings.groq_api_key
    if key is None or not key.get_secret_value().strip():
        raise fail("PROVIDER_NOT_CONFIGURED")
    if (
        not messages
        or not any(
            isinstance(message.get("content"), str) and message["content"].strip()
            for message in messages
        )
        or len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) > 65536
    ):
        raise fail("PROVIDER_CONTEXT_LIMIT", 422)
    timeout = min(
        settings.groq_timeout_seconds,
        timeout_seconds if timeout_seconds is not None else settings.groq_timeout_seconds,
    )
    if timeout <= 0:
        raise fail("DEADLINE_EXCEEDED", 504)
    try:
        deadline = started + timeout
        with (
            httpx.Client(
                timeout=httpx.Timeout(timeout, connect=min(timeout, CONNECT_TIMEOUT_SECONDS)),
                trust_env=False,
                follow_redirects=False,
            ) as client,
            client.stream(
                "POST",
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {key.get_secret_value()}",
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                },
                json={
                    "model": settings.groq_model,
                    "messages": messages,
                    "max_completion_tokens": (
                        PROPOSAL_COMPLETION_TOKENS
                        if workflow_proposal
                        else 2048
                        if json_mode
                        else 1024
                    ),
                    **({"response_format": {"type": "json_object"}} if json_mode else {}),
                    **(
                        {"tools": tools, "tool_choice": "auto", "parallel_tool_calls": False}
                        if tools is not None
                        else {}
                    ),
                },
            ) as upstream,
        ):
            if upstream.headers.get("content-encoding", "identity").lower() != "identity":
                raise fail("PROVIDER_INVALID_RESPONSE", 502)
            body = bytearray()
            for chunk in upstream.iter_bytes():
                if monotonic() >= deadline:
                    raise fail("DEADLINE_EXCEEDED", 504)
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise fail("PROVIDER_INVALID_RESPONSE", 502)
                body.extend(chunk)
            try:
                payload: Any = json.loads(bytes(body), object_pairs_hook=_unique)
            except (ValueError, UnicodeError, RecursionError):
                payload = None
            if upstream.status_code != 200:
                code = _failure(upstream.status_code, payload)
                status = (
                    429
                    if code == "PROVIDER_RATE_LIMITED"
                    else 422
                    if code == "PROVIDER_CONTEXT_LIMIT"
                    else 502
                    if code == "PROVIDER_INVALID_RESPONSE"
                    else 503
                )
                raise fail(
                    code,
                    status,
                    _retry_after(upstream.headers.get("retry-after"))
                    if code == "PROVIDER_RATE_LIMITED"
                    else None,
                )
        if not isinstance(payload, dict):
            raise ValueError()
        model = payload["model"]
        if not isinstance(model, str) or not model or key.get_secret_value() in model:
            raise ValueError()
        metadata = ProviderMetadata(
            requested_model=settings.groq_model,
            model=model,
            duration_ms=max(0, min(86400000, int((monotonic() - started) * 1000))),
        )
        usage = payload.get("usage")
        if usage is not None:
            if not isinstance(usage, dict):
                raise ValueError()
            known = {name: usage[name] for name in TokenUsage.model_fields if name in usage}
            metadata.usage = TokenUsage.model_validate(known) if known else None
        choices = payload["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError()
        choice = choices[0]
        metadata.finish_reason = ProviderMetadata.model_validate(
            {
                **metadata.model_dump(),
                "finish_reason": choice.get("finish_reason"),
            }
        ).finish_reason
        if metadata.finish_reason == "length":
            raise fail("PROVIDER_OUTPUT_LIMIT", 502)
        message = choice["message"]
        content = message.get("content")
        calls = message.get("tool_calls")
        if message.get("refusal") or message.get("function_call"):
            raise ValueError()
        if tools is not None and metadata.finish_reason == "tool_calls":
            if not isinstance(calls, list) or len(calls) != 1:
                raise ValueError()
            call = calls[0]
            function = call["function"]
            call_id, name, arguments = call["id"], function["name"], function["arguments"]
            if (
                call.get("type") != "function"
                or not isinstance(call_id, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id) is None
                or not isinstance(name, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", name) is None
                or not isinstance(arguments, str)
                or len(arguments.encode("utf-8")) > 4096
                or any(key.get_secret_value() in item for item in (call_id, name, arguments))
                or (content is not None and not isinstance(content, str))
            ):
                raise ValueError()
            return {
                "model": model,
                "tool_call": {"id": call_id, "name": name, "arguments": arguments},
                "metadata": metadata.model_dump(exclude_none=True),
            }
        if (
            metadata.finish_reason in {"tool_calls", "content_filter"}
            or calls
            or not isinstance(content, str)
            or not content.strip()
            or len(content) > 100000
            or key.get_secret_value() in content
        ):
            raise ValueError()
        result = copy_payload({"model": model, "content": content})
        result["metadata"] = metadata.model_dump(exclude_none=True)
        return result
    except GroqError:
        raise
    except httpx.TimeoutException:
        raise fail("DEADLINE_EXCEEDED", 504) from None
    except httpx.HTTPError:
        raise fail("PROVIDER_UNAVAILABLE") from None
    except (
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        AttributeError,
        UnicodeError,
        RecursionError,
        ValidationError,
        InvalidExecutionPayloadError,
    ):
        raise fail("PROVIDER_INVALID_RESPONSE", 502) from None
