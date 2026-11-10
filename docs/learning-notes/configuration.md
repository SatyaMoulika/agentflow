# Configuration and lifespan — Phase 1B

Phase 1C adds [request IDs, JSON logging, and safe HTTP errors](http-observability.md), including the consumed `AGENTFLOW_LOG_LEVEL` setting. [Phase 2A](sqlalchemy.md) now adds the optional secret database URL, startup connection check, and pool cleanup; the concepts below record the foundation increment.

## Ownership and validation

Settings control app construction before HTTP is served. `app/core/config.py` owns that boundary; `app/main.py` composes it with FastAPI. Domain modules do not need to know how environment variables or dotenv files are read. There are no database/migration/transaction changes.

`Settings` extends `pydantic_settings.BaseSettings`. `SettingsConfigDict` defines the prefix, absolute dotenv path, immutability, unknown-key handling, and error display. `Field` bounds the app name; `Literal` restricts environments; typed booleans parse environment strings. `model_validator(mode="after")` checks production/debug after individual fields validate.

Only consumed settings exist. Ignoring unrelated dotenv keys permits a shared file, with the trade-off that misspelled names are ignored too. Supported names are in the backend README.

## Precedence and lifetime

Explicit constructor arguments override process environment, which overrides `backend/.env`, then field defaults. Deployment configuration can therefore override a developer's file. `_env_file=None` disables dotenv, not process environment. See [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

The dotenv path is derived from the source file's location, so changing shell directories does not select another file. Defaults need no `.env` or credentials.

Each factory call loads independent settings unless a validated object is injected. `app.state.settings` retains it without a global cache. Later environment changes do not change an existing app. `frozen=True` prevents assigning new field values after validation; reconstruct the app to apply changes.

`create_app(settings=...)` is constructor injection: the caller supplies the dependency. Per-request FastAPI `Depends` is unnecessary for settings already consumed during construction.

## Failure handling

`Settings()` raises `ValidationError` for invalid recognized values. `load_settings()` extracts locations/messages without input/context values and raises `ConfigurationError` using `from None` to suppress the original traceback. It does not dump settings to logs. No request exists yet, so construction fails instead of returning HTTP 422.

Production debug remains prohibited as defense in depth. Phase 1C also handles API failures before response start as safe JSON even with local debug enabled. Documentation visibility is independent and does not implement authorization. Centralized HTTP errors and log configuration are now implemented; see the linked Phase 1C notes.

## Lifespan ownership

`@asynccontextmanager` converts an async generator into an async context manager. FastAPI enters it on startup, pauses at `yield` while serving requests, and exits on shutdown. `try/finally` puts teardown on normal and exceptional context exits. See [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).

The hook now configures application JSON logging at the selected level, then emits lifecycle records with environment metadata. Phase 1B opened no external resources; Phase 2A now adds optional PostgreSQL engine/pool ownership, described in the linked session notes. Model clients remain later work. Forced process kills cannot run Python cleanup.

A request returning 500 does not normally end application lifespan. A test-only failing route is followed by successful health, then ordinary shutdown; it is not included in the production app.

## Testing the boundary

HTTPX ASGITransport sends in-process HTTP requests but no startup/shutdown events. `LifespanManager` supplies these events; use `manager.app` with the transport for lifespan state. See [asgi-lifespan](https://github.com/florimondmanca/asgi-lifespan).

Tests distinguish ASGI shutdown, an HTTP failure during a live application, and exceptional context unwinding. The last enters `application.router.lifespan_context(application)` directly: an exception in a manager body does not request normal shutdown.

An autouse fixture clears prefixed environment variables and disables default dotenv loading; pytest `monkeypatch` restores changes afterward. Explicit temporary files test dotenv behavior, keeping private developer configuration out of tests.

## Review questions

Discuss one at a time:

1. If `.env` enables debug but the process environment disables it, which wins, and why is that useful for deployment?
2. Why does invalid configuration stop app construction instead of returning HTTP 422?
3. Why should database connections eventually belong to lifespan instead of module import?
4. Why can a health HTTP test pass even when application startup is broken?

## Independent exercise

Use a temporary dotenv file containing production and debug enabled. Test that configuration fails, then override debug with a process environment variable set to false and verify app construction succeeds. Leave the real `.env` untouched. No solution is included.
