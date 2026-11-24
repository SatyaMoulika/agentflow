# Development log

## 13 November 2026 — Gmail provider foundation

Started the [Gmail integration sequence](gmail-implementation-plan.md) with code-owned Google OAuth authorization, PKCE and token-exchange/refresh primitives, fixed Gmail list/read endpoints, bounded sanitized provider errors and bounded plain-text extraction. Credentials are represented with SecretStr and provider calls do not follow redirects or retry. This is not exposed as a product feature: authorization state persistence, connection ownership, routes, editor nodes, triggers, approvals and Gmail actions are still outstanding. No migration or application configuration was changed and no real account or Google API was contacted. The standard backend check passed **944 tests** with **438 opt-in integration cases skipped**, plus Ruff and Pyright.

## 12 November 2026 — Workflow proposal output limit

A user received `PROVIDER_OUTPUT_LIMIT` while requesting an edit to a multi-node workflow. Workflow generation and editing require the provider to return the complete graph; their bounded completion allowance is now 4,096 tokens instead of the general JSON allowance of 2,048. Other provider calls retain their previous bounds. The planner also explains explicit mappings after conditions and numeric versus substring comparisons. Truncated responses remain errors and provider calls are not automatically retried.

The standard backend checker passed **932 tests** with **438 opt-in integrations skipped**, Ruff and Pyright; **49 focused PostgreSQL run and connection integration tests** passed. No real provider call, browser test or business-data replay was performed. A larger graph or model reasoning can still exceed the allowance or account quota.

## 12 November 2026 — Development schema update

After a user reported an unexpected error while running a workflow, a read-only check showed that development was still on migration 0010. Current run-detail code queries the invocation table introduced by 0011, including for non-agent workflows; the mismatch can cause a failure after execution. The request log was not available, so the exact exception was not confirmed. Applied the tested additive 0011 migration and initialized the separate checkpoint schema. `alembic current` reports 0011 head and `alembic check` reports no drift. An existing run was read successfully through the application service without displaying its data. No workflow was rerun and no development fixtures or destructive checks were used.

## 11 November 2026 — Phase 9A tracing foundation

Added fixed-name OpenTelemetry API instrumentation at HTTP, synchronous and pure node, model and tool boundaries. The default provider is a no-op; no SDK, exporter, collector or cross-process propagation was added. Span creation/cleanup failures do not interrupt execution, and no business payload, endpoint, identifier or exception text is added to spans. See [tracing notes](learning-notes/trace-instrumentation.md).

The standard backend checker passed **930 tests** with **438 opt-in integrations skipped**, Ruff and Pyright; a focused isolated PostgreSQL run passed **49 agent and worker tests**. New tests verify threadpool parenting, privacy and fail-open behavior using a recording test double. No new browser, provider, collector or Redis check was run. The existing PostgreSQL test service was preserved.

## 11 November 2026 — Phase 8C verification

The in-progress checkpoint implementation adds PostgreSQL-backed LangGraph state, retained invocation/thread correlation, explicit post-tool pauses, owner-checked continuation and execution-detail controls. Migration 0011 owns invocation history; a separate setup command installs the saver schema. Continuation never automatically replays an unknown in-flight external call. See [checkpoint setup and limits](learning-notes/agent-checkpoints.md).

Updated the OpenAPI and migration tests for the new endpoint and revision. The full guarded PostgreSQL/Redis backend checker passed **1,364 tests**, Ruff and Pyright; frontend checks passed **141 tests**, lint and build. A focused agent integration run passed **26 tests**. The existing test PostgreSQL was retained and the Redis test service started for this task was stopped. Development was not migrated; no new live-provider or browser acceptance run was performed.

## 30 October 2026 — Backend Phase 0 planning

**Scope:** inspect the supplied backend architecture brief, current frontend contracts and earlier unintegrated drafts; propose the incremental implementation and verification sequence. Planning/documentation only.

**Files added:** backend implementation plan; backend architecture; Groq provider plan; database ER/schema design; API inventory/contract-alignment plan; three proposed ADRs; this log. The root README receives a documentation link only.

**Findings:** frontend state mutations are synchronous and local; entity IDs/config/mapping/approver/retry models need deliberate API adapters. The SQLite JSON repository/in-process runner drafts do not implement the requested PostgreSQL/Alembic/worker architecture. They remain unmodified reference drafts. Docker/Compose/client binaries are present; daemon/database/model access is unverified.

**Concepts covered:** modular monolith boundaries, immutable workflow versions, ORM sessions and transactions, database normalization/JSONB, transactional outbox, at-least-once delivery, run leases, external side-effect ambiguity, typed node contracts, Groq capabilities, agent checkpoint ownership, per-run event ordering, JWT/refresh delivery and SSE authorization.

**Verification:** read repository/contracts and all sections of the brief; checked primary Groq/SQLAlchemy/FastAPI/Celery/LangGraph documentation; checked local tool version/binary availability; performed documentation formatting and relative-link/API-count checks. No backend, migration, worker, provider or browser behavior was tested or claimed. No dependencies were installed and no application/source files were changed in this phase.

**Open review points:** approve the proposed contract/DSL choices and synchronous-ORM starting strategy; confirm the logout addition; standardize the interpreter; decide draft replacement as a future explicit increment. Exact dependency pins are selected/tested in their owning phases. Private Groq account capability verification is deferred until Phase 7.

**Next increment:** Phase 1A, a minimal FastAPI application factory and tested `/api/v1/health` endpoint, after the architecture review. No automatic advance to later modules.

## 30 October 2026 — Backend Phase 1A

**Implemented:** independent FastAPI application factory, versioned router composition, typed public liveness response, OpenAPI/docs, and HTTPX API tests. No database/migration, auth, configuration service, workflow engine, worker, or model calls were added. The earlier `backend/agentflow/` drafts remain untouched.

**Files:** `backend/app/main.py`; `backend/app/api/router.py`; `backend/app/api/v1/health.py`; their package `__init__.py` files; `backend/tests/conftest.py`; `backend/tests/api/test_health.py`; `backend/.python-version`; `backend/pyproject.toml`; `backend/uv.lock`; backend README; FastAPI learning notes; root README and planning/API status updates; this log.

**Dependencies:** reused cached/installed FastAPI 0.162.0, Pydantic 2.14.2, Uvicorn 0.54.0, HTTPX 0.28.1, Pytest 9.2.0 and Ruff 0.17.3. Pydantic is now a direct requirement because the API response imports it. uv resolved/synchronized the lock offline; no new package download was needed. Pinned the existing Python 3.13.13 development interpreter, within the brief's Python 3.12+ requirement. Compatibility with later database/worker/model packages remains to be tested in their phases.

**Concepts:** application factory, ASGI server versus app, APIRouter prefixes, Pydantic Literal response fields, liveness versus readiness, async HTTP tests, OpenAPI schema verification and test isolation.

**Problems encountered:** sandbox socket restrictions prevented binding the local server and stalled Starlette's thread-backed TestClient; that wrapper also emitted an HTTPX deprecation warning. The elevated server/test diagnostic verified the app was working. Final automated tests use direct HTTPX ASGITransport with the already-installed AnyIO asyncio test support, avoiding the deprecated wrapper and socket requirement. No extra test-runtime package was installed.

**Actual verification:** 8 API tests passed with no warning in the final suite; Ruff lint and formatting checks passed for `backend/app` and `backend/tests`; locked offline dependency synchronization succeeded. Real Uvicorn HTTP checks returned 200 for `/api/v1/health` with the exact response and for `/openapi.json`, documenting only the implemented endpoint. The owned smoke-test server was stopped after checks. No database, browser, provider, worker, or Python type-checker result is claimed.

**Limits:** direct ASGI HTTP tests do not automatically exercise lifecycle hooks; none exist in this increment. Pyright is planned for Phase 1D. Frontend source and earlier backend draft implementations were not changed.

**Exercise:** add a regression test for POST health returning 405; do not change the endpoint.

**Next increment:** Phase 1B, validated environment settings and startup/shutdown behavior. Review this increment and discuss the first knowledge-check question before continuing through the next learning increment.

## 30 October 2026 — Backend Phase 1B

**Implemented:** typed per-app configuration for title, environment, debug, and documentation visibility; absolute optional `backend/.env` path; explicit configuration injection; production debug protection; sanitized configuration failures before app construction; async startup/shutdown context with environment-only lifecycle records. The exact public health contract is preserved. No database, auth, provider, worker, or frontend integration was added.

**Files:** added `backend/app/core/__init__.py`, `config.py`, `lifespan.py`, `backend/.env.example`, `backend/tests/unit/test_config.py`, `backend/tests/api/test_application.py`, `backend/tests/api/test_lifespan.py`, and `docs/learning-notes/configuration.md`. Updated `backend/app/main.py`, shared test fixtures, dependency manifest/lock, backend/root READMEs, implementation plan, FastAPI notes, and this log. Existing health routes/tests, legacy drafts, and frontend source remain unchanged.

**Dependencies:** explained and installed pydantic-settings 2.16.2 for typed environment/dotenv loading and dev-only asgi-lifespan 2.1.0 for explicit ASGI startup/shutdown tests. Transitive additions: python-dotenv 1.2.4 and sniffio 1.3.1. Network access was needed because these packages were not cached; the approved download succeeded. Existing FastAPI/Pydantic/Uvicorn/HTTPX/Pytest/Ruff versions remain unchanged.

**Concepts:** settings precedence, field/cross-field validation, immutability, constructor injection, per-instance state, fail-fast configuration, sanitized errors, async context managers, `yield`/`finally`, request errors versus app shutdown, and isolated test configuration. Unknown dotenv keys are ignored for sharing; the trade-off is that misspelled variable names are ignored too.

**Problems encountered:** two line-length lint errors were fixed by Ruff formatting. The sandbox again prevented localhost binding; the approved live check outside it passed. ASGITransport does not trigger lifespan, so lifecycle checks explicitly use LifespanManager and its managed app. Exceptional context unwinding is checked directly rather than assuming an exception inside the manager requests normal ASGI shutdown.

**Actual verification:** 25 tests passed (12 settings, 10 HTTP, 3 lifecycle); scoped Ruff lint/format checks and locked offline synchronization passed. Real Uvicorn checks verified exact health, configured OpenAPI title, disabled docs/OpenAPI routes, and graceful startup/shutdown with documentation on and off. A separate process rejected production debug before startup. Owned verification servers were stopped. Tests use temporary dotenv files and do not read private local configuration.

**Limits:** no external resources are acquired, so no real connection/client cleanup is claimed. Lifecycle INFO records exist but log handlers/levels/JSON formatting remain Phase 1C. HTTP errors still use framework defaults. Forced process kills cannot run Python cleanup. Pyright remains Phase 1D; no frontend, browser, database, model, or worker tests ran in this increment.

**Exercise:** write a temporary-dotenv production/debug rejection test, then override debug through process environment and verify app construction succeeds. No solution provided.

**Next increment:** Phase 1C, request IDs, structured logging, and consistent HTTP error responses, after reviewing this increment. First review question: when dotenv and process environment disagree on debug, which wins and why?

## 30 October 2026 — Backend Phase 1C

**Implemented:** generated `X-Request-ID` for every HTTP request; isolated state/ContextVar correlation; one JSON completion record with method, route template, status, duration, environment, request ID, and unexpected exception type; startup JSON logging at a validated application log level; consistent HTTP/validation/unexpected-error envelopes and OpenAPI schemas. The health body is unchanged. No production demo route, database/migration, auth, worker, frontend integration, model call, or new dependency was added.

**Files:** added `backend/app/core/logging.py`, `exceptions.py`, `middleware.py`; API tests `test_errors.py` and `test_request_context.py`; unit tests `test_logging.py` and `test_middleware.py`; `docs/learning-notes/http-observability.md`. Updated `main.py`, `config.py`, `lifespan.py`, health header documentation, `.env.example`, test fixtures/config tests, backend/root READMEs, API inventory, implementation plan, configuration/FastAPI notes, and this log. The private `.env`, dependency manifests, frontend source, and legacy backend drafts were untouched.

**Concepts:** pure ASGI scope/receive/send, response-start semantics, middleware error boundary versus exception handlers, ContextVar tokens/reset, task-local versus shared state, UUID correlation versus authentication/tracing, static public error mappings, request versus response validation, logging handler ownership/propagation, allowlisted operational metadata, and streaming/cancellation limits. Logging configuration is process-global even though settings remain per-app.

**Problems encountered:** the concurrent lifespan/HTTP test exposed shared request-state dictionaries: each task's ContextVar was correct but another request overwrote `request.state.request_id`. Copying state before injecting the ID fixed the race. Added coverage for context restoration, unbuffered stream forwarding, committed-response failures, and cancellation. Ruff formatting fixed initial line-length/import errors. Sandbox socket restrictions prevented the initial bind probe; the approved Uvicorn smoke verification outside it passed.

**Actual verification:** 45 tests passed (20 additional cases); scoped Ruff lint/formatting, locked offline synchronization, documentation formatting, and relative-link checks passed. A temporary Uvicorn factory verified six real HTTP responses: health, 404, 405/Allow, validation 422, safe 500, and OpenAPI. JSON completion IDs/statuses matched every response, startup/shutdown records were present, and a private sentinel was absent from response/log output. Temporary factory/routes/files were outside the production app and removed; the owned server stopped gracefully. Existing application/config/lifecycle checks still pass. No Pyright, frontend, browser, database, provider, worker, or telemetry check is claimed.

**Deliberate limits:** error details remain null rather than copying raw validator input/messages/context/locations. Common protocol headers are preserved; arbitrary exception headers are withheld. Pre-response API failures are safe JSON even with local debug enabled. Committed stream/background failures are logged and re-raised; the status cannot be replaced. Their raw server-level diagnostics need separate privacy handling. The formatter omits arbitrary extras/exception text but cannot protect a credential explicitly interpolated into a message. Uvicorn uses `--no-access-log` so application completion records replace raw URL access logs; its startup/system output remains separate. WebSocket correlation, trace/span IDs, domain-specific error details, and redacted stack diagnostics are later work.

**Exercise:** test `/docs` response correlation when enabled and matching 404 header/body IDs when disabled, without changing the health payload or private `.env`. No solution included.

