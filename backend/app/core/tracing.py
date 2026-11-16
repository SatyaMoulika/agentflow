"""Privacy-preserving OpenTelemetry instrumentation, inert without a tracer provider.

Only fixed span names are recorded. Inputs, outputs, identifiers, exception details,
headers and URLs are deliberately not passed to the tracing API.
"""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from typing import ParamSpec, TypeVar

from opentelemetry import trace
from opentelemetry.trace import StatusCode

P = ParamSpec("P")
T = TypeVar("T")


@contextmanager
def span(name: str) -> Iterator[None]:
    """Record no exception data and never let instrumentation break application work."""
    manager = None
    active = None
    try:
        manager = trace.get_tracer("agentflow").start_as_current_span(
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
