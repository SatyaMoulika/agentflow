"""HTTP correlation, completion logging, and the unexpected-error boundary."""

import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import error_response
from app.core.logging import request_id_context

logger = logging.getLogger("agentflow.http")


class RequestContextMiddleware:
    """Keep per-request state local and stream messages without buffering the body."""

    def __init__(self, app: ASGIApp, environment: str) -> None:
        self.app = app
        self.environment = environment

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Never trust/reflect a caller's correlation header as our server request ID.
        request_id = f"req_{uuid4().hex}"
        # ASGI lifespan state is shared by some transports; preserve its values but
        # never write request-specific data into another request's dictionary.
        scope["state"] = {**scope.get("state", {}), "request_id": request_id}
        token = request_id_context.set(request_id)
        started_at = perf_counter()
        status_code: int | None = None
        error_type: str | None = None
        response_started = False

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
                status_code = message["status"]
                response_started = True
            await send(message)

        try:
            try:
                await self.app(scope, receive, send_with_request_id)
            except Exception as exc:
                # This is the HTTP boundary, not a catch-and-ignore business operation.
                error_type = type(exc).__name__
                if response_started:
                    # Streaming/background failures cannot replace a committed response.
                    raise
                response = error_response(Request(scope), 500)
                await response(scope, receive, send_with_request_id)
        finally:
            try:
                logger.log(
                    logging.ERROR if error_type or (status_code or 0) >= 500 else logging.INFO,
                    "HTTP request completed",
                    extra={
                        "request_id": request_id,
                        "environment": self.environment,
                        "method": scope["method"],
                        "route": getattr(scope.get("route"), "path", "<unmatched>"),
                        "status_code": status_code,
                        "duration_ms": round((perf_counter() - started_at) * 1000, 3),
                        "error_type": error_type,
                    },
                )
            finally:
                request_id_context.reset(token)
