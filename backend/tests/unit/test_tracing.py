"""Tracing boundaries must be private and must never change execution outcomes."""

from contextvars import ContextVar
from typing import Any

import pytest
import requests
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry import context, trace
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    StatusCode,
    TraceFlags,
    set_span_in_context,
)
from starlette.concurrency import run_in_threadpool

from app.core import tracing
from app.core.middleware import RequestContextMiddleware
from app.modules.executions.dispatch import schedule_recovery
from app.modules.executions.operations import calculate
from app.workers.workflow_tasks import consume_workflow


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


def test_worker_and_recovery_spans_do_not_record_delivery_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = Recorder()
    monkeypatch.setattr(tracing.trace, "get_tracer", lambda _: recorder)
    # Invalid values are rejected before storage is touched.
    consume_workflow(None, "private-invalid-id")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        schedule_recovery(None, limit=0)  # type: ignore[arg-type]
    assert [item["name"] for item in recorder.items] == ["agentflow.recovery_discovery"]
    assert recorder.items[0]["status"] == StatusCode.ERROR
    assert "private-invalid-id" not in repr(recorder.items)


def test_traceparent_round_trip_and_context_restoration() -> None:
    original = SpanContext(trace_id=123, span_id=456, is_remote=False, trace_flags=TraceFlags(1))
    token = context.attach(set_span_in_context(NonRecordingSpan(original)))
    try:
        parent = tracing.capture_traceparent()
    finally:
        context.detach(token)
    assert parent is not None
    with tracing.parent_trace(parent):
        restored = trace.get_current_span().get_span_context()
        assert restored.trace_id == 123 and restored.span_id == 456 and restored.is_remote
    assert not trace.get_current_span().get_span_context().is_valid
    with tracing.parent_trace("invalid"):
        assert not trace.get_current_span().get_span_context().is_valid


def test_sdk_spans_correlate_and_exclude_private_values(monkeypatch: pytest.MonkeyPatch) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "_provider", provider)
    try:
        with tracing.span("agentflow.http"):
            parent = tracing.capture_traceparent()
        with tracing.parent_trace(parent), tracing.span("agentflow.worker_delivery"):
            with tracing.span("agentflow.calculator"):
                assert calculate("add", [1, 2]) == {"result": 3}
        spans = exporter.get_finished_spans()
        assert spans[-1].context is not None
        assert {item.context.trace_id for item in spans if item.context} == {
            spans[-1].context.trace_id
        }
        assert all(not item.attributes and not item.events for item in spans)
    finally:
        provider.shutdown()


def test_local_export_is_opt_in_and_shutdown_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tracing, "_provider", None)
    tracing.configure_local_export(False)
    assert tracing._provider is None
    tracing.configure_local_export(True)
    assert tracing._provider is not None
    tracing.shutdown_export()
    assert tracing._provider is None


def test_otlp_export_contains_only_bounded_trace_data(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[bytes] = []

    def request(self: Any, method: str, url: str, **kwargs: Any) -> requests.Response:
        assert method == "POST" and url == "http://127.0.0.1:6006/v1/traces"
        assert not self.trust_env and self.max_redirects == 0
        prepared = self.prepare_request(requests.Request(method, url, headers=kwargs["headers"]))
        assert dict(prepared.headers) == {
            "Content-Type": "application/x-protobuf",
            "User-Agent": "AgentFlow/0.1",
            "Content-Length": "0",
        }
        captured.append(kwargs["data"])
        response = requests.Response()
        response.status_code = 200
        response._content = b""
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "Authorization=private-sentinel")
    monkeypatch.setattr(tracing, "_provider", None)
    tracing.configure_local_export(True)
    try:
        assert tracing._provider is not None
        with tracing.span("agentflow.http"):
            with tracing.span("agentflow.calculator"):
                pass
        assert tracing._provider.force_flush(timeout_millis=3000)
        request_data = ExportTraceServiceRequest.FromString(captured[0])
        spans = [
            span
            for resource in request_data.resource_spans
            for scope in resource.scope_spans
            for span in scope.spans
        ]
        assert {item.name for item in spans} == {"agentflow.http", "agentflow.calculator"}
        assert all(not item.attributes and not item.events for item in spans)
        assert spans[0].trace_id == spans[1].trace_id
    finally:
        tracing.shutdown_export()