**Next increment:** Phase 1D, Pyright and repeatable foundation checks. First review question: why is a global string unsafe for request IDs when two requests overlap?

## 30 October 2026 — Backend Phase 1D

**Implemented:** dev-only Pyright, standard-mode configuration for active `app`, `tests`, and `scripts`, and `backend/scripts/check.py` as one command for Ruff lint, format verification, Pyright, and Pytest. The wrapper uses the running interpreter, an explicit backend working directory, subprocess argument lists without a shell, and stops at the first nonzero exit. No API contract, database, migration, request flow, or transaction behavior changed.

**Files:** added `backend/scripts/check.py` and `docs/learning-notes/backend-checks.md`; updated dependency manifest/lock, exception callback annotations and narrowing, configuration tests, log metadata assertions in API/lifecycle/middleware tests, backend/root READMEs, implementation plan, HTTP learning notes, and this log. The private `.env`, `.env.example`, frontend source, and legacy drafts were untouched.

**Dependencies:** explained and installed Pyright 1.1.414 with transitive nodeenv 1.11.1, both development-only. The uncached package required an approved download. Runtime dependency versions are unchanged. The Python Pyright wrapper uses Node; verification used existing Node 22.22.3 and Python 3.13.13. Automatic Node provisioning on a fresh machine may require network access and is not pinned by the Python lockfile.

**Concepts:** static versus runtime validation, callback parameter compatibility, `isinstance` type narrowing, dynamic logging metadata, Pydantic synthesized signatures, minimum static Python target versus actual test interpreter, subprocess exit statuses, explicit working directories, and repeatable local quality checks.

**Issues fixed:** initial Pyright run found 14 diagnostics: framework callback parameters were narrower than the registered callback type; tests accessed dynamically added LogRecord fields as declared attributes; dotenv runtime constructor keywords were absent from Pydantic's synthesized static signature. Callbacks now accept Exception and narrow their expected subtype. Tests inspect metadata dictionaries and use isolated temporary dotenv model configuration. No broad diagnostic suppression or type-ignore workaround was introduced. A misspelled diagnostic option was corrected to `reportUnnecessaryTypeIgnoreComment`.

**Actual verification:** combined checker passed from backend and repository-root entry points: Ruff lint passed, 22 Python files were formatted, Pyright reported 0 errors/0 warnings, and 45 tests passed. Locked offline synchronization, documentation formatting, and relative-link checks passed. An actual temporary typed source mismatch made Pyright fail and prevented Pytest from starting; the probe was removed in `finally` and clean checks passed afterward. No new unit tests were added for the wrapper; its actual success and failure behavior was exercised directly.

**Limits:** standard mode includes dynamically typed framework boundaries; zero diagnostics do not prove strict typing or replace behavior tests. Python 3.12 is the static target, while runtime tests use pinned 3.13.13. Legacy drafts are outside scope. This is local automation, not configured remote CI. No live server, frontend, browser, PostgreSQL, migrations, worker, provider, or telemetry check was run for this tooling increment. Prior live-server results remain under Phase 1C.

**Exercise:** temporarily add a function annotated to return int that returns a string; predict the failure, run the combined command, then fix/remove it and restore green checks. Do not change private configuration or suppress the error.

**Next increment:** Phase 2A, verify Docker/Compose access and isolated local PostgreSQL databases, then configure SQLAlchemy session lifecycle. Tables/migrations follow in Phase 2B. First review question: what can Pyright detect that a passing API test might miss?

## 30 October 2026 — Backend Phase 2A

**Implemented:** isolated Compose PostgreSQL development/test services; optional secret database URL with supported driver/host/database validation; synchronous SQLAlchemy engine/session factory; explicit transaction ownership; configured startup connectivity check; pool disposal on shutdown or failed startup. The exact health/OpenAPI endpoint set is unchanged. No application tables, ORM mappings, repositories, migrations, auth, worker, or provider module was introduced.

**Files:** added root `compose.yaml`; `backend/app/infrastructure/` and `database/` package markers; `database/session.py`; database config and startup-failure unit tests; integration fixture and database/lifespan suites; `docs/learning-notes/sqlalchemy.md`. Updated `core/config.py`, `core/lifespan.py`, `.env.example`, test options/markers, `scripts/check.py`, manifest/lock, backend/root guides, implementation plan, database schema status, architecture status, tooling notes, and this log. Private `.env`, frontend source, and legacy drafts remain untouched.

**Dependencies/services:** approved download installed SQLAlchemy 2.0.55, Psycopg 3.3.6 and psycopg-binary 3.3.6, with transitive greenlet 3.5.6. Existing foundation versions remain unchanged. Used cached PostgreSQL 16.14 pinned by digest, a tested version rather than a latest-version claim. Loopback-only ports 15432/15433 avoid existing services; dev has a retained named volume, tests use tmpfs and a separate user/database. Compose credentials are public local-only defaults, not deployment credentials.

**Concepts:** engine versus pooled connection versus mutable Session, per-thread/session ownership, explicit commit, rollback on uncommitted close/exception, transaction-scoped locks, pre-ping versus in-flight transaction retries, startup blocking I/O offload, resource ownership/cleanup, secret URL validation, liveness versus readiness, isolated real-database tests and temporary tables without application schema changes.

**Problems fixed:** sandbox Docker access required approved execution outside it. A duplicate unit/integration test basename initially prevented collection and was renamed. Pyright caught an optional password assertion, corrected with explicit narrowing. A fake startup-failure unit test stalled at sandbox thread-pool wakeup; its fake I/O operation now runs inline, while actual worker-thread behavior remains covered by integration tests. The stalled owned process was stopped. Ordinary tests then passed inside the sandbox; real SQL tests require permitted socket access.

**Actual verification:** Compose config validated and both PostgreSQL services became healthy. The full checker passed Ruff lint/format (30 Python files), Pyright with zero errors/warnings, and 61 tests against real PostgreSQL. Ordinary checks passed 53 and explicitly skipped 8 integration cases. Database tests verified connection/database identity, empty public schema, committed versus rolled-back temporary writes, closed-session non-reuse, separate concurrent transactions and advisory-lock release, checked-in pool connection disposal, configured startup/shutdown, and sanitized refused-connection failure. A live database-configured Uvicorn process verified unchanged health/OpenAPI, request ID, graceful shutdown, and absence of connection URL/password in logs. Dependency sync, documentation formatting, and relative-link checks passed. Verification containers/server were stopped and removed afterward; the development volume remains. No frontend, model, worker, or migration result is claimed.

**Limits:** absent database URL intentionally preserves health-only mode; a configured unreachable database prevents startup. No DB-aware readiness endpoint exists. Pool limits/timeouts are fixed defaults and not SQL/query deadlines. Dispose releases checked-in connections; operations must close their sessions before shutdown. Integration tests require explicit local `agentflow_test` URL with no query overrides and never infer the development URL or read private dotenv. Test writes use connection-local temporary tables only. Deployment roles/TLS/secrets and worker process initialization remain future work. Alembic is not installed until its owning next increment.

**Exercise:** write an integration test proving an exception escaping `Database.session()` releases a transaction-scoped advisory lock, using no permanent tables and only the isolated test database.

**Next increment:** Phase 2B, users/workflows/workflow-version ORM models and Alembic migrations, with circular FK creation order, constraints/indexes, and empty-database upgrade/downgrade checks. First review question: why can an engine be shared but not a Session between concurrent operations?

## 30 October 2026 — Backend Phase 2B

**Implemented:** User, Workflow, WorkflowVersion SQLAlchemy mappings and Alembic revision 0001; named metadata, UUID defaults, timezone-aware timestamps, normalized unique email, bounded/nonempty fields, checked lowercase statuses, positive unique version numbers, versioned JSONB object envelope, restrictive foreign keys, owner/status/history/creator indexes, and same-workflow composite current-version reference. Database triggers maintain user/workflow updated_at and reject version UPDATE/DELETE/TRUNCATE. No business services, repositories, hashing/authentication, workflow CRUD, execution, or provider features were added.

**Files:** added database `base.py` and `models.py` registry; `app/modules/` package markers plus `auth/models.py` and `workflows/models.py`; `backend/alembic.ini`; migration environment/template/0001 revision; unit mapper/offline migration tests; integration ORM/migration tests; migration/schema fixtures; `docs/learning-notes/migrations.md`. Updated manifests/lock, check script/Pyright scope to include migrations, backend/root guides, implementation plan, schema/ER/architecture status, session/tooling notes, and this log. Private `.env`, frontend/build assets, and earlier drafts were untouched.

**Dependencies:** explained and installed Alembic 1.20.1 with Mako 1.4.3 and MarkupSafe 3.0.4, after the package was absent from cache. Existing SQLAlchemy/Psycopg and foundation versions remain unchanged. Alembic is a direct schema-management dependency, not only a test tool.

**Concepts:** declarative metadata and typed mappings, relationship versus FK, explicit joins for circular references, nullable current pointer versus version history, composite referenced uniqueness, flush versus commit, JSONB storage versus executable validation, restrictive deletion, database-enforced append-only history, generated defaults/updated_at, immutable migration history, online/offline DDL, supplied Alembic connections, schema isolation, and drift-detection limits.

**Actual verification:** full checks passed 90 tests with real PostgreSQL (29 additional cases), Ruff lint/format for 42 Python files, and Pyright with zero errors/warnings. Ordinary checks passed 55 and skipped 35 integration cases. Verified empty-schema upgrade, populated-table downgrade, cleanup, re-upgrade, revision identity, named indexes/composite FK, and no ORM drift after upgrade/re-upgrade. Checked relationships/UUID/UTC defaults, normalized email uniqueness, bad owners/status/names, version uniqueness/schema/JSON/FKs, cross-workflow pointers, ORM/direct SQL mutation rejection, TRUNCATE protection, restrictive parent deletion, preserved old snapshots, and timestamps. Offline SQL generation works without a URL.

**Development database:** confirmed empty before applying the tested upgrade, then migrated to 0001. `alembic current` reports head; `alembic check` reports no new upgrade operations. Expected three application tables plus alembic_version exist; application row counts are all zero. No development downgrade or fixture seeding occurred. Its pre-existing PostgreSQL container was left running; only the test container started for verification was stopped/removed. Random test schemas were removed, with public test schema left empty. Locked sync, documentation formatting, and links passed. No live browser/model/worker or new API-server test was claimed.

**Issues fixed:** initial lint feedback required splitting long SQL strings; Pyright required optional reflected-FK metadata access. Tests were strengthened to reject numeric/null JSON schema versions and to exercise downgrade with populated circular references, without changing an already-applied migration. No broad type suppression was introduced.

**Limits:** lowercased stored email is not account validation/deliverability; password hashing is Phase 3. JSON envelope constraints are not graph compilation or authorization. UUID/FK existence does not grant ownership permissions. Consecutive version allocation and stale updates belong to later service/repository rules. Current-version navigation is view-only, and loaded relationships need refresh after pointer changes. Plain JSON nested mutation is not tracked automatically; treat snapshots as immutable. Database owners can disable/drop triggers; deployment privileges remain later work. Alembic check does not validate trigger bodies/check logic, so explicit PostgreSQL tests cover them. Initial downgrade deletes tables/data and is tested only in disposable schemas.

**Exercise:** test that different workflows may each have version_number 1, while duplicate version_number 1 for one workflow fails. Use isolated migrated fixtures, not the development database.

**Next increment:** Phase 2C, repositories and explicit unit-of-work transaction tests before authentication. First review question: why is a foreign key on current_version_id alone insufficient to prevent using another workflow's version?

## 30 October 2026 — Local command/configuration troubleshooting

The user ran a repository-root command while already inside `backend/`, then correctly ran the ordinary checks from the root (55 passed, 35 skipped). Alembic reported the missing application database URL. Enabled the published local Compose connection in the existing private `backend/.env`, preserving other settings; no private values were printed. Clarified root versus backend commands and the missing-URL remedy in the backend guide.

Verified using the actual dotenv configuration, without a process URL override: upgrade head succeeded, current reported `0001 (head)`, and Alembic check reported no new upgrade operations. Socket restrictions required the permitted check outside the sandbox. No application code, table definitions, or frontend assets changed, so the backend suite was not repeated. Phase 2C remains next.

## 30 October 2026 — Backend Phase 2C

**Implemented:** concrete UserRepository and WorkflowRepository with caller-owned Sessions; user insert/ID/email queries; owner-scoped workflow/version reads, bounded ordered listings, draft insertion, and immutable version append under a refreshed workflow row lock. Database.unit_of_work selects one transaction for cooperating repositories, commits on normal exit, rolls back escaping failures, and always closes. Version appends compare expected current number, allocate from saved history, deep-copy JSON, advance the pointer, and expire cached navigation/timestamp. Missing/not-owned and stale writes have plain module exceptions, without HTTP mappings yet.

**Files:** added `app/modules/auth/repository.py`, `app/modules/workflows/repository.py`, `app/modules/workflows/exceptions.py`; integration `test_repositories.py`, `test_repository_concurrency.py`; `docs/learning-notes/repositories.md`. Updated database session context, integration fixtures for independent schema-translated pooled sessions, backend/root guides, implementation plan, schema/architecture status, migration notes, and this log. No dependency/lock/migration/model, private configuration, frontend/build artifact, or legacy-draft change was needed.

**Concepts:** flush versus commit, caller-chosen transaction boundaries, all-or-nothing multi-table persistence, rollback after business/constraint failures, independent connection visibility, scoped repository queries versus authentication, SELECT FOR UPDATE with expected-version checks, ORM identity-map refresh and navigation expiration, defensive JSON copying, and real concurrency tests with bounded barriers/SQL deadlines. No generic repository/interface or additional unit-of-work class was introduced.

