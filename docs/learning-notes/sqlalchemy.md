# PostgreSQL and SQLAlchemy sessions — Phase 2A

## Scope and ownership

The database infrastructure module now owns a PostgreSQL engine, its connection pool, and a factory for short-lived synchronous ORM sessions. FastAPI lifespan creates/checks/releases these resources when a database URL is configured. Phase 2B now adds user/workflow/version mappings and Alembic migration 0001; see [model/migration notes](migrations.md). This document records the session increment; repositories remain later work. Earlier SQLite drafts remain reference material.

This follows the planned synchronous session strategy. Later services will create/use/close each session in the same worker thread; Celery workers will own engines in their own processes. Never share a Session across concurrent requests/threads or inherit an active pool into a worker process.

## New dependencies and local services

SQLAlchemy **2.0.55** provides the engine, pool, transaction handling, and ORM Session. Psycopg **3.3.6** with its binary extra is the PostgreSQL driver. Transitive additions are psycopg-binary **3.3.6** and greenlet **3.5.6**. Existing foundation dependencies are unchanged; `uv.lock` records all resolved versions. The binary driver avoids requiring a local compiler/libpq installation for this development setup. See [Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html).

`compose.yaml` pins the already available PostgreSQL **16.14** image by digest. This is the tested version, not a claim that it is the latest release. Both services publish only on localhost:

| Service                        | Host port | Database/user    | Storage                                                               |
| ------------------------------ | --------- | ---------------- | --------------------------------------------------------------------- |
| `postgres`                     | 15432     | `agentflow`      | Named `agentflow_postgres_data` volume, retained when containers stop |
| `postgres_test` (test profile) | 15433     | `agentflow_test` | tmpfs, disposable data; no shared development volume                  |

Credentials in Compose and the examples are public **local-only** defaults. Do not reuse them in deployment. Each container uses a local development superuser; production least-privilege roles and deployment secrets are later work. Explicit names/ports isolate AgentFlow from the machine's existing containers. A `pg_isready` healthcheck lets `docker compose up --wait` wait for server availability; the Python integration suite separately verifies authenticated SQL connections.

There is no persistent application schema change. Integration writes use a PostgreSQL temporary table on one pooled connection; closing the pool removes it. Advisory transaction locks verify separate transactions without creating tables. Application tables and every later schema change require Alembic in Phase 2B. There is no `metadata.create_all()` shortcut.

## File-by-file explanation

| File                                                                          | Responsibilities and important calls                                                                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `compose.yaml`                                                                | Project-specific development/test containers, digest pin, loopback ports, storage, and server healthchecks. The test service is opt-in through a profile.                                                                                                                                                                      |
| `app/infrastructure/__init__.py`, `app/infrastructure/database/__init__.py`   | Package boundaries only; no import-time engine or network connection.                                                                                                                                                                                                                                                          |
| `app/infrastructure/database/session.py`                                      | `Database(url: SecretStr)` owns `create_engine(...)` and `sessionmaker(...)`. `check_connection() -> None` executes SELECT 1 and releases its connection. `session()` yields a fresh Session and closes it on all exits without committing. `dispose()` releases checked-in pool connections.                                  |
| `app/core/config.py`                                                          | Adds optional `database_url: SecretStr`. A field validator uses SQLAlchemy `make_url` to require `postgresql+psycopg`, explicit host/database, and a valid port. Errors use a static message; normal repr/JSON dumps mask the URL.                                                                                             |
| `app/core/lifespan.py`                                                        | Configures logs; creates the optional Database; runs blocking check/disposal through `run_in_threadpool`; stores the ready resource on app state; clears state in shutdown. SQLAlchemy startup errors become a static RuntimeError with suppressed original diagnostics. Pool disposal also runs after a failed startup check. |
| `.env.example`                                                                | Adds a commented optional development URL. The private `.env` was not edited. No URL preserves the health-only foundation mode.                                                                                                                                                                                                |
| `tests/conftest.py`, `pyproject.toml`                                         | Register `--integration` and the integration marker; ordinary tests explicitly skip database cases. Existing prefixed-environment isolation remains.                                                                                                                                                                           |
| `tests/integration/conftest.py`                                               | Requires `TEST_DATABASE_URL`; validates it without reading private dotenv. Refuses non-local hosts, a database other than `agentflow_test`, or URL query overrides. Creates and disposes a Database for each test. Missing/bad configuration fails explicitly when integration tests are requested.                            |
| `tests/integration/test_database.py`                                          | Real SQL connectivity, empty public schema, temporary-table commit/rollback, session closure, independent transactions and lock release, and checked-in connection cleanup.                                                                                                                                                    |
| `tests/integration/test_database_lifespan.py`                                 | Real configured startup and shutdown; pool connections actually close, app state clears, and health remains its exact public JSON. A refused local connection must fail startup safely.                                                                                                                                        |
| `tests/unit/test_database_config.py`                                          | Optional defaults, accepted secret URL, masked serialization, invalid drivers/hosts/databases/ports and safe failure messages.                                                                                                                                                                                                 |
| `tests/unit/test_database_startup_failure.py`                                 | Simulated driver failure verifies cleanup and sanitized errors. Fake operations run inline here; real thread-pool behavior is covered in integration tests.                                                                                                                                                                    |
| `scripts/check.py`                                                            | Adds `--integration`, forwarding it to Pytest while preserving lint/format/type checks and stop-on-failure behavior.                                                                                                                                                                                                           |
| `pyproject.toml`, `uv.lock`, README files, plan, development log, these notes | Dependencies, marker registration, setup/testing commands, progress, evidence, and limits.                                                                                                                                                                                                                                     |

