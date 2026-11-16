"""Tracing boundaries must be private and must never change execution outcomes."""

from contextvars import ContextVar
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.trace import StatusCode
from starlette.concurrency import run_in_threadpool

from app.core import tracing
from app.core.middleware import RequestContextMiddleware
from app.modules.executions.operations import calculate


class Recorder:
    def __init__(self) -> None:
        self.current: ContextVar[str | None] = ContextVar("test_span", default=None)
        self.items: list[dict[str, Any]] = []

    def start_as_current_span(self, name: str, **kwargs: Any) -> Any:
        recorder = self

        class Manager:
            def __enter__(self) -> Any:
                self.item = {"name": name, "parent": recorder.current.get(), "options": kwargs}
                recorder.items.append(self.item)
                self.token = recorder.current.set(name)
                return self

            def set_status(self, status: StatusCode) -> None:
                self.item["status"] = status

            def __exit__(self, *args: Any) -> None:
                self.item["exit"] = args
                recorder.current.reset(self.token)

        return Manager()


@pytest.mark.anyio
async def test_request_span_reaches_threadpool_without_private_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(tracing.trace, "get_tracer", lambda _: recorder)
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware, environment="testing")

    @app.get("/calculate/{private_value}")
    async def endpoint(private_value: str) -> dict[str, int | float]:
        assert private_value
        return await run_in_threadpool(calculate, "add", [2, 3])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/calculate/private-sentinel?token=private-query")

    assert response.json() == {"result": 5}
    assert [item["name"] for item in recorder.items] == [
        "agentflow.http",
        "agentflow.calculator",
    ]
    assert recorder.items[1]["parent"] == "agentflow.http"
    assert all(
        item["options"] == {"record_exception": False, "set_status_on_exception": False}
        and item["exit"] == (None, None, None)
        for item in recorder.items
    )
    assert "private" not in repr(recorder.items)
    assert recorder.current.get() is None


def test_error_records_only_status_and_preserves_original_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(tracing.trace, "get_tracer", lambda _: recorder)
    with pytest.raises(ValueError, match="private-error"):
        with tracing.span("agentflow.test"):
            raise ValueError("private-error")
    assert recorder.items[0]["status"] == StatusCode.ERROR
    assert recorder.items[0]["exit"] == (None, None, None)
    assert "private-error" not in repr(recorder.items)


def test_broken_instrumentation_does_not_break_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(_: str) -> Any:
        raise RuntimeError("private-export-error")

    monkeypatch.setattr(tracing.trace, "get_tracer", broken)
    assert calculate("add", [2, 3]) == {"result": 5}
    with pytest.raises(ValueError, match="original"):
        with tracing.span("agentflow.test"):
            raise ValueError("original")


def test_broken_span_cleanup_does_not_change_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def start_as_current_span(self, *args: Any, **kwargs: Any) -> Any:
            return self

        def __enter__(self) -> Any:
            return self

        def __exit__(self, *args: Any) -> None:
            raise RuntimeError("private-export-error")

    monkeypatch.setattr(tracing.trace, "get_tracer", lambda _: Broken())
    assert calculate("multiply", [2, 3]) == {"result": 6}