**Actual verification:** full checker passed 105 tests against real PostgreSQL, including 15 new integration cases; Ruff lint/format passed for 47 Python files and Pyright reported zero errors/warnings. Ordinary checks passed 55 and skipped 50 integration cases. Proved joint user/workflow/version commit, session closure, invisible uncommitted inserts, rollback/recovery after business and constraint failures, scoped reads/appends, deterministic bounded listing, preserved history/copied input, refreshed cached relationships, preserved pending metadata, stale-save rollback, and invalid-envelope rollback. Two simultaneous cached-version writers used distinct PostgreSQL connections and produced one new version/one conflict. A concurrent duplicate-email race produced one committed row/one integrity failure with rollback. Existing migration round trips and drift checks remain green. Locked sync, documentation formatting, and relative links passed.

**Design consideration:** populate_existing refreshes cached ORM state after a waiting row lock; without it stale cached pointers could accept a second outdated save. Pending changes are flushed before refresh to avoid discarding same-transaction edits; any later failure rolls those edits back. Version pointer/history navigation and updated_at are expired after writes for consistent reads in the same Session. Tests include each case.

**Database state:** revision remains 0001; no development writes or schema changes occurred. All new test writes used random migrated schemas in the guarded local agentflow_test database, with independent pooled connections rather than one shared migration connection. Test schemas and temporary test container were removed after checks. The existing development PostgreSQL service remains running.

**Limits:** repositories assume trusted, normalized inputs/precomputed password hashes and owner IDs from a future authenticated service. They do not implement authentication, password hashing, graph validation, HTTP endpoints/error mapping, archive/status transitions, collaboration, production query/lock deadlines, or automatic deadlock/serialization retries. Unknown DB integrity errors remain internal SQLAlchemy outcomes. Callers must handle failures outside the unit of work and keep external calls outside its locks. Default READ COMMITTED concurrency is tested; other isolation levels may need explicit retry policy. No new live API/browser/model/worker test is claimed.

**Exercise:** raise after a successful version append, then verify in a fresh unit of work that the earlier version remains current and the new snapshot is absent. Use repository_database and no development writes.

**Next increment:** Phase 3A, Argon2 password hashing, registration AuthService, safe duplicate-email conflict mapping, and registration endpoint. Login/JWT and refresh follow as separate increments. First review question: why must repositories flush without committing when several tables form one operation?

## 30 October 2026 — Backend Phase 3A

**Implemented:** public POST /api/v1/auth/register; strict registration input/public-user output schemas; email/name trimming and lowercase account identity; unchanged 15–128-character passwords with blank-only rejection; Argon2id RFC 9106 low-memory hashes with independent salts. AuthService hashes before opening a transaction, inserts through UserRepository, constructs the public DTO before commit, and returns after successful commit. Only the named email unique violation maps to 409 EMAIL_ALREADY_REGISTERED; storage/pool unavailability maps to 503, unrelated integrity failures remain safe 500s. No tokens/cookies are issued.

**Files:** added app/core/security.py, app/api/dependencies.py, app/api/v1/auth.py, auth schemas/service/exceptions, two unit test modules, API registration contracts, PostgreSQL registration integration tests, and docs/learning-notes/authentication.md. Updated app construction/router, shared static error mapping, auth module description, health route inventory test, dependency manifest/lock, backend/root guides, API inventory, architecture status and implementation plan. No model/migration, private .env, frontend/dist or legacy-draft changes.

**Dependencies/concepts:** argon2-cffi 25.1.0 and email-validator 2.3.0 are locked with their transitive dependencies. Explicit 64 MiB/three-iteration/four-lane Argon2id profile, fresh salt, one-way password verifier versus SecretStr masking, explicit DTO allowlists, sync route worker-thread ownership, hash-before-transaction, commit-before-response, domain exceptions versus HTTP mapping, and database-authoritative duplicate handling. No unneeded verification/JWT dependencies are added before login.

**Actual verification:** full backend check passed **136 tests** with real PostgreSQL; ordinary check passed **80, skipped 56**. Ruff lint/format passed for 57 Python files, Pyright reported zero errors/warnings, locked offline synchronization passed. Tests cover exact password preservation/verification and random salts/profile; strict validation/Unicode/boundaries/extra-field rejection; public-only UTC output; safe 201/409/422/503/unexpected 500; matching request IDs; real hash/SQL work in one worker thread with hashing before any transaction; failed response DTO construction rolling back INSERT; storage failure then recovery; and simultaneous normalized signup yielding one account/one mapped conflict. Existing repository, constraint, migration round-trip and drift checks remain green.

**Live HTTP:** temporary real Uvicorn factory used the production app with only its Database resource overridden to a random migrated local test schema. Verified health 200, register 201/no-store/no cookie, duplicate 409, invalid input 422/null details, exactly two OpenAPI paths, response/log correlation, credential/hash privacy and graceful shutdown. Temporary factory/server/schema were removed. Test DB inspection found zero random test schemas and zero public tables. Only the test service started for verification was stopped/removed; pre-existing development postgres remains running. No development accounts were inserted.

**Issue resolved:** a failure-path test initially assigned None to a datetime ORM attribute, correctly rejected by Pyright. It now injects a naive datetime: valid for the Python attribute type but invalid for the public AwareDatetime contract, exercising real post-INSERT rollback without suppressions. No production behavior was weakened.

**Limits:** registration is not login. JWTs, /auth/me, refresh/revocation, ownership dependencies, rate limiting, breached-password checks, mailbox verification/recovery and frontend auth integration remain unimplemented. Duplicate 409 intentionally discloses registered addresses. Email syntax does not prove deliverability. Passwords retain their original Unicode sequence. Argon2's per-concurrent-request memory cost needs capacity/rate controls before public deployment. No compliance or production-ready claim; no Groq/provider/worker/browser behavior was exercised.

**Exercise:** with repository_database, fail a first registration after INSERT, restore normal behavior, and successfully register the same email. Verify exactly one account in a fresh transaction; no solution is supplied and no development writes are needed.

**Next increment:** Phase 3B, login/access JWTs and /auth/me, with credential, inactive-user, invalid/expired-token tests before refresh sessions. First review question: why should password hashing happen before opening the database transaction?

## 30 October 2026 — Backend Phase 3B

**Implemented:** public JSON POST /api/v1/auth/login and HTTP Bearer GET /api/v1/auth/me. Login normalizes email and verifies exact passwords with Argon2 outside the initial closed read Session; unknown accounts execute a genuine public dummy-hash check. A second read requires an active account and unchanged hash before issuing. /me validates the token subject then checks current account existence/active status. Wrong/unknown/inactive/deleted or invalid/expired credentials share safe 401 UNAUTHENTICATED with WWW-Authenticate: Bearer. Storage/key unavailability returns safe 503. Login returns public user data plus a short-lived access token and no-store/no-cache; /me returns public user data with no-store. No cookies or refresh tokens are issued.

**Token/configuration decisions:** fixed HS256, private configured key with no default; 32–4096 UTF-8 bytes and no outer whitespace, with random generation documented. Issuer defaults agentflow, single audience agentflow-api, TTL 900 seconds bounded 60–3600. Required sub/iss/aud/iat/nbf/exp/jti/token_type, canonical UUIDs, integer dates, exact access purpose/header, bounded input and lifetime, no future/expired claims. Algorithm never comes from an untrusted header; signatures and claims are verified, not merely decoded. No email/password/hash/role in JWTs. Configured key is optional so health/registration retain their earlier contracts; /me without Bearer credentials fails 401 before key/DB lookup.

**Files:** added app/core/tokens.py, tests/unit/test_access_tokens.py and test_auth_config.py, tests/api/test_login_contract.py, tests/integration/test_login.py, and docs/learning-notes/login-access-tokens.md. Updated settings, password verifier, auth schemas/service/exceptions/repository scope comments/package, API dependencies/routes, app description, hash tests and four-route health/registration inventory tests. Updated .env.example, manifest/lock, backend/root guides, API inventory, implementation plan and architecture status. PyJWT 2.15.1 adds no extra transitive dependency. No schema/migration, private .env, frontend/dist or legacy draft changes.

**Actual verification:** full checker passed **199 tests** with real PostgreSQL; ordinary checker passed **131, skipped 68**. Ruff lint/format passed 62 Python files; Pyright reported zero errors/warnings; locked offline synchronization passed. Added 51 ordinary and 12 PostgreSQL cases. Genuine signatures/hostile claims cover missing/wrong issuer/audience/purpose/UUID/date/header/algorithm/key, expiry/future/oversized/malformed credentials. Contract tests cover JSON login, HTTP Bearer OpenAPI, strict safe input, no cookie/query fallback and missing-key behavior. Integration tests prove two identities stay distinct, wrong/unknown/inactive credentials have the same safe response, deactivation/deletion rejects existing tokens, changed password/status during verification is rechecked, and storage failures recover. Thread/pool observations prove verification occurs in a worker without retaining a login read transaction. Passwords/hashes/keys/tokens are absent from profile/error responses and application logs.

**Live HTTP:** temporary real Uvicorn smoke verified register 201, login/me 200, missing/wrong credentials 401, rejection after deactivation, four OpenAPI paths, no-store/no cookie, matching response/log request IDs, secret privacy and graceful shutdown. Its only resource substitution was a Database mapped to a random migrated local test schema; signing key was randomly generated for that process. The development database/configuration was untouched. Cleanup confirmed zero random test schemas/zero public test tables, removed the temporary server/factory/test container, and left the pre-existing development postgres running.

**Issues resolved:** a test caught global settings whitespace stripping happening before a signing-key after-validator. Added a before-validator so keys cannot be silently changed. Tests also narrow SQLAlchemy's generic Pool to QueuePool before observing checkouts; no suppressions. Wrong-algorithm test uses an appropriately long test key to avoid an unrelated library warning. Scope comments were refreshed without persistence changes.

**Limits:** no refresh/reuse detection/logout/revocation, password-reset/version-based invalidation, rate limiting, MFA, browser cookie/CSRF/CORS integration, frontend wiring or automatic hash-parameter upgrade. JWT signatures are not encryption; unique jti is not replay protection. An active-account token remains reusable until expiry; a later password change does not revoke it. Disable/delete is enforced by current-user lookup; reactivation may restore an unexpired token. Key rotation invalidates all prior tokens, and reducing configured TTL can reject older longer-lifetime tokens. HMAC verifiers also hold signing authority; synchronized clocks are required with zero leeway. No deployment/compliance/provider/worker/browser claim.

**Exercise:** in repository_database, log in, change display_name in a separate transaction, then call /auth/me with the original token and verify the new name. No development writes or solution provided.

**Next increment:** Phase 3C, persistent refresh sessions/rotation/reuse detection, with cookie/CSRF design, migration and concurrent/replay/expiry tests. First review question: why should /auth/me query the current account after verifying the JWT signature?

## 30 October 2026 — Backend Phase 3C

**Implemented:** persisted refresh families and retained one-use token history; POST /api/v1/auth/refresh; login now commits a family before setting refresh/CSRF cookies. Each refresh locks its family, rereads token state after waiting, validates server-bound CSRF, consumes the token and inserts its replacement atomically. Known consumed-token replay with valid proof commits family revocation before returning safe 401, rejecting descendants while leaving separate login families usable. Default family expiry is seven days absolute, never extended by rotation. PostgreSQL stores only SHA-256 digests of independent 256-bit opaque refresh/CSRF values, never raw credentials.

**Browser contract:** default __Host-agentflow_refresh is Secure/HttpOnly; __Host-agentflow_csrf is Secure/readable. Both are SameSite=Strict, Path=/, no Domain. Login/refresh require one exact allowed Origin and X-AgentFlow-Client: web; refresh also requires X-AgentFlow-CSRF equal to its cookie and server-side token binding. CSRF failures return safe 403 without consuming/revoking/clearing. Unusable refresh returns safe 401 and clears the pair; storage failures return 503 without clearing. Successful login/refresh returns access_token, csrf_token, bearer type, access lifetime and public user, with no-store/no-cache. Local HTTP explicitly disables Secure and uses unprefixed names; production refuses that mode and requires HTTPS origins when auth is configured. No CORS middleware or frontend connection is added.

**Files:** added core/refresh_tokens.py, auth/refresh_models.py and refresh_repository.py, api/auth_cookies.py, migration 0002_refresh_sessions.py; unit refresh config, API refresh contract, integration rotation/concurrency/model tests; docs/learning-notes/refresh-sessions.md. Updated config, auth service/result/schema/exceptions, API dependencies/routes, model registry, app description, .env.example, existing login/health/schema/migration tests, backend/root guides, API/schema/ER/architecture/implementation-plan documents and learning-note crosslinks. No new package/lock change, private configuration edit, frontend/dist or legacy-draft change.

**Schema/transaction decisions:** refresh_sessions is the family with owner/absolute expiry/revocation; refresh_tokens retains unique token digests, bound CSRF digests and consumption timestamps. FK cascades remove refresh state on account/family deletion. Hex/expiry checks and a partial unique family index enforce digest shape and one unconsumed row. Consume flushes before replacement insert to release that index. SELECT FOR UPDATE plus populate_existing avoids stale cached token state after lock waits. Revocation is raised as an HTTP outcome only after normal unit-of-work exit commits; insert/signing/DTO failures escape and roll back consumption. No grace-window/raw-secret recovery or access-JWT denylist is implied.

**Actual verification:** full checker passed **253 tests** against real PostgreSQL; ordinary checker passed **164, skipped 89**. Ruff lint/format passed 72 Python files; Pyright reported zero errors/warnings; locked offline synchronization passed. Added 33 ordinary and 21 PostgreSQL cases. Covered random/digest privacy, config limits/production flags/safe errors, Origin/client/CSRF rejection, no query/body/Bearer refresh fallback, cookie creation/deletion, absolute expiry, rotation/replay-family isolation, inactive/expired/revoked/unknown credentials, login/replacement/signing failure atomicity, storage recovery and credential-safe logs. Independent PostgreSQL PIDs/bounded barriers/SQL deadlines proved simultaneous same-token and ancestor-replay/current-token races leave no usable descendant after family revocation. Database tests prove FK/hash/expiry/unique/one-unconsumed guards and populated 0002→0001→0002 preservation/no drift; all earlier checks remain green.

