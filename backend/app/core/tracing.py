"""Privacy-preserving OpenTelemetry instrumentation, inert without a tracer provider.

Only fixed span names are recorded. Inputs, outputs, identifiers, exception details,
headers and URLs are deliberately not passed to the tracing API.
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

from opentelemetry import context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

P = ParamSpec("P")
T = TypeVar("T")
_provider: TracerProvider | None = None


def configure_local_export(enabled: bool) -> None:
    """Enable bounded OTLP export to a local Phoenix collector, explicitly opt-in."""
    global _provider
    if not enabled or _provider is not None:
        return
    try:
        import requests
        from opentelemetry.exporter.otlp.proto.http import Compression
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

        class LocalSession(requests.Session):
            def prepare_request(self, request: requests.Request) -> requests.PreparedRequest:
                prepared = super().prepare_request(request)
                for name in list(prepared.headers):
                    if name.lower() not in {"content-length", "content-type", "user-agent"}:
                        del prepared.headers[name]
                prepared.headers["Content-Type"] = "application/x-protobuf"
                prepared.headers["User-Agent"] = "AgentFlow/0.1"
                return prepared

        session = LocalSession()
        session.trust_env = False
        session.max_redirects = 0
        exporter = OTLPSpanExporter(
            endpoint="http://127.0.0.1:6006/v1/traces",
            headers={"User-Agent": "AgentFlow/0.1"},
            compression=Compression.NoCompression,
            timeout=2,
            session=session,
        )
        provider = TracerProvider(
            resource=Resource({"service.name": "agentflow"}),
            sampler=ParentBased(ALWAYS_ON),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_queue_size=512,
                max_export_batch_size=64,
                schedule_delay_millis=1000,
                export_timeout_millis=2000,
            )
        )
        _provider = provider
    except Exception:
        # Observability must not prevent the application from starting.
        _provider = None


def shutdown_export() -> None:
    global _provider
    provider, _provider = _provider, None
    if provider is not None:
        try:
            provider.shutdown()
        except Exception:
            pass


def capture_traceparent() -> str | None:
    """Keep only W3C traceparent; never persist baggage or vendor trace state."""
    try:
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        value = carrier.get("traceparent")
        return value if value and len(value) == 55 else None
    except Exception:
        return None


@contextmanager
def parent_trace(traceparent: str | None) -> Iterator[None]:
    """Attach a validated remote context and always restore the prior context."""
    token = None
    try:
        if traceparent is not None and len(traceparent) == 55:
            extracted = TraceContextTextMapPropagator().extract({"traceparent": traceparent})
            if trace.get_current_span(extracted).get_span_context().is_valid:
                token = context.attach(extracted)
    except Exception:
        token = None
    try:
        yield
    finally:
        if token is not None:
            try:
                context.detach(token)
            except Exception:
                pass


@contextmanager
def span(name: str) -> Iterator[None]:
    """Record no exception data and never let instrumentation break application work."""
    manager = None
    active = None
    try:
        tracer = _provider.get_tracer("agentflow") if _provider else trace.get_tracer("agentflow")
        manager = tracer.start_as_current_span(
            name, record_exception=False, set_status_on_exception=False
        )
        active = manager.__enter__()
    except Exception:
        manager = None
    try:
        yield
    except BaseException:
        if active is not None:
            try:
                active.set_status(StatusCode.ERROR)
            except Exception:
                pass
        raise
    finally:
        if manager is not None:
            try:
                # Do not forward exception objects: exporters must never see their text.
                manager.__exit__(None, None, None)
            except Exception:
                pass


def traced(name: str) -> Callable[[Callable[P, T]], Callable[P, T]]:
    def decorate(function: Callable[P, T]) -> Callable[P, T]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with span(name):
                return function(*args, **kwargs)

        return wrapped

    return decorate


def traced_async(
    name: str,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    def decorate(function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(function)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            with span(name):
                return await function(*args, **kwargs)

        return wrapped

    return decorate
