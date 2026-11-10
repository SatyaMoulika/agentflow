"""Streaming messages pass through; committed responses cannot become JSON errors."""

import asyncio
import logging

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.core.logging import request_id_context
from app.core.middleware import RequestContextMiddleware

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("fail_after_start", [False, True])
async def test_streaming_is_not_buffered_and_late_failures_are_reraised(
    fail_after_start: bool, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[Message] = []

    async def receive() -> Message:
        raise AssertionError("Middleware must not consume the request body")

    async def send(message: Message) -> None:
        sent.append(message)

    async def streaming_app(scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        assert len(sent) == 2  # Forwarded before the stream completes.
        if fail_after_start:
            raise RuntimeError("private-stream-failure")
        await send({"type": "http.response.body", "body": b"second", "more_body": False})

    middleware = RequestContextMiddleware(streaming_app, environment="testing")
    scope: Scope = {"type": "http", "method": "GET", "path": "/test/stream", "headers": []}
    if fail_after_start:
        with pytest.raises(RuntimeError, match="private-stream-failure"):
            await middleware(scope, receive, send)
        assert len(sent) == 2  # No second response start or fabricated 500 body.
    else:
        await middleware(scope, receive, send)
        assert sent[-1]["body"] == b"second"
    assert sent[0]["headers"] == [(b"x-request-id", scope["state"]["request_id"].encode())]
    record = next(record for record in caplog.records if record.name == "agentflow.http")
    assert record.__dict__["status_code"] == 200  # The committed status stays truthful.
    assert record.levelno == (logging.ERROR if fail_after_start else logging.INFO)
    assert "private-stream-failure" not in caplog.text
    assert request_id_context.get() is None


async def test_cancellation_is_not_converted_to_an_internal_error() -> None:
    sent: list[Message] = []

    async def cancelled_app(scope: Scope, receive: Receive, send: Send) -> None:
        raise asyncio.CancelledError()

    async def receive() -> Message:
        raise AssertionError("No body expected")

    async def send(message: Message) -> None:
        sent.append(message)

    with pytest.raises(asyncio.CancelledError):
        await RequestContextMiddleware(cancelled_app, environment="testing")(
            {"type": "http", "method": "GET", "path": "/test/cancel", "headers": []},
            receive,
            send,
        )
    assert sent == []
    assert request_id_context.get() is None