**Live HTTP and development migration:** a temporary real Uvicorn process logged in using dev HTTP cookies, shut down, restarted from the same database, refreshed successfully, and accessed /me. Missing marker returned 403; old-token replay and its child returned 401 with cookie clearing. Checked five OpenAPI paths, committed family revocation, request/log ID matching, no raw key/password/token/hash leakage and graceful shutdown. Only Database was overridden to a random migrated test schema; key was process-local. Applied the tested additive 0002 upgrade through a guard requiring the existing localhost:15432/agentflow Compose database. Alembic reports 0002 (head), check reports no new upgrade operations. No development account writes/deletes or private .env edits occurred.

**Cleanup:** confirmed zero random test schemas and zero public test tables, removed temporary smoke server/factory/schema and disposable test container, and left pre-existing development postgres running. Documentation formatting and relative links passed.

**Issues resolved:** HTTP tests exposed a PostgreSQL UTC tzinfo representation incompatible with cookie GMT formatting; normalizing to datetime.UTC fixed real rotation cookie delivery. Malformed JSON origin environment values raise SettingsError before normal model validation, so load_settings now maps that case to a static ConfigurationError with no raw source. No type suppressions or weakened security expectations were introduced.

**Limits:** concurrent tabs/requests must serialize refresh; strict replay detection may reject the apparent winner after a simultaneous use. A lost committed rotation response requires fresh login if the old pair is retried. Family revocation does not revoke already issued access JWTs. Logout/owner authorization, password-reset invalidation, retention cleanup, rate/capacity limits, session/device management, production lock deadlines, cross-origin browser integration and frontend wiring remain later work. CSRF/HttpOnly do not solve XSS. No browser UI/deployment/OAuth-compliance/provider/worker claim.

**Exercise:** rotate twice in an isolated test, replay the original cookie/proof pair, then verify the newest refresh fails in a fresh request while another login family still works. No development writes or solution provided.

**Next increment:** Phase 3D, proposed refresh-family logout and owner-scoped dependencies before workflow CRUD. First review question: why must replay revocation commit before the service raises its 401 outcome?

## 2 November 2026 — Backend Phase 3D

**Implemented:** the previously documented POST /api/v1/auth/logout addition and reusable authenticated workflow/version ownership dependencies. Logout revokes only the refresh family represented by a cookie, including via a consumed ancestor, commits before clearing both cookies, and returns empty 204 with no-store/no-cache. It is idempotent for absent/malformed/unknown/already unusable state. Origin/client checks remain required; a present well-formed cookie requires bound CSRF proof. No access JWT/signing key is required. Storage/CSRF failures do not falsely claim success or clear retry credentials. Other login families and the existing access-JWT expiry model are unchanged.

**Ownership:** current active user supplies the owner UUID; owner-scoped repository reads require the containing workflow and version membership. Missing, not-owned and mismatched versions share the generic 404; storage failure maps to safe 503. Dependencies return frozen identifier references, not ORM objects/Sessions or persistent permission grants. Test-only routes exercise this boundary. No public workflow CRUD was added; future writes must still use owner-scoped SQL in their own transaction.

**Files:** added modules/workflows/access.py and api/workflow_dependencies.py, API logout contracts, integration logout/concurrency/ownership checks, and docs/learning-notes/logout-ownership.md. Updated refresh repository shared lock/revoke operations, AuthService logout/refresh, optional cookie/database dependencies, logout router/OpenAPI, workflow storage exception and factory handlers. Existing isolated database overrides now bind one shared get_database_resource dependency; health/registration route inventories and Origin rejection tests include logout. Updated backend/root guides, implementation plan, API inventory, architecture status, refresh-note crosslink and this log. No dependency/lock/configuration/model/migration, private .env, frontend/dist or legacy-draft changes.

**Contract decision:** this is the previously proposed one-route addition to the original 25-endpoint baseline: 26 scoped endpoints, six currently implemented. It is not logout-all or immediate access-token revocation. A cookie-free request can clear local cookies with no DB/key; a present well-formed credential requires storage before claiming successful server revocation. Bad proof returns 403 without disrupting a valid session. Consumed, expired or inactive state is not an obstacle to revoking the represented family. Caller body/query IDs do not select a family.

**Actual verification:** full checker passed **289 tests** against real PostgreSQL; ordinary checker passed **175, skipped 114**. Ruff lint/format passed 78 Python files, Pyright reported zero errors/warnings, and locked offline synchronization passed. Added 11 ordinary and 25 PostgreSQL cases. Logout tests prove first revocation timestamp preservation, cookie clearing/no body, repeat behavior, ancestor/other-family scope, stored proof binding, unknown/unusable credentials, absent signing key/invalid access header, private logs, rollback after flushed revocation, and storage/internal failure recovery. Independent backend PIDs and bounded barriers/SQL deadlines prove current/ancestor logout racing refresh leaves no usable descendant. Two-user HTTP probes prove allowed own reads, identical missing/unowned errors, ignored spoofed owner IDs, cross-workflow version denial, auth-before-ownership checks, worker execution and storage recovery. All prior migration/refresh/JWT/repository checks remain green; revision remains 0002.

**Live HTTP:** temporary real Uvicorn login/rotation, missing-marker 403, consumed-ancestor logout 204/no body/cookie deletion, server stop/restart, descendant refresh rejection, empty logout 204, and retained existing access-JWT behavior passed. Checked six production paths with no workflow/probe routes, secret omission, response/log request-ID correlation and graceful shutdown. Only the shared Database resource was overridden to a disposable migrated local test schema; key was process-local and HTTP cookie mode explicit. No development data/configuration was read or written for this verification.

**Issue resolved:** the first optional logout resource helper called get_database directly, bypassing FastAPI's injected test resource. Extracted get_database_resource as one optional shared injection point for both required data access and conditional logout; no test-only application switch or inspection of overrides was added. The sandbox also stalled the new ordinary successful sync-handler test's worker wakeup; the owned pytest process was stopped and both ordinary/full checks rerun with permitted access. No test expectations, security checks or production threading behavior were weakened.

**Cleanup:** zero random test schemas and zero public test tables remained. Temporary server/factory/schema and the owned test container were removed; existing development postgres remains running. Documentation formatting/relative links passed. No new development migration was needed.

**Limits:** logout revokes one refresh family, not every family/device or already issued JWT; clients must drop their in-memory access token. Frozen ownership references are snapshots, not substitutes for mutation-time owner filters. No workflow HTTP CRUD, run/connection/approval authorization, logout-all, password-reset invalidation, retention jobs, rate limits, production lock deadlines, browser UI/CORS/frontend integration or deployment completion is claimed.

**Exercise:** in isolated two-user fixtures, let B append a version to B's workflow; verify A still gets the same 404 for both B's workflow and new version while B can access both. No development writes or solution supplied.

**Next increment:** Phase 4A, owner-scoped workflow CRUD/archive with public DTOs and API checks. First review question: why must a future workflow write retain its owner filter inside the transaction after an ownership dependency has succeeded?

## 2 November 2026 — Backend Phase 4A

**Implemented:** owner-scoped workflow metadata create/list/get/patch/archive APIs. POST accepts strict trimmed name/description, creates status draft/current_version_id null, returns 201/Location; initial saved definitions are explicitly deferred to 4B. GET returns explicit metadata, including owned archived rows. List supports bounded page/page_size, optional status and literal case-insensitive name search with identical owner/filter conditions on count/items. PATCH applies only provided metadata fields; empty/null/privilege/status/graph changes are rejected. DELETE archives with empty 204 and preserves workflow/version pointer/history; repeat archive is safe, archived metadata edits return 409 WORKFLOW_ARCHIVED.

**Files:** added workflow schemas.py/service.py, api/v1/workflows.py, unit/API metadata contract tests and integration CRUD/concurrency tests, plus docs/learning-notes/workflow-metadata.md. Updated repository owner-lock/paging/metadata/archive operations, shared archived exception/handler, router/app description and exact health/registration/logout inventories. append_version now reuses the same refreshed owner lock while keeping its existing semantics. Updated root/backend guides, API inventory, implementation plan, architecture status, prior-note crosslink and this log. No model/configuration/dependency/lock/migration, private .env, frontend/dist or legacy-draft change.

**Contract and transaction decisions:** create is a versionless draft for this staged increment, not a fabricated saved/executable graph. Output is id/owner_id/name/description/status/current_version_id/UTC timestamps only. All five operations use active-user Bearer auth; cookie-operation headers/cookies do not authenticate workflows. Writes open their own unit of work, scope ownership inside SELECT FOR UPDATE, refresh cached state, mutate/flush/build DTO before commit. Same-field metadata requests serialize with the last write winning; expected-version graph saves remain 4B. Default listing excludes archived, explicit status=archived selects it; q uses bound icontains(autoescape=True), deterministic updated_at/ID ordering. Offset count/pages under READ COMMITTED are not a frozen concurrent snapshot.

**Actual verification:** full backend checker passed **347 tests** against PostgreSQL; ordinary checker passed **215, skipped 132**. Ruff lint/format passed 85 Python files; Pyright reported zero errors/warnings; locked offline sync passed. Added 40 ordinary and 18 integration cases. Checked strict trimming/limits, omitted/null/cleared PATCH distinctions and accurate OpenAPI, all-route Bearer auth, safe validation/ownership errors, complete metadata lifecycle, owner-only rows/counts, deterministic UUID ties and beyond-page totals, literal wildcard/quote search, versionless creation, preserved pointer/history and excluded graph JSON. Post-flush create/update/archive failures roll back and recover; invalid public timestamp after INSERT rolls back before Location/success. Separate connection PIDs prove disjoint partial edits and both cached-draft archive/update orders respect refreshed lifecycle state. All prior migrations/auth/ownership/version-repository checks remain green. A timestamp assertion was changed to compare parsed aware datetimes and its journey case rerun successfully.

**Live HTTP:** temporary real Uvicorn used actual registration/login, draft create 201, owned read/patch 200, stranger 404/empty listing, archive 204 and explicit archived filtering. After restart the archived row remained readable and PATCH returned 409. Verified 11 operations across eight paths, absence of test routes, private metadata/key/password/token omission from logs, matching request IDs and graceful shutdown. Only Database was mapped to a disposable migrated schema, with a process-local signing key and explicit dev HTTP cookies. No development data/configuration was involved.

**Smoke cleanup issue resolved:** the temporary smoke script reused its schema variable for the OpenAPI object, so its final DROP failed after application checks succeeded. Identified its sole retained random test schema by expected users/workflow/archive state, removed it, renamed the OpenAPI variable and reran the full smoke successfully. This was confined to temporary verification code and the dedicated test database. Cleanup then confirmed zero random test schemas and zero public test tables. Temporary server/factory/schema/test container were removed; existing development postgres remains running.

**Limits:** initial saved definitions and graph read/write/version APIs, expected-version concurrency, activation/restore, node registry/config schemas, compilation/execution, frontend wiring and production query deadlines remain pending. Metadata has no client ETag/revision precondition; offset listing can shift during concurrent writes. Archive policy is enforced by this metadata API; future graph/status services must apply their own lifecycle rules in their transaction. No graph validity/execution, browser UI or deployment completion is claimed. Revision remains 0002 with no new migration needed.

**Exercise:** in isolated two-user API fixtures, create/archive one workflow per owner, then verify status=archived rows and total remain owner scoped. No development writes or solution supplied.

**Next increment:** Phase 4B, immutable saved-definition APIs, initial versions, historical reads and expected-version concurrency. First review question: why does archive preserve a workflow and its immutable versions rather than deleting them?

## 2 November 2026 — Backend Phase 4B

**Implemented:** optional initial workflow definitions, immutable draft saves through the existing PATCH route, and owner-scoped historical reads via GET version_id UUID. Create without definition remains a versionless draft. Create with definition inserts version 1/pointer atomically. PATCH requires definition and strict nonnegative expected_version together, and rolls back accompanying metadata/snapshot/pointer on stale 409 WORKFLOW_VERSION_CONFLICT. Archived edits/saves remain 409 WORKFLOW_ARCHIVED; history stays readable. POST/item GET/PATCH add current_version_number and a selected version DTO; historical selection does not replace current metadata/pointer fields. List remains metadata only. API count remains 11 operations across eight paths.

**Definition contract:** schema_version "1.0", nodes/edges arrays of objects (max 500/2000), finite native JSON/string keys, depth 32, compact UTF-8 size at most 256 KiB. Extension/business keys round-trip verbatim. No node/config/DAG/executable validation, status activation or run is implied. Definition limits apply after HTTP body parsing. A successful identical JSON save still appends; no deduplication, idempotency or automatic stale merge. Metadata-only writes retain the earlier last-write behavior without a version precondition.

**Files:** extended workflow schemas/service, workflow API/exception mappings and app description; added unit/API/integration coverage within existing workflow test files. Reused the existing locked/deep-copy append repository and database immutable trigger without modifying repository/models/migrations. Added docs/learning-notes/workflow-versions.md and updated root/backend guides, API inventory, implementation plan, architecture/database notes, metadata-note crosslink and this log. No dependency/lock/private .env/frontend/dist/legacy-draft change; revision stays 0002.

**Actual verification:** complete backend checker passed **390 tests** against real PostgreSQL. Ordinary checker passed **247, skipped 143**; 32 ordinary and 11 integration cases added. Ruff lint/format passed 85 Python files, Pyright zero errors/warnings, locked offline synchronization passed. Focused workflow run passed 101 tests. Covered JSON byte/depth/array/schema/finite-value boundaries and preservation, paired strict integer save/OpenAPI contracts, initial/versionless appends, historical snapshot equality after saves/archive, owner/workflow membership privacy, stale combined-save rollback, post-flush snapshot/pointer rollback/recovery and invalid public version DTO rollback. Concurrent HTTP saves with independent backend PIDs prove one 200/one 409 from version 0 and version 1; cached-state archive/save tests prove both commit orders. An interleaved reader/writer check proves the read pins its immutable snapshot to the pointer read with metadata. Existing migration/drift/trigger/auth/metadata/repository checks remain green.

**Live HTTP:** temporary real Uvicorn with actual registration/login verified version 1, append to 2, stale 409, historical owner denial, current/history persistence across server restart, archive refusal, metadata-only listing, OpenAPI inventory, private password/key/token/definition omission from logs, request/log correlation and graceful shutdown. Only the shared Database resource targeted a disposable migrated local test schema; the signing key was process-local and cookie HTTP mode explicit. No development data/configuration was involved.

