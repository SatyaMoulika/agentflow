# HTTP errors, request IDs, and JSON logging — Phase 1C

## Architecture and ownership

This increment belongs to the application boundary in `app/core/`. Correlation, safe HTTP failures, and operational logging apply across routes. They are not workflow business rules and need no service/repository pair. No database, migration, transaction, authentication feature, or model integration is introduced. No dependencies were added.

Three files implement the feature; the factory connects them. Domain exceptions and domain-specific codes will be introduced with actual business modules rather than an unused exception hierarchy now.

| File                                 | What its functions/classes do                                                                                                                                                                                                                                                                                                                                                                                                                |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/core/middleware.py`             | `RequestContextMiddleware(app, environment)` retains configuration only. Its async `__call__(scope, receive, send)` creates a server ID, copies state, sets context, forwards ASGI messages, handles unexpected failures before response start, emits a completion record, and restores context. The nested `send_with_request_id` adds the header and tracks the committed status.                                                          |
| `app/core/exceptions.py`             | Pydantic `ErrorDetail`/`ErrorResponse` validate the shared JSON shape. `error_response(request, status_code, headers=None) -> JSONResponse` selects a static public message and reads the ID from request state. `http_exception_handler` preserves status and allowed protocol headers. `validation_exception_handler` maps request validation to safe 422. `register_exception_handlers(application)` installs these mappings on that app. |
| `app/core/logging.py`                | `JsonFormatter.format(record) -> str` emits one JSON object using approved fields. `configure_logging(level) -> None` configures one named stdout handler for the `agentflow` logger; repeated calls do not add duplicates. `request_id_context` is a module-level ContextVar with a per-context value.                                                                                                                                      |
| `app/main.py`                        | The factory registers handlers and middleware, and publishes the shared OpenAPI default error schema. The middleware must surround any future user middleware that also needs this error boundary.                                                                                                                                                                                                                                           |
| `app/core/lifespan.py`               | Configures logging at startup before emitting the existing lifecycle records. App construction/import still does not configure logging.                                                                                                                                                                                                                                                                                                      |
| `app/core/config.py`, `.env.example` | Add `AGENTFLOW_LOG_LEVEL`: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`; default `INFO`. This controls application records, independently of FastAPI debug.                                                                                                                                                                                                                                                                            |
| `app/api/v1/health.py`               | Documents the success `X-Request-ID` header. The health payload is unchanged.                                                                                                                                                                                                                                                                                                                                                                |
| `tests/conftest.py`                  | Keeps the existing configuration isolation and adds log capture/restoration, so tests do not leave application handlers or levels behind.                                                                                                                                                                                                                                                                                                    |

The backend/root READMEs, API inventory, implementation plan, configuration/FastAPI notes, and development log record actual implemented scope. The private `.env`, frontend source, dependency manifests, and old `backend/agentflow/` drafts are untouched.

## Request flow

```text
HTTP request
  → middleware generates req_<32 hexadecimal characters>
  → shallow-copy request state; set ContextVar
  → FastAPI routing and request validation
      → success: normal response
      → HTTPException / RequestValidationError: registered safe handler
      → other Exception before headers: middleware creates safe 500
  → send wrapper adds X-Request-ID
  → completion JSON record contains the same ID
  → ContextVar token reset in finally
```

Lifespan and WebSocket scopes pass through without HTTP correlation. Startup/shutdown records have `request_id: null`. WebSocket correlation is not implemented.

## Why a ContextVar and a state copy?