## Engine, pool, Session, transaction

An **engine** is the shared connection/pool entry point. Constructing it does not immediately establish a database connection. The startup SELECT opens one and returns it to the pool. **Pool pre-ping** checks a connection on checkout, replacing stale connections when possible; it does not retry an in-flight transaction. The pool allows five retained connections plus five overflow connections, with a five-second pool wait and a five-second driver connection timeout. These are current fixed defaults, not per-query or total-request deadlines. See [SQLAlchemy engine configuration](https://docs.sqlalchemy.org/en/20/core/engines.html).

A **Session** represents one unit of database interaction. It is mutable and is not shared between operations. `Database.session()` closes it on both success and failure. Closing rolls back uncommitted work; it never decides that a successful function should automatically commit. `close_resets_only=False` prevents accidentally reusing a closed Session. `autoflush=False` keeps implicit query-triggered writes out of the flow; commit still flushes pending changes. `expire_on_commit=False` avoids automatically expiring already loaded values after commit; it does not make lazy relationships safe outside a closed session.

Services will choose a transaction explicitly, for example:

```python
with database.session() as session:
    with session.begin():
        # Future service/repository writes belong here.
        # Normal exit commits; an exception rolls back.
        ...
```

The Session handles transaction state; the service owns the decision and business boundary. Future routers should delegate to these services, not write SQL. External model/tool calls must happen outside an open transaction. See [SQLAlchemy session basics](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

## Startup and request flow

```text
create_app() → validate Settings (no network)
  → ASGI startup
      → create Database only if database_url exists
      → worker thread: connect + SELECT 1 + release connection
      → app.state.database = ready Database
      → serve HTTP
          health → constant public JSON (no SQL/readiness probe)
          future sync service → new Session → explicit transaction → close
  → ASGI shutdown (or failed startup check)
      → worker thread: dispose checked-in pool connections
      → app.state.database = None
```

If a URL is configured, PostgreSQL must be reachable at startup. No URL leaves database state None. The health route remains **liveness**, not readiness, and does not acquire a session. No database dependency is attached to it and no new endpoint has been added.

Startup SQLAlchemy/driver failures are intentionally replaced with a safe static error; raw diagnostics can contain credentials/hosts. SQL echo is disabled and statement parameters are hidden in SQLAlchemy errors. This is not a universal redactor: do not log a revealed SecretStr, arbitrary SQL, or driver exception in future code. Connection URL passwords with reserved characters must be URL-encoded. A database URL is revealed only at the driver boundary. Deployment TLS/roles, statement timeouts, migrations, readiness, and worker-specific initialization remain later work.

## Run and verify

From the repository root:

```bash
docker compose up -d --wait postgres
docker compose --profile test up -d --wait postgres_test
uv sync --directory backend --locked

# Fast checks; no PostgreSQL required:
uv run --directory backend --locked python scripts/check.py

# Real PostgreSQL tests; this published credential is for local tests only:
TEST_DATABASE_URL='postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test' \
  uv run --directory backend --locked python scripts/check.py --integration
```

To enable database-backed startup locally, add the commented development URL from `.env.example` to your private backend `.env`, then start Uvicorn as documented in the backend guide. Set `AGENTFLOW_DATABASE_URL` only for development/application startup. Set `TEST_DATABASE_URL` only for explicit integration tests; it is not loaded from `.env` and is never inferred from the development URL.

Stop the containers with `docker compose --profile test down`. This keeps the named development volume; do not add `--volumes` if you want to retain data. Test tmpfs data is disposable. PostgreSQL initialization variables apply when initializing empty storage; changing a Compose password later does not rewrite an existing database role. See the [official PostgreSQL image](https://hub.docker.com/_/postgres).

Verified on 30 October 2026: **53 tests passed and 8 integration tests skipped** in the ordinary check. With integration enabled, **61 tests passed**, Ruff lint/format passed (30 Python files), and Pyright reported zero errors/warnings. Docker/Compose configuration validated and both servers became healthy. A real PostgreSQL-configured Uvicorn process verified unchanged health/OpenAPI, request ID, safe logs, and graceful shutdown. No frontend/model/worker or Alembic result is claimed.

The sandbox allowed neither Docker/socket access nor real thread-pool wakeups. The real database suite ran with permitted access outside it. A stalled restricted unit run was stopped; its fake operation is now inline, and ordinary checks pass inside the sandbox. A duplicate unit/integration module basename initially blocked collection and was renamed. The verification containers were stopped and removed afterward; the development volume remains. Start services with the commands above before using them.

## Review questions

Discuss one at a time:

1. Why can we share an engine but not a Session between concurrent operations?
2. What happens to an INSERT when the Session closes without commit?
3. Why is the synchronous startup SELECT run through a worker thread?
4. Why do integration tests refuse the development database URL?
5. Why does an available liveness route not prove PostgreSQL is ready?

## Independent exercise and next increment

Write an integration test proving that an exception escaping `Database.session()` releases a transaction-scoped advisory lock. Use only the isolated `agentflow_test` target and no permanent tables. Try it before requesting the solution.

Phase 2B is now complete: see [models/migrations](migrations.md). The next increment is Phase 2C, repositories and explicit unit-of-work transaction tests.