**Harness issue resolved:** its first stop assertion required exit 0, but installed Uvicorn re-raises SIGTERM after graceful shutdown. The harness now accepts 0 or the signal exit and explicitly checks shutdown logs. Schema cleanup now runs in a separate finally block even if a shutdown assertion fails. Verified the sole leftover schema by its expected two smoke accounts/workflow/two versions before removal, then reran the smoke successfully. This changed only temporary verification code, not application behavior or test expectations.

**Cleanup:** zero random test schemas and zero public test tables remained. Temporary smoke server/factory/scripts and the owned test container were removed; existing development PostgreSQL remains running. Documentation formatting and relative links passed. No new development migration was needed.

**Limits:** saved drafts are not executable; registry/configuration, authoritative validation/compiler, runs/workers/Groq and frontend API wiring remain later work. No history-list endpoint, restore/activation, transport/rate limits, production query deadlines, automatic secret detection inside arbitrary business JSON, browser UI or deployment completion is claimed. Historical metadata is current metadata, not a metadata snapshot at version creation.

**Exercise:** in isolated fixtures, save twice, archive, read version 1, then attempt a current-number save; verify rejected mutation preserves metadata, both snapshots and pointer. No development writes or solution supplied.

**Next increment:** Phase 4C, node registry and typed configuration, followed by authoritative graph validation/compilation in 4D. First review question: why must a stale save roll back its metadata changes as well as its version insertion?

## 2 November 2026 — Backend Phase 4C

**Implemented:** authenticated GET /api/v1/node-types with stable schema_version/items and six initial configuration contracts: manual, transform, condition, calculator, merge and end. Items include output handles, self-contained config JSON Schema, validate_config capability only and execution_ready false. Static frozen registrations/read-only lookup reuse TypeAdapter for both schemas and internal strict validation. Returned DTOs/schemas are fresh, so callers cannot mutate the code-owned catalog. Missing/invalid/inactive Bearer users use existing safe auth outcomes. Discovery is no-store and performs no database mutation. API count is now 12 operations across nine paths.

**Typed contract:** empty structural configs; predefined identity/pick_fields transforms; discriminated typed comparison operators; explicit literal/output calculator operands and bounded add/subtract/multiply/divide shapes. Configs forbid unknown fields/coercion, arbitrary expressions and non-finite/out-of-range numbers. References accept bounded ASCII $.node.output.field dictionary paths only; no evaluation/resolution happens. Unknown/invalid configs raise static domain errors without raw validator details. Incomplete/unsupported saved candidates remain drafts under the unchanged 4B save contract. Unimplemented provider/tool/approval/trigger types are absent from the catalog. Configuration readiness does not claim executable graphs or runtime outputs.

**Files:** added app/modules/workflows/node_configs.py, node_registry.py, api/v1/node_types.py, tests/unit/test_node_registry.py and tests/api/test_node_types.py. Updated API router/description, exact route inventories and one real PostgreSQL active-user catalog test. Added docs/learning-notes/node-registry.md and docs/real-backend-walkthrough.md; updated root/backend guides, API inventory, architecture/implementation plan and prior version-note crosslink. No workflow service/repository/model/dependency/lock/migration/private .env/frontend/dist/legacy-draft change. Revision stays 0002.

**Actual verification:** full checker **465 passed** with real isolated PostgreSQL; ordinary **321 passed, 144 skipped**. Added 74 ordinary cases and one integration case. Focused registry/config/API run passed 74. Ruff lint/format passed 90 Python files, Pyright zero errors/warnings, locked offline synchronization passed. Tests cover strict operations/scalar types/arity/array/text/number/reference bounds, extra/code-field rejection, static domain errors, absent capabilities, self-contained local JSON-Schema refs, response mutation isolation, changed-model revalidation, unchanged unfinished draft saves and Bearer/readiness/OpenAPI. Actual two-user discovery returns the same public contracts, current inactive user is rejected, and no workflows/versions are created by reads. Prior migration/drift/round-trip/auth/version immutability/rollback/concurrency cases remain green.

**Live HTTP:** real Uvicorn registration/login/Bearer catalog discovery, unauthenticated 401, six config schemas/handles with execution_ready false, no-store, incomplete/unsupported draft save compatibility, restart persistence of catalog/draft, OpenAPI inventory, key/password/token/config omission from logs, matching request IDs and graceful shutdown all passed. Database override targeted only a disposable migrated test schema, with a process-local key and explicit local HTTP cookie mode. No development data/configuration was involved. No new smoke-harness failure occurred.

**User-facing viewing guide:** documents root/backend directory-safe startup, required private database/JWT settings without reading .env, Swagger registration/login/Bearer flow, real version save/read/restart behavior, and full remaining roadmap. The React app still uses mockApi/mockOutput/browser persistence; starting the backend does not replace its demo dashboard values. Real run statistics, approval state, token usage and traces are not implemented resources yet. No seed or fabricated data was introduced.

**Cleanup:** zero random test schemas and zero public test tables remained. Temporary server/factory/scripts and owned test container were removed; development PostgreSQL remains running. Documentation formatting/relative links passed. No new development migration was needed.

**Limits:** no graph/upstream/permission validation, reference resolution, arithmetic execution, runtime input/output schemas, provider/agent/tool capability, activation/run, frontend API adapter or browser/deployment verification. Config models are internal building blocks; Phase 4D adds the owned validation endpoint/compiler. Phase 5 adds deterministic execution; later phases add workers, Groq Free Plan calls, agents, live telemetry, approvals and frontend integration. No percentage estimate or automation-completion claim.

**Exercise:** validate explicit calculator operands, replace a numeric literal with a numeric string, assert static failure, and confirm draft storage remains available. Use isolated fixtures; no solution supplied.

**Next increment:** Phase 4D, authoritative graph validation/compiler. First review question: why can a configuration be valid while execution_ready remains false?

## 2 November 2026 — Backend Phase 4D

**Implemented:** read-only POST /api/v1/workflows/{workflow_id}/validate and authoritative deterministic graph compilation. An explicit {} selects the current immutable snapshot; version_id selects exact owned history; definition validates an unsaved candidate. Selectors are exclusive, null/malformed/extra request input is safe 422. Missing/unowned/mismatched versions share generic 404. Versionless current returns 200 valid false/NO_SAVED_DEFINITION; archived snapshots remain inspectable without activation. Semantic failures return 200 valid false with static structural diagnostics, capped at 100 with truncation; valid reports include a bounded plan summary. Every outcome keeps execution_ready false. API count is 13 operations across ten paths.

**Compiler:** strict supported root/node/edge envelopes and six registry configs, unique bounded IDs, exact default/true/false output routes, one manual root, end terminals, explicit merge convergence, full reachability and no cycles/parallel fanout. Kahn/heap sorting gives canonical topological order, not an executed route. Dominator intersections reject references unavailable on some incoming path, including branch-local outputs after merges; only declared reference fields/input mappings are checked, not path-looking literals. Internal plans use frozen dataclasses, tuples and canonical config JSON strings, retaining no mutable input containers. Root metadata/labels/positions do not execute; unsupported semantic fields are rejected. Actual value resolution/field/type/math/result checks remain runtime work.

**Read-only/privacy:** active-user ownership and exact immutable snapshot selection occur inside a short read Session. Definition is copied and the Session closes before compilation. No status/timestamp/pointer/history write or validation flag is persisted; concurrent saves cannot substitute another snapshot. Reports omit raw configs, identifiers in diagnostics, validator messages and driver exceptions. Plan summaries include only authorized graph IDs/counts/order. Future runs must authorize/recompile the exact saved version; a previous validation report is not execution authorization. Draft saving remains permissive.

**Files:** added graph_schemas.py, validation_schemas.py, compiler.py and validation_service.py under modules/workflows; added node_output_handles accessor, validation route and app description. Added 59 compiler, 23 API and 13 integration cases in separate test files; exact inventories include the new route. Added docs/learning-notes/workflow-validation.md and updated guides, API inventory, architecture/implementation plan, real-data walkthrough and registry-note crosslink. No save-service/repository/database model/dependency/lock/migration/private .env/frontend/dist/legacy-draft changes. Revision stays 0002.

**Actual verification:** full backend checker **560 passed** with real PostgreSQL; ordinary **403 passed,157 skipped**. Added 82 ordinary and 13 integration cases (95 total). Ruff lint/format passed 97 Python files, Pyright zero errors/warnings, locked offline synchronization passed. Compiler/API/integration checks cover nested diamonds/early ends/same-target merge alternatives, degree/handle/ID/endpoint/cycle/unreachable refusal, strict configs, dominator availability versus sibling/self/future/missing outputs, literal path strings, immutable/permutation-stable plans, static secret-free capped reports, unchanged saved state, owner-first semantic privacy, exact historical membership, inactive-user denial, safe 503 recovery and current-pointer race pinning. Earlier migration/drift/round-trip/auth/immutable-trigger/CRUD/concurrency checks remain green. Independent read-only audit found no actionable bug; local 500-node valid-chain and 2000-edge invalid-graph probes passed within bounded diagnostics. These are not production benchmarks.

**Issues resolved during checks:** forward result annotation was postponed with future annotations before import tests; duplicate API/integration test basenames were corrected to the established API _contract suffix before final collection. These were implementation/test setup issues, not runtime security-policy changes. No test was skipped or weakened to pass.

**Live HTTP:** temporary real Uvicorn registration/login, current/candidate/history reports, 401/owner 404, invalid graph safe diagnostics, unchanged metadata/history, continued permissive save of unfinished version 2, valid historical version 1, same reports after restart, archived inspection, OpenAPI 13 operations/ten paths, no-store/request-ID correlation, private key/password/token/config omission from logs and graceful shutdown passed. Database alone targeted a disposable migrated local test schema, key process-local, explicit local HTTP cookies; no development data/configuration involved.

**Cleanup:** zero random test schemas and zero public test tables remained. Temporary server/factory/scripts and owned test container were removed; existing development PostgreSQL stays running. Documentation formatting/relative links passed. No new development migration needed.

**Limits:** no node execution, runtime output schema/key/type checks, activation/run, workers/provider/agent/approval capabilities, frontend API wiring or browser/deployment completion. Unsupported saved root extensions must move under metadata to compile; storing them still works. Validation is staged rather than exhaustive, and compiled ordering includes both alternative branches. Production query/transport/rate limits remain hardening work. No fabricated result, telemetry or model call was added.

**Exercise:** build nested exclusive branches with an early-terminal arm and calculator on the surviving route, predict an available reference and assert validation leaves saved state unchanged. Isolated fixtures only; no solution supplied.

**Next increment:** Phase 5A run/node-attempt/event persistence and legal state transitions, before the first controlled runner in 5B. First review question: why is an ancestor check insufficient for a reference after an exclusive merge?

## 3 November 2026 — Phase 5A: execution persistence and lifecycle guards

**Delivered:** additive migration 0003 and WorkflowRun/NodeRun/ExecutionEvent mappings, explicit run/attempt transition maps, bounded copied JSON objects and static failure codes. Runs retain exact immutable version identity and optional same-version parent lineage. Attempts retain numbered retry history; events retain a unique per-run cursor. ExecutionRepository uses owner-scoped refreshed row locks, expected revisions and caller-owned units of work to commit state/results/counters/events together. PostgreSQL guards enforce lifecycle/revision/identity/saved-node/result/context/retention rules without relying on connection search_path. Existing migrations remain unchanged; no new dependency was introduced.

**Verification:** complete backend checker **708 passed**, ordinary **500 passed/208 skipped**, Ruff lint/format clean for 108 files, Pyright zero errors/warnings and locked offline sync passed. Added 97 ordinary and 51 real PostgreSQL cases. Tested full transition matrices, JSON boundaries, ownership, frozen history, old failures/new attempts, wait/resume ABA revisions, refreshed cached state, transaction fault rollback/recovery, direct SQL guards, and three independent-connection races with bounded barriers/deadlines/distinct backend PIDs. Populated migration round trips preserve previous account/workflow/refresh rows and return no schema drift. A raw-SQL fixture initially addressed public instead of its isolated schema; schema-aware SQL expressions/qualified TRUNCATE corrected the test harness, retaining guard assertions.

**Process/development checks:** independent write/read Python processes verified persisted synthetic lifecycle state, version identity and ordered events after process exit, plus the unchanged 13-operation/ten-path OpenAPI inventory. This was fixture persistence, not real node execution or a new live Uvicorn test. A guard restricted the additive development upgrade to the documented localhost:15432/agentflow public schema; it reached 0003 head with no drift, retained all earlier record identifiers and inserted no execution fixtures. Test schemas/public test tables and temporary scripts were removed; only the owned postgres_test container was stopped/removed, development PostgreSQL retained. No private .env, frontend/dist or legacy-draft edits occurred.

**Concurrent contract edit:** the current auth schema had an 8-character registration minimum while older tests expected 15. Preserving that edit, registration boundary/redaction/OpenAPI tests and current guides now require 8–128; historical Phase 3A policy/results are retained with a current-contract note. No production auth code was changed for 5A.

**Limits/next:** no node executor, run HTTP route, actual automation result, SSE, checkpoint/lease/outbox/idempotency, cancellation/approval service or provider call yet. Reserved states and parent linkage are storage only. Raw privileged SQL does not automatically generate appropriate business events; callers must use the repository/UoW contract. The frontend remains mock-backed; execution_ready stays false. Next is **Phase 5B: controlled manual → transform → end execution and its scoped run API slice**. See [execution persistence learning notes](learning-notes/execution-persistence.md) for fields, function/transaction flow, results, limitations, one unsolved exercise and four review questions. First review question: why must a state change and its event commit together?

## 3 November 2026 — Phase 5B: first real pure-node execution and run APIs

**Delivered:** synchronous exact-version POST /api/v1/workflows/{workflow_id}/runs (201/Location/no-store) and owner-scoped GET /api/v1/runs/{run_id}. ExecutionService copies and compiles the owned immutable snapshot outside storage, restricts execution to manual/transform/end, and rechecks archive/ownership/version membership while creating a queued run. LinearRunner persists attempt starts/results/events in short units of work while pure computation holds no operation Session open. manual/end/identity copy input, pick_fields selects exact top-level fields, and explicit compiler bindings replace input through dictionary lookups only. Actual outputs/errors/timestamps/durations/version/attempt history are returned in typed public DTOs. Run end-result and succeeded transition commit together; failure stops downstream execution.