`request.state.request_id` makes the ID accessible to handlers. A ContextVar makes it available to logging without passing a request through every function. Values are isolated between overlapping async contexts; a normal global string could be overwritten by another request. `set()` returns a token and `reset(token)` restores the previous value even after failure. See [Python 3.13 contextvars](https://docs.python.org/3.13/library/contextvars.html).

Each request gets a fresh UUID-based server ID. Incoming `X-Request-ID` values are ignored, and endpoint-supplied response IDs are overwritten. This avoids trusting unbounded/untrusted caller data as our correlation identifier. The ID is operational metadata, not authentication and not an OpenTelemetry trace ID.

The first concurrency test exposed a shared dictionary from the lifespan test transport: one request overwrote another's state ID while their ContextVars remained correct. Shallow-copying state before adding the ID fixes that issue and preserves existing lifespan values. It does not make other nested mutable resources safe for concurrent mutation; their modules must define ownership.

## Why pure ASGI middleware?

ASGI passes connection metadata in `scope`, input events through `receive`, and output events through `send`. The wrapper observes `http.response.start` to add a header and records status/duration with the monotonic `perf_counter`. It does not read or buffer the body, and forwards stream chunks as they arrive. Keeping request data inside `__call__` avoids sharing it on the middleware instance. See [Starlette middleware](https://starlette.dev/middleware/).

After response headers have been sent, HTTP cannot change the status or substitute a JSON error. Late streaming/background failures therefore produce an ERROR completion record with the original committed status and exception type, then propagate. Cancellation is not caught as an ordinary Exception and does not manufacture HTTP 500; status can be null if no response started.

The unexpected-error boundary is inside Starlette's outer server-error layer. It consumes failures before response start so there is one safe JSON response and one metadata completion record, without passing raw exception strings to Uvicorn. This keeps the same HTTP contract even with local `debug=true`; the production debug prohibition remains defense in depth. Exceptions outside this boundary, including startup or late stream errors, can still be reported by the server.

## Error contract and deliberate limits

Example for an unknown route, HTTP 404:

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "The requested resource does not exist.",
    "details": null
  },
  "request_id": "req_0123456789abcdef0123456789abcdef"
}
```

The header and body IDs match. Routing 405 retains `Allow`; 401 retains `WWW-Authenticate`; retryable errors may retain `Retry-After`. Other exception headers and raw detail strings are not copied. Common statuses have stable codes; unmapped client errors use `HTTP_ERROR`, unmapped server errors use `INTERNAL_ERROR`, retaining the original status.

Request validation returns 422. Response validation is a programming failure and returns 500. The client did not produce an invalid server response. Raw validation errors can include input, custom validator messages, context, and dynamic dictionary keys, so this increment deliberately returns `details: null`. Later modules can add explicitly public, typed field details with their contracts. No production validation/demo endpoint was added; test routes exist only on isolated test apps. See [FastAPI custom error handlers](https://fastapi.tiangolo.com/tutorial/handling-errors/).

OpenAPI describes `ErrorResponse` under the default error response for existing/future routes; the success and error response headers are documented. Returning an arbitrary error-shaped JSONResponse directly bypasses these exception handlers; future routes should use the agreed error boundary rather than inventing another envelope.

## Logging and privacy

Application records contain timestamp, level, logger, message, request_id, and selected metadata: environment, method, route template, status_code, duration_ms, error_type. Unknown paths use `<unmatched>`; matched dynamic values are replaced by the registered route template. Completion messages are constant. Bodies, query strings, headers, cookies, tokens, raw exception strings/tracebacks, and arbitrary extra fields are not serialized by the provided completion/error paths.

This formatter is an allowlist, not a universal secret scanner. Future callers must not put private data directly into the log message. Only exception type is retained for unexpected failures; full stack diagnostics/redacted tracing remain later work. The logging level/handlers are process-global Python logging state, unlike per-app settings: one app per server process is the intended deployment, and the most recent startup configures the shared AgentFlow logger. Other loggers/root handlers are not modified. See [Python 3.13 logging](https://docs.python.org/3.13/library/logging.html).

Run Uvicorn with `--no-access-log`: AgentFlow's JSON completion records replace its raw URL access records. Uvicorn startup/system messages retain their own format, and infrastructure logs from late errors need separate privacy configuration. Suppressing application INFO through a higher `AGENTFLOW_LOG_LEVEL` is intentional; it also suppresses ordinary completion/lifecycle records. Increasing log verbosity does not enable debug HTTP tracebacks through this boundary.

## Tests and observed results

The suite has **45 passing cases**, adding 20 to Phase 1B:

| File                                | What a failure would reveal                                                                                                                                                                             |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/api/test_errors.py`          | Broken 404/405 envelopes or ID matching; lost protocol headers; leaked HTTP/validation detail; unsanitized 500/debug output; response validation misclassified as client error; incorrect OpenAPI shape |
| `tests/api/test_request_context.py` | Reflected caller IDs, duplicate IDs, shared state under overlap, incorrect context/log correlation, or leaked dynamic paths/query/header values                                                         |
| `tests/unit/test_logging.py`        | Arbitrary extras/exception strings in JSON; duplicate handlers; wrong level filtering; unintended root logger changes                                                                                   |
| `tests/unit/test_middleware.py`     | Buffered stream chunks, a second response after headers, swallowed late failure/cancellation, or context left behind                                                                                    |
| `tests/unit/test_config.py`         | New log-level parsing/default or invalid-value handling broken; previous configuration checks remain                                                                                                    |

Existing health, app settings, and lifecycle tests also pass. Ruff lint and format checks pass. A real Uvicorn process verified health, 404, 405/Allow, 422, 500, OpenAPI, JSON completion correlation, and startup/shutdown. A private sentinel was absent from responses/log output. Temporary smoke routes/files and the owned server were removed afterward. This is foundation coverage, not frontend/database/worker/provider/telemetry verification; Pyright was added and verified in [Phase 1D](backend-checks.md).

## Review questions

Discuss one at a time:

1. Why is a global string unsafe for request IDs when two requests overlap?
2. Why does the middleware copy request state as well as use a ContextVar?
3. Why should invalid server response data produce 500 while invalid request data produces 422?
4. Why can a failing stream retain HTTP 200 in its completion record?
5. What can still leak if a developer interpolates a credential into a log message?

## Independent exercise and next step

Add a test that `/docs` includes a generated request ID when enabled. With documentation disabled, check that its 404 header/body IDs match. Keep the health payload unchanged and do not edit the real `.env`. Try the test before requesting a solution.

Phase 1D is now complete: see [backend checks](backend-checks.md). Next is Phase 2A, PostgreSQL and SQLAlchemy session lifecycle, after the foundation review.