**Contract:** a created run can be failed, so callers inspect status/error_code rather than assuming 201 means successful computation. Missing selected fields produce EXECUTION_FAILED, unresolved/non-dictionary mappings INPUT_MAPPING_FAILED, unexpected pure executor exceptions INTERNAL_FAILURE; no raw exception messages are persisted. Failed mapping input is {} rather than a partial mapping. Unsupported/invalid saved graphs return safe 422 before run creation. Each POST creates a distinct run; Idempotency-Key is explicitly rejected pending 5D. A storage error rolls back the current transaction, preserves earlier history and returns safe 503 with Location when creation is known committed. Initial commit/response loss remains ambiguous. Synchronous 201 is the current contract; asynchronous 202 belongs to Phase 6.

**Readiness:** the registry's shared allowlist now marks manual/transform/end true with validate_config/execute capabilities; condition/calculator/merge remain validation-only/false. Graph validation returns readiness true only for compiled graphs entirely supported by current executors. This is capability information, not authorization, saved-version existence or a guarantee about runtime input. Current tests/docs reflect this intended contract change; historical learning-note results remain identified as historical.

**Files:** added executions/schemas.py, runner.py, service.py and api/v1/runs.py; updated execution exceptions, router/factory, registry and validation response/service. Added unit/test_pure_executor.py, api/test_run_contract.py and integration/test_run_execution.py, and updated exact route/catalog/readiness inventories. Added [first runner learning notes](learning-notes/first-runner.md), updated root/backend guides, API inventory, schema/architecture/plan, runnable real-data walkthrough and prior note crosslinks. No dependencies, migrations, private .env, frontend/dist, legacy drafts or auth production code changed. Password minimum remains the user-confirmed 8 characters; head remains 0003.

**Actual verification:** full backend checker **756 passed** against PostgreSQL; default checker **530 passed/226 skipped**. Ruff lint/format clean for 115 files, Pyright zero errors/warnings, locked offline synchronization passed. Added 30 ordinary and 18 database cases. Verified actual outputs and mapped/whole/nested references; copying, null/type/key preservation; static runtime failures with no downstream invocation; owner/version/inactive/archive boundaries; copied-snapshot/current-pointer races; actual worker-thread execution with no checked-out operation Session; independent concurrent POSTs; safe storage failures/recovery and rollback after flushed creation/result events. Conditional/calculator graphs validate but are correctly refused by the current runner. All prior migration/auth/compiler/state/rollback/concurrency checks remain green.

**Real HTTP/restart:** temporary Uvicorn registered/logged in, saved a three-node graph, computed actual field-selection output and persisted a real failed run. After stop/restart, GET returned identical version/attempt/result history for both. Verified 401/owner 404, ready types, 15 operations/12 paths, private correlated logs and two application-shutdown records. The temporary smoke harness initially expected exit 0 from SIGTERM; it now accepts normal signal termination while independently requiring shutdown logs. Only Database was overridden to a disposable migrated test schema; signing key was process-local and HTTP cookie mode explicit. No development data/private configuration was read or changed.

**Schema/cleanup:** guarded read-only inspection confirms local development revision 0003 head and no drift; no new migration/data writes were needed. Disposable schemas/public test tables and temporary servers/factories/scripts were cleaned up. Only the owned postgres_test container was stopped/removed; development PostgreSQL remains running. Documentation formatting/relative links passed.

**Limits/next:** condition/calculator/merge routing, run list/cancel/retry/events APIs, command idempotency, scheduled retries, worker leases/checkpoints/outbox/crash recovery, Groq/tools/agents, approvals/SSE and frontend integration remain pending. Storage failure/crash can leave queued/running history; no automatic replay or completion is claimed. Next is **Phase 5C: condition/calculator execution and exclusive-branch routing/merge**, with actual selected-path execution and explicit skipped-node semantics. The learning notes contain functions/transaction flow, an unsolved mapping exercise and four review questions. First question: why commit an attempt start before pure computation and close the transaction during computation?

## 3 November 2026 — Phase 5C: typed conditions/calculators and exclusive routing

**Delivered:** WorkflowRunner follows the selected CompiledRoute from the manual entry rather than executing every node in topological order. condition returns a boolean result selecting true/false; calculator returns a bounded numeric result; merge copies only the chosen predecessor output. Nested branches, early terminal arms, shared merges and two handles converging on the same merge are supported. At successful completion, unvisited nodes get actual pending-to-skipped history (input {}, output/error null, no start, duration 0, revision 1), committed atomically with the end result/run output/events. Selected-route failure still stops with actual failure history and no completion skips.

**Operation contract:** explicit compiled data/config bindings resolve separately from already executed dictionary outputs, with copied bounded JSON and no expression evaluation or path-looking literal interpolation. Equality compares scalar categories, distinguishing bool from number while allowing int/float numeric equality. Ordered comparisons require finite numbers; contains is bounded case-sensitive substring. Numbers/operands/intermediates/results remain within ±10^12 and comparison strings within 4096 characters. Division by zero, unsupported runtime types and overflow persist EXECUTION_FAILED; missing/non-dictionary reference traversal persists INPUT_MAPPING_FAILED. Division uses Python float, not a decimal currency engine. No unchosen runtime input/config is resolved or executed; whole-graph preflight validation still applies.

**Files:** added executions/operations.py for storage-free operations/reference/routing helpers; runner.py now defines WorkflowRunner with selected traversal, visited-output state and atomic final skip writes. Updated ExecutionService, shared readiness allowlist, named existing numeric/text bounds and OpenAPI route description. Added unit/test_branch_operations.py and integration/test_branch_execution.py; updated existing catalog/readiness and 5B executor wrappers to accept explicit resolved_config. Replaced the two former unsupported-condition/calculator refusal cases with real execution coverage; unsupported/invalid graph refusal remains tested. No compiler algorithm, models, migration, dependencies, auth, private .env, frontend/dist or legacy draft changes. Password minimum remains the user-confirmed 8 characters.

**Verification:** full PostgreSQL checker **845 passed**, default **598 passed/247 skipped**, Ruff lint/format clean for 118 files, Pyright zero errors/warnings and locked offline sync passed. Added 68 ordinary and 23 database cases (net +89 after replacing two obsolete refusals). The suite includes 85 pure-operation cases; focused branch/linear PostgreSQL checks passed 39 cases. Verified strict scalar equality/order/contains, literal versus reference resolution, numeric zero/overflow/bool/string/null failures, selected output/merge inputs, exact skipped fields/cursors, no unchosen runtime-invalid arm evaluation, nested/early/same-target paths, no checked-out operation Session during new executors, invalid post-merge branch-local references, immutable historical route results/archive, concurrent opposite-route independence, and rollback after a flushed skipped event. That injected storage failure retains the prior end start as running with no output/partial skips/run success; a new run can succeed after recovery. Earlier auth/compiler/migration/ownership/lifecycle/concurrency tests remain green.

**Real HTTP/restart:** temporary Uvicorn registered/logged in, saved a branching graph, computed 22 and 5 on opposite conditions and persisted the corresponding unchosen skipped attempts. Numeric-string input produced a persisted typed condition failure before either arm. After application shutdown/restart, GET returned identical version/results/attempt histories for both successes and the failure. Verified six ready catalog types, unchanged 15 operations/12 paths, 401, private request-correlated logs and two graceful application shutdowns. Only Database targeted a disposable migrated test schema, with process-local signing key and explicit local HTTP cookies. No development fixtures or private configuration access was used.

**Schema/docs/cleanup:** read-only local development inspection reports 0003 head and no metadata drift, without business data reads/writes. Existing skipped state/result checks and event types required no schema change. Added [branch execution learning notes](learning-notes/branch-execution.md) with full runnable JSON, exact operator/skip rules, function/transaction flow, results/limits, unsolved exercise and four review questions. Updated current guides/API/schema/architecture/plan/walkthrough and historical-note crosslinks; Markdown formatting/relative links passed. Test schemas/public test tables and temporary server/factory/scripts were cleaned up; only owned postgres_test was stopped/removed, leaving development PostgreSQL running.

**Limits/next:** no parallel scheduling, loops, retry/cancel/idempotency/list/events commands, worker dispatch/leases/checkpoints/outbox/recovery, provider calls, approval/SSE or frontend integration. Storage errors/crashes can retain queued/running history with no automatic replay. Existing run POST remains synchronous 201 and rejects Idempotency-Key; GET returns owned exact-version history. Next is **Phase 5D: execution command idempotency, bounded pure-node retry, cancellation and failure hardening**, with run discovery/listing designed within that baseline slice. First review question: why is executing every node in topological order incorrect for exclusive branches?

## 4 November 2026 — Initial frontend API integration

**Result:** brought initial Phase 11 auth/workflow/run adapters forward after backend 5C. The default app now uses actual accounts and PostgreSQL data. New accounts have empty workflows/runs. Added API session/client/DTOs, auth screens, shell, catalog-based graph editor, async immutable saves with retained 409 drafts, candidate validation, saved-version execution, actual history/totals and profile identity. Historical/archived views are read-only. Unsupported provider/approval/integration features are unavailable. Prototype pages/store/simulator remain unrouted; no fixture/localStorage migration occurs.

**Protocol:** access token stays in memory; HttpOnly refresh and readable CSRF cookies restore sessions. Web Locks serialize cross-tab auth and proof is read inside the lock. Refresh is single-flight, expired requests retry once, account generations fence stale results and prevent replay as another user. Broadcast notices contain no token. Network/503 mutations never automatically replay. Logout waits for backend success. Same-origin Vite dev/preview proxy preserves Origin; local default origins now include port 5173. Private .env was neither read nor changed. Registration minimum remains the user's chosen 8 characters.

**Backend:** GET /api/v1/runs now supplies owner-scoped, filtered/paginated summaries without business payloads. API inventory is 16 operations/13 paths. No schema/model/migration change: development head 0003, no drift. Current names and frozen version numbers are explicit; separate count/page queries can shift under concurrent writes. Added query/auth/OpenAPI/config contracts and PostgreSQL ownership/archive/storage-failure tests. Shared UI Button now renders one Radix Slot child and keeps loading/disabled controls inactive; screen tests caught the original defect.

**Checks:** 108 frontend tests (71 retained prototype + 37 new API/graph/rendering cases), ESLint, TypeScript, Vite production build and selected formatting pass. Backend checker: 858 passed with PostgreSQL; ordinary mode 607 passed/251 skipped; Ruff 119 files, Pyright zero errors/warnings. Locked uv sync passes. Development Alembic current/check are read-only and report 0003/no changes.

**HTTP:** bundled the actual frontend ApiClient and exercised it through real Vite preview → temporary Uvicorn → disposable migrated test schema. Verified registration/login/me, empty account, save and stale 409/request ID, validation, both arithmetic branch outputs/skips, owned listing/detail, restored cookie session and serialized rotations, logout, second-account isolation and identical saved run history across API restart. Built assets served without prototype workspace markers. Correlated logs, no key/password/token leakage and API shutdown passed. The smoke harness initially rejected Vite's normal SIGTERM status 143; correcting that assertion completed all checks. Temporary processes/schema/files were removed. Only the owned test database service was stopped/removed; development PostgreSQL remains running. No development records were inserted or altered.

**Limits:** browser access host is unavailable, so visual/responsive/canvas/browser-cookie E2E remains outstanding. SSR/component tests and HTTP proxy checks do not establish browser interaction behavior. No provider call, worker, deployment, approval or SSE completion is claimed. Groq remains planned. Backend 5D (idempotency, bounded pure-node retries, cancellation/failure hardening) is next; future integration still needs live events/approvals, richer aggregate/profile contracts and browser/deployment verification. See [frontend API learning notes](learning-notes/frontend-api.md) for files, flow, exercise and review questions.

## 4 November 2026 — Login cookie-mode selection

Investigated a frontend cookie error after backend login 200 at localhost:5173. Found and fixed deterministic first-cookie selection when legacy Secure and local-development CSRF cookies coexist. Login/rotation now require an exact readable response-proof match and retain its cookie name for subsequent auth operations. Fresh bootstrap does not guess across conflicting modes; same-name conflicts still fail closed. No bypass of CSRF checks or backend/private .env changes.

Added six regressions for both cookie modes/orders, mixed bootstrap and same-name conflicts. Frontend now passes 114 tests, lint, TypeScript, production build and selected formatting. Backend is unchanged, so its previously passing 858 tests were not repeated. Added targeted local-cookie troubleshooting to the startup guide. Browser cause is not proven solely by the user's 200 log; retry and blocked-cookie metadata can distinguish delivery settings from the fixed selection issue. Visual browser QA remains outstanding.

## 4 November 2026 — Backend Phase 5D and execution command UI

**Implemented:** owner-scoped Idempotency-Key receipts committed atomically with run creation/events, canonical request matching and safe 409 conflicts, repeat lookup without another runner, bounded 1–3 attempts for explicitly pure internal/deadline failures, retained failed attempt history, full original-version/input retry with parent lineage, and cooperative atomic cancellation. New POST cancel/retry routes bring inventory to 18 operations/15 paths. Cancellation/result writers share a run lock; already-running pure computation may finish but cannot overwrite committed cancellation. No worker/backoff/deadline scheduler/provider/approval/SSE is added.

**Files:** execution command hashing module, service/runner/repository/model/schema/API changes, additive Alembic 0004, new policy/concurrency/migration tests and contract inventory updates. Frontend editor now selects a budget and retains an unresolved command key; execution details show eligible commands, parent and budget. Keyed failures can be explicitly resubmitted in that editor without creating another run. Keys remain memory-only; reload requires history inspection. Retry is the complete original graph, not partial resumption.

**Checks:** 905 backend tests pass against real PostgreSQL (638 ordinary/267 integration); ordinary checker separately confirms 638 passed/267 skipped. Ruff lint/format 124 files and Pyright zero errors/warnings. Added 47 regressions for strict contracts, canonical fingerprints, owner/key/workflow scope, simultaneous first creation, concurrent replay, atomic receipt rollback, transient recovery/exhaustion, deterministic non-retry, cancellation success/error races and rollback, immutable SQL/ownership guards, populated additive migration preservation and disposable downgrade/re-upgrade. Fixed migration test-fixture column/binding errors before final green checks. Frontend 120 tests, ESLint, TypeScript and production build pass; new render cases verify commands across six run states. SSR text assertions normalize React's comment separators.

**HTTP and migration:** temporary real Uvicorn with a random migrated test schema verified real auth, run creation/replay/conflict, full retry lineage, cancellation of an explicitly seeded queued storage fixture, same receipts/history/session after server restart, current OpenAPI inventory, request correlation, secret/key/body privacy and graceful shutdown. Concurrent running cancellation is verified through actual PostgreSQL-backed ASGI routes with controlled executor barriers. The smoke harness counts application lifecycle JSON separately from Uvicorn's shutdown notices. Applied tested additive 0004 only to guarded local Compose development storage; no metadata drift, all pre-existing table row counts retained. No account/workflow/run fixtures were inserted into development. Private .env unchanged; no dependency/lock changes.

**Limits and cleanup:** no browser visual/E2E completion; browser host remains unavailable. Automatic attempts are immediate, at most three, with no elapsed deadline enforcement or database-write retry. Receipts have no expiry; they identify existing runs without resuming queued/running work stranded by process/storage failure. No exactly-once or external-effect rollback claim. Temporary smoke processes, files and schemas were removed; test DB inspected empty before stopping/removing only the owned test service. Development PostgreSQL remains healthy. See [execution command notes](learning-notes/execution-commands.md) for flow, contracts, exercise and review questions. Next: Phase 6, reliable dispatch/outbox/claims/leases/recovery; Groq remains Phase 7.

## 4 November 2026 — Phase 6A Redis/Celery transport

Implemented optional Redis configuration and a separate Celery worker for a payload-free transport probe. API workflow execution stays synchronous; no workflow task, migration or public endpoint was added. The broker is optional for API startup and uses an explicit validated URL for worker/probe processes. Local development and isolated test Redis services bind to loopback. JSON-only task policy, no result backend, bounded publisher connection failures and unvalidated Celery environment override rejection protect the transport boundary. Production settings require TLS and a password; deployment TLS remains untested.

Added Celery 5.6.3 with its Redis dependencies to the backend lockfile. Full checks: 935 passed with isolated PostgreSQL and Redis; ordinary 665 passed/270 skipped. Ruff 131 files and Pyright clean. Frontend 120 tests, lint and production build passed. Real subprocess tests verified worker startup, random-ID probe delivery without business data, graceful shutdown, broker failure/exit status and privacy. A worker-controller exit code fixed a Celery Python CLI wrapper issue observed during testing. API health remained available with an unreachable broker. Development migration remains 0004 with no drift; private .env was not changed.

PostgreSQL test schemas and public tables were empty afterward. The Redis test database retained seven broker bookkeeping keys after per-queue cleanup; removal of the disposable Redis test container discarded these, without FLUSHDB or changing development data. Both isolated test services were stopped and removed; development PostgreSQL remains healthy. No workflow delivery, durable dispatch, worker recovery or Groq call is claimed. See [worker transport notes](learning-notes/worker-transport.md). Next is 6B transactional outbox/dispatcher; 6C–6D add claims/recovery and retry scheduling, then Phase 7 integrates a free Groq model.

## 4 November 2026 — Phase 6B outbox foundation

Added migration 0005 and a PostgreSQL transactional outbox for payload-free transport probes. The caller controls the transaction; bounded SKIP LOCKED claims use database-time leases and unique tokens. Dispatch publishes outside the transaction and only a current unexpired lease can mark/release a row. Broker errors retain intents; loss after broker acceptance may publish a duplicate. Outbox history is retained. Separate CLI commands enqueue/dispatch probes and a real Celery worker consumes only opaque UUIDs.

Workflow runs remain synchronous and are not yet written to the outbox. Connecting them safely requires worker claims, fencing and recovery in 6C; no asynchronous workflow completion or exactly-once delivery is claimed. No Groq/provider call was made.

Verification: 947 backend tests passed with isolated PostgreSQL and Redis; Ruff 140 files/Pyright clean. Ordinary checks earlier passed 665 and skipped 281 before adding the final migration regression. Tests cover rollback, broker failure, concurrent claims, expired lease fencing, crash-after-publish duplicates, actual PostgreSQL/Redis/worker probe delivery and populated migration upgrade/downgrade and SQL guards. Development 0005 was applied only to the guarded local Compose database, with no metadata drift, unchanged existing table row counts and no probe insertion. The frontend remains unchanged; prior checks passed 120 tests. See [outbox notes](learning-notes/transactional-outbox.md).

## 4 November 2026 — Phase 6C queued-run claim groundwork

Added migration 0006 and internal queued-run claim repository. PostgreSQL run-row locking serializes acquisition, and renewable database-time leases have unique tokens and monotonic generations. assert_current holds the run lock for callers to fence state writes in the same transaction; expiry, replacement and cancellation invalidate old claims. A running run is intentionally not reclaimed because the current runner does not persist resumable progress. No outbox workflow intent or worker execution is wired; synchronous API behavior is unchanged.

Checks: full backend checker passed 958 PostgreSQL/Redis tests before adding the populated migration regression; that regression and claim tests then passed separately (12 tests). Ruff/Pyright pass. Tests cover concurrent acquisition, expired takeover, stale fences, renewal/release, cancellation, rollback, SQL history guards and fenced run transition. Migration 0006 was applied to the guarded local development DB, with existing table counts preserved, no new claims and no schema drift. Frontend and private .env are unchanged. See [claim notes](learning-notes/run-claims.md).

Still required: persist resumable progress and interrupted-attempt semantics; enforce fencing in all worker mutations; atomically enqueue workflow intent with run creation; implement worker recovery/renewal and process-kill/duplicate tests; then switch API to asynchronous dispatch, add scheduled retries and integrate Groq in Phase 7.

## 4 November 2026 — Project agent guide and recovery reconstruction

Added root AGENTS.md with active project layout, private configuration and ownership conventions, real-data boundaries, guarded PostgreSQL/Redis test commands, migration policy and Groq free-plan direction. It does not request extra approvals for routine development.

Added read-only recovery reconstruction that walks the compiled exact-version selected path using persisted successful attempt outputs and condition decisions. It preserves bounded business JSON, identifies ready/interrupted/failed/completed state, and rejects invalid attempts, unselected execution, bad ordering and incomplete completed history. It does not execute nodes, write checkpoints, claim or authorize runs, or enable worker recovery. A future caller must acquire a coherent owner-authorized run/attempt snapshot while holding the run lock and perform subsequent worker writes with claim fencing.

Unit tests cover both branch choices, retries, skipped nodes, case fidelity and inconsistent history; two real PostgreSQL tests run both branch paths and reconstruct actual persisted attempt history. No migration, frontend or private .env change. The synchronous API remains active. Persisted progress integration, interrupted-attempt reconciliation, worker fencing on every write, outbox workflow intents, process-kill/duplicate tests, scheduled retries and Groq remain to be developed.

Verification for this increment: full backend checker passed 974 tests with isolated PostgreSQL and Redis; ordinary checks passed 678 and skipped 294 before the two new database tests. Ruff checked 149 files and Pyright reported zero errors. Existing development migration remains 0006, with no metadata drift. Frontend/browser checks were not repeated because frontend behavior did not change.

## 4 November 2026 — Recovery snapshot and required keys

Added read-only claim-fenced, owner-scoped recovery snapshot loading. The run row is locked while validating claim and copying the immutable exact version, bounded input and chronological attempts. Compilation/reconstruction happen after the lock and accept only explicitly pure retry-safe node types. Snapshot output is advisory; every subsequent state write must recheck the current lease under the run lock. Queued inconsistent histories and running/completed contradictions fail closed. No worker execution, recovery, migration, frontend change or provider call was added.

Isolated PostgreSQL tests cover owner boundary, expiration/takeover/cancellation, committed progress, detached copies, immutable version selection, invalid graphs, lock release before compilation and cancellation after snapshot. Groq key documentation now explains that current code does not read a provider key; only a private JWT signing secret and database URL are needed for existing account/workflow features. Optional Redis is a broker URL. Groq free-plan integration and its exact environment variable remain Phase 7.

Verification: full backend checker passed 982 tests with isolated PostgreSQL and Redis; ordinary checks passed 678 with 304 integration cases skipped. Ruff checked 151 files and Pyright reported zero errors. The refined nonblocking run-lock test passed separately. No frontend or private configuration changes.

## 4 November 2026 — Claim-fenced worker state groundwork

Added an internal `WorkerState` layer that checks owner and current claim under the run-row lock in each mutation transaction. It provides fenced run transitions, atomic attempt creation/start, attempt success/failure and atomic terminal attempt/run failure. Real PostgreSQL tests cover owner isolation, expired and replaced claims, cancellation versus late results, event-write rollback and lock ordering. It is not connected to the synchronous runner or Celery worker; fenced branch completion, interrupted attempts, expired running-run recovery and outbox job wiring remain unfinished. No database migration, frontend change, private configuration read or provider call was made.

Full backend checks passed 988 tests with isolated PostgreSQL/Redis; an additional replaced-generation test passed separately along with the six existing worker-state tests. Ordinary checks passed 678 and skipped 310 before that additional case. Ruff checked 153 files and Pyright reported zero errors/warnings. The user's preferred Groq model is `openai/gpt-oss-120b` and they have selected `GROQ_API_KEY`; the backend does not read the key yet. The Groq adapter will be implemented later and model access/free limits verified then.

## 6 November 2026 — Internal pure worker execution and recovery

Added `PureWorkerRunner`, connecting the existing snapshot, selected-route
reconstruction and fenced worker state to actual pure-node computation. It
authorizes the run owner, validates the entire immutable saved version and refuses
any graph containing Groq, including an unselected branch. A separate internal
claim operation permits takeover of previously claimed running work after lease
expiry; the existing queued-only operation is unchanged. Unclaimed synchronous
running requests cannot be taken over.

Successful outputs and condition choices are reused. Interrupted pending/running
attempts retain their identities, become `INTERNAL_FAILURE` and consume their
original slot in the saved 1–3 attempt budget. Only internal/deadline failures can
produce a fresh attempt. Exhaustion and deterministic failures terminate the run
atomically with its failure event. Claims renew between nodes, every write is
owner/lease/generation fenced, and actual node execution holds no transaction.
Completion uses the existing atomic end/skipped-branch/run operation. Storage and
claim-loss exceptions stop further writes.

Verification: targeted runner/state/claim checks passed 46 tests. The complete
backend checker then passed **1048 tests with isolated PostgreSQL and Redis**;
Ruff lint/format passed 164 files and Pyright reported zero errors/warnings. New
tests cover both branch results, case-sensitive business keys, pinned versions,
ownership, retry budgets, deterministic failures, duplicate execution, stale lease
results, cancellation and rollback. A real child process is killed with SIGKILL
during a calculator node; recovery preserves committed upstream attempts and
records a new selected-node attempt. All test records use disposable migrated
schemas. No development records, private `.env`, migrations or frontend changed;
no provider call or browser verification was performed.

Public run POST remains synchronous. Workflow outbox creation, a workflow task
consumer, automatic expired-work discovery, lease heartbeat during long computation
and scheduled retries remain next. The new runner is internal and must not be used
to scan arbitrary queued API runs. No exactly-once or external-effect recovery
claim is made. See [pure worker recovery](learning-notes/pure-worker-runner.md).

## 6 November 2026 — Queued workflow dispatch, heartbeat and automatic recovery

Connected the pure runner to opt-in background API commands, retained outbox
delivery and a real Celery consumer. New pure create/retry commands return 202 with
`execution_mode: background`; default mode and any graph containing Groq remain
synchronous. Idempotent replay retains the original mode after configuration
changes. Run/event/receipt/worker provenance/initial intent commit together without
an API broker call. Redis carries only the outbox UUID; the consumer resolves the
target and active owner from PostgreSQL and revalidates the exact pure version.

Migration 0007 adds retained `workflow_dispatches` provenance and redispatch timing,
an outbox workflow target FK and kind/target/pending uniqueness guards. Published
rows cannot be reset or retargeted. Existing synchronous history and probes are
preserved. Downgrade refuses retained workflow dispatch history. The dispatcher
loop skips live claims and terminal/synchronous work, rechecks leases under the run
lock and inserts a new intent after abandoned work becomes eligible. Heartbeat
renewal uses separate short sessions and bounded statement timeouts during pure
computation; every result still uses the owner/token/generation/lease fence.

Execution details poll every 1.5 seconds while active, explain queued/running state
and show execution mode. Terminal results refresh run summaries. The browser
walkthrough explains how to enable background admission and start the worker and
dispatcher without modifying the private file.

Verification: the complete backend checker passed **1073 tests** with isolated
PostgreSQL and Redis, Ruff lint/format checked 172 files and Pyright reported zero
errors/warnings. The 25 added cases include atomic receipt failure rollback, 202,
replay across mode changes, owner isolation, cancellation/retry lineage, broker
outage, concurrent recovery scans, provenance/history constraints and a computation
lasting longer than its original lease. A real API → Redis → Celery test checks
opaque message contents, actual output and duplicate delivery. A second kills a
real worker mid-transform and verifies a fresh worker plus dispatcher loop recover
after natural lease expiry without editing test leases/clocks. Frontend **121
tests**, ESLint, TypeScript and production build pass.

Applied the tested additive 0007 migration only after guarding the configured local
development database identity. Existing table row counts were unchanged and
Alembic reports no metadata drift. No account/workflow/run fixtures were inserted
in development, no provider call was made and private `.env` was unchanged. Test
schemas and public tables were empty after verification. Browser automation was
attempted but the browser access host is unavailable; no visual/browser E2E claim
is made. Only test services started for the task are stopped afterward.

Background mode defaults off. Scheduled node-attempt backoff, SSE, provider/external
side-effect reconciliation, production supervision and load testing remain later
work. Duplicate publication and pure computation remain possible. See [background
execution and browser test steps](learning-notes/background-execution.md).

## 6 November 2026 — Phase 6D scheduled pure-node retries

Background pure-node retries now persist an immutable deadline and release their
claim instead of immediately looping inside a worker. New background runs freeze
the base/max delay from API settings into their dispatch record. Defaults are five
seconds then ten seconds for a three-attempt budget; only internal/deadline failures
are eligible. Synchronous pure retries keep their previous behavior and Groq graphs
remain outside automatic retry/recovery.

Migration 0008 adds retained `node_retries`, bounded immutable dispatch-policy
columns and the attempt-bound `node.retry_scheduled` event. Actual failure,
schedule/event, dispatch wake and release commit together. Both dispatcher and
claim acquisition enforce due times. Resume resolution commits with the new
attempt; cancellation atomically resolves the pending retry. Retry deadlines and
past resolutions cannot be overwritten, and downgrade refuses retry history.
Existing run/version/attempt identifiers and command fingerprints are preserved.

Owned run detail responses expose the pending node, next attempt and retry time,
plus each attempt's scheduled/resumed/cancelled metadata. The UI explains the wait
and retains the failed attempt. A run stays running during its wait, remains
cancellable and continues to poll for results. Optional retry settings require no
private `.env` changes.

Verification: **1100 backend tests** passed with isolated PostgreSQL/Redis; Ruff
lint/format checked 178 files and Pyright reported zero errors/warnings. Frontend
**122 tests**, ESLint, TypeScript and production build passed. Tests verify no early
claim/duplicate delivery, exponential delay and cap, policy/deadline/history guards,
budget exhaustion, deterministic non-retry, cancellation races, and rollback of
failure/scheduling/release or resume/new attempt on event-write failures. A real
solo worker schedules a retry and processes another workflow while it waits;
after stopping it, a fresh worker and dispatcher resume at the unchanged deadline.
The real worker-kill case also passes through the persisted recovery retry. A
populated migration fixture initially used an invalid inline JSON SQL binding;
parameterizing its JSON fixed it before the full green check.

Applied 0008 only through the guarded local development target: prior table row
counts were preserved and Alembic reports no metadata drift. No development
fixtures, provider calls or private configuration edits were made. Browser access
was attempted but its host is unavailable, so visual/browser E2E is not claimed.
Test cleanup is confined to the disposable services started for this task.

SSE, provider/external-effect reconciliation, jitter, elapsed execution deadlines,
load testing and production supervision remain separate work. See [scheduled retry
notes](learning-notes/scheduled-retries.md) for policy, transactions and browser
behavior.

## 6 November 2026 — Phase 7E protected HTTP connections

Implemented owner-scoped connection create/list/get/revoke, optional authenticated
encryption bound to owner/connection identity, immutable endpoint history and
credential removal on revocation. Additive migration 0009 extends failure-code
constraints and refuses downgrading retained connection/HTTP failure history.
Cryptography 50.0.2 and the existing HTTPCore 1.0.9 are direct locked dependencies.

HTTP GET nodes use fixed owned public HTTPS endpoints with numeric DNS address
pinning, TLS hostname verification, no redirects/proxies, bounded JSON responses
and static failure codes. Calls own no database transaction and have no automatic
retry/recovery. Integrations manages real connections; the editor selects IDs and
execution details exclude HTTP graphs from whole-workflow retry. Generation cannot
invent IDs; edit proposals may preserve existing bindings.

Verification: full backend checker **1203 passed** using disposable PostgreSQL and
Redis, Ruff lint/format (194 files) and Pyright clean. Frontend **130 passed**, lint,
TypeScript and production build clean. Coverage includes ownership, revocation,
encryption/tampering, DNS rebinding/private answers, unsafe URLs, response bounds,
echoed credentials, command replay, no held transaction, timeouts without replay,
cancellation during a call and populated migration round trips.

No private runtime configuration, development data or applied migration was
changed. Browser access was attempted and its host is unavailable; network
responses are stubbed, so no live HTTP/provider result is claimed. DNS resolution
uses OS resolver timeouts. Removed only the Redis test service started for this
task; pre-existing PostgreSQL services were retained. See
[HTTP connection notes](learning-notes/secure-http-connections.md) for setup,
limitations, request flow and the next increment.

## Provider hardening and authorized generation continuation

Implemented safe provider-specific error outcomes, sanitized quota wait guidance,
bounded streaming response reads, actual response model/usage metadata and explicit
truncation failures. Migration 0010 expands failure-code constraints and refuses a
lossy downgrade of retained provider outcomes. Usage metadata shares the immutable
node-status event transaction; workflow business output keys stay unchanged.

Generation/edit requests now accept explicit selected connection IDs. The server
reads only owned active metadata columns, validates before/after the provider call,
and rejects model-invented or unselected IDs. Edits also authorize saved bindings.
The UI discloses metadata sharing, starts new-workflow selection empty, shows
authorized endpoints for review, and distinguishes unknown usage from reported zero.
Quota errors do not log out the user or automatically resubmit requests.

Offline PostgreSQL checks verified ownership, revoked/missing/unselected bindings,
revocation during generation, read-only edits and immutable provider event history.
Live public HTTP and configured Groq completion passed. Initial live generation
attempts failed or returned an unexpected result; fixing the missing canonical
HTTP type and adding a registry-derived type list plus authorized example produced
a valid live proposal without repair. A guarded temporary PostgreSQL schema then
verified the complete live API create/generate/save/run/replay/revoke flow with
one actual HTTP request; the schema was removed afterward. No private business data
was used. Browser access was retried and remains unavailable.

See [provider/integration contracts and limits](learning-notes/provider-integration-hardening.md).

Final verification: **1254 backend tests passed** with disposable PostgreSQL/Redis,
Ruff lint/format (200 files) and zero Pyright errors/warnings. Frontend **133 tests**,
lint, TypeScript and production build passed. Stopped/removed only the Redis test
service started for this task, retaining the pre-existing PostgreSQL services.
Private `.env`, development database and applied migration revisions were preserved.

## 10 November 2026 — Phase 7 closeout and Phase 8A calculator agent

**Implemented:** consolidated the current plan/verification/walkthrough status; removed the broad docs/tests Git exclusions; applied additive development migration 0010 and verified head/no metadata drift. Added an executable synchronous `agent` registry/config contract, typed LangGraph model/calculator loop, strict shared bounded arithmetic, cancellation checks between steps, finite turn/deadline budgets, explicit stop reasons and immutable per-call provider usage/history. The active editor supplies a valid starter configuration and disclosure; run details show agent metadata and exclude full-workflow retry for agent graphs. Generation can propose the supported calculator agent for review without executing it.

**Ownership and transaction flow:** agent internals live in `app/modules/agents/`. The existing execution service authorizes the owner/saved version and commits attempt state around external computation. No database transaction is held across a provider or calculator call. Result and validated operational metadata share one terminal event transaction; stale/cancelled output cannot replace committed cancellation. Agent graphs remain outside automatic retries, background dispatch and recovery.

**Dependencies:** locked LangGraph 1.2.20 and explicitly declared its already-installed LangSmith dependency for the local tracing-disable context. Provider selection remains the configured Groq model/key with no paid fallback or automatic provider retry. Implicit LangSmith export is disabled for invocation. No agent table, checkpoint saver or new migration is introduced; source/development head stays 0010.

**Verification:** deterministic transport tests exercise the actual graph and tool-result conversation. Isolated PostgreSQL/API tests prove owner denial, explicit synchronous execution, idempotent replay, usage persistence, cancellation and atomic rollback. An old integration catalog assertion was updated for the twelfth executable node type. Final full checks passed **1,301 backend tests**, Ruff lint/format (205 files) and Pyright; frontend checks passed **135 tests**, lint, TypeScript and production build. Commands and acceptance limits are recorded in [verification](verification.md). Private-value scanning found no configured credentials in candidate source/docs/tests; the existing private `.env` remains ignored and unchanged.

**Limits:** browser discovery returned an unavailable access host; browser/visual acceptance remains pending. No live Groq call was made for this increment. A model answer can be inaccurate; inspect actual calculator results. Failed attempts retain counts/stop/usage metadata rather than durable intermediate tool checkpoints. No automatic crash resume, HTTP agent tool or external-effect reconciliation is claimed.

**Next:** 8B authorized HTTP agent tool, then 8C persistent checkpoint correlation/recovery. See the [calculator-agent guide](learning-notes/calculator-agent.md) for a runnable graph, exact bounds and exercise.

## 10 November 2026 — Groq connection timeout correction

The live Version 2 calculator run and a simple Integrations completion both timed out at the configured 45-second boundary. Public endpoint probes showed IPv4 responding in about 0.3 seconds while the IPv6 route stalled; HTTPX with a five-second connect timeout reached the same endpoint after fallback. The shared provider adapter previously allowed a connection attempt to consume the entire response deadline.

Capped connect timeouts at five seconds or the smaller remaining request budget, preserving the configured response timeouts, TLS validation, direct transport, no redirects and no automatic provider retry. Added regression coverage for a stalled first address exhausting the old overall deadline, short configured budgets and the agent's smaller remaining budget. No private environment setting, model selection, workflow data, schema or frontend was changed.

Verification: standard checker **888 passed/416 integration cases skipped**, Ruff lint/format (205 files) and Pyright clean; targeted provider/agent tests **79 passed**. One synthetic live Groq completion and a live calculator-agent invocation passed. The agent made one actual calculator call and two provider requests in 11.17 seconds. No database writes or business data were used. The earlier 1,301-test PostgreSQL/Redis suite remains the Phase 8A baseline; it was not repeated for this transport-only patch. Restart the API before trying a fresh editor run if reload is not enabled.

## 10 November 2026 — Phase 8B authorized HTTP agent tools

**Implemented:** the existing `agent` type is now displayed as Tool Agent. A saved strict `connection_ids` allowlist grants up to ten owned active fixed-endpoint HTTP GET connections; empty/omitted configuration retains the calculator-only agent. `agents/http_tools.py` binds connection access to the authenticated owner. The typed LangGraph loop exposes only a code-owned selected-ID schema, rejects arbitrary URL/headers/body, rechecks grants before each model turn and immediately before fetching, and refuses repeated endpoint fetches even through connection aliases. Calculator/HTTP share the existing finite round/deadline budget. Agent responses and conversation growth are bounded. No dependency, schema or migration was added; head stays 0010.

**Request and history flow:** metadata lookup does not decrypt credentials. Authorization closes storage before decryption/network; no transaction spans external calls. Selected endpoint metadata and fetched JSON go to Groq with explicit UI disclosure; credentials stay server-side. Successful output preserves actual business JSON and calculator entries, adding HTTP tool results. Bounded attempt metadata records HTTP tool attempts, selected connection status/error, static failure reason and each provider request; it commits atomically with terminal attempt state. Old stored events decode with defaults, without rewriting history. Agent-aware proposal generation/editing accepts only explicitly approved connection IDs and never executes tools.

**Active frontend and sample:** the editor has an explicit multi-connection agent picker, including removal of missing/revoked IDs. Integrations and proposal review explain data sharing; execution details show actual HTTP/tool/provider summaries. The [HTTP agent guide](learning-notes/http-agent.md) supplies [workflow JSON](examples/http-agent.workflow.json), [input](examples/http-agent.input.json), expected tool history, revocation and calculator compatibility checks.

**Live finding:** the first live sample stopped on an HTTP connect timeout because DNS listed unusable IPv6 routes first. The controlled executor now validates every DNS answer, prefers IPv4 and permits TCP address fallback within the operation deadline before sending a request. TLS/HTTP is never retried; public destination pinning and mixed/private-address rejection remain. Four regression tests cover preference, fallback before one GET, exhausted addresses and the shared deadline. The earlier five-second Groq connect-timeout correction is included in the final full verification.

**Verification:** **1,351 backend tests** passed with isolated PostgreSQL/Redis, Ruff lint/format (208 files) and Pyright; **137 frontend tests**, lint, TypeScript and production build passed. The live API sample then succeeded with one actual HTTP request, three Groq requests, two fetched slides and actual calculator result **20** in **18.81 seconds**. Command replay retained identical history with no extra calls; revocation blocked a fresh run before HTTP/Groq. Synthetic fixtures used only a random guarded test schema, removed afterward. Only the task-started Redis test service was removed; pre-existing PostgreSQL and development data were preserved. Private-value scanning found no newly introduced configured secrets; the private `.env` remains ignored and unmodified.

**Limits and next:** browser discovery was retried and its access host remains unavailable; UI click-through/layout acceptance is pending. Model tool selection/content is not guaranteed by one live pass. HTTP/agent graphs stay synchronous with no automatic retry, background recovery or durable intermediate checkpoints. A cancellation/crash can leave an issued request's outcome unknown. Review the sample before **8C**, persistent checkpoint correlation/recovery; it must preserve external-call reconciliation boundaries.

## 23 November 2026 — Owner approvals for pure background workflows

Added migration 0014, strict owner-approval configuration, retained requests/decisions, review/list APIs, approval UI and branch routing. The worker atomically records waiting state and releases its claim. Decisions, expiry and cancellation serialize on the run lock; an authorized winning decision commits its result/events and resume outbox intent together. A new worker reconstructs committed progress from the exact saved version. Identical decision/note replay returns the retained decision; conflicts return 409. Expired/cancelled requests cannot revive a run.

Scope: pure background graphs only. External-call approval graphs and AI-generated approval edits are rejected explicitly. Gmail consent/live verification remains outstanding; browser discovery still reports an unavailable host. The user is configuring OAuth credentials privately. No external provider was called and no development data or private configuration was changed by the agent.

Verification: 1,416 backend tests passed with isolated PostgreSQL/Redis, including actual worker/dispatcher restart around approval and release of worker capacity while waiting. Frontend: 187 tests, lint and production build passed; backend Ruff lint/Pyright and changed-file formatting passed. The standard combined checker remains blocked by the existing formatting issue in applied migration 0013, which was preserved. Only the task-started disposable test services were stopped/removed. See [verification](verification.md) and [approval setup](learning-notes/approvals.md).
