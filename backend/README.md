# AgentFlow backend

Phase 6D adds persisted exponential retry delays for background pure-node failures.
Migration head is 0008. Retry policy is frozen per run; eligible attempts release
the worker until due, with cancellation and immutable retry history. Synchronous
pure retries remain immediate; Groq remains excluded. See [scheduled retry notes](../docs/learning-notes/scheduled-retries.md).
The phase snapshots below describe earlier increments.

Phase 6C now supports opt-in queued pure workflows: atomic run/receipt/outbox
creation, opaque-ID Celery delivery, fenced worker execution, heartbeat and automatic
recovery discovery. Migration head is 0007. Enable
`AGENTFLOW_BACKGROUND_EXECUTION_ENABLED=true` with the worker and dispatcher
running; Groq graphs remain synchronous. See [startup, contracts and browser checks](../docs/learning-notes/background-execution.md).
The phase snapshots below record earlier increments.

Phase 6C, 6 November 2026: an internal pure worker runner now executes queued runs
and recovers previously claimed running runs after lease expiry. It reuses committed
outputs, reconciles interrupted attempts within the saved budget, renews leases
between nodes and fences every write. Groq graphs and unclaimed synchronous running
runs are refused. Workflow tasks/outbox dispatch, automatic recovery scheduling and
asynchronous API responses remain next. See [pure worker recovery](../docs/learning-notes/pure-worker-runner.md).
Earlier Phase 6C notices below are historical.

The authenticated Groq connection, workflow node and new-workflow generator use `GROQ_API_KEY` from `backend/.env` and default to `openai/gpt-oss-120b`; see the [walkthrough](../docs/real-backend-walkthrough.md#generate-a-workflow-from-a-prompt). Generation returns a validated proposal for review and does not save or execute it.

Phase 6C groundwork adds queued-run claim leases and fencing primitives. Workflow execution remains synchronous; persisted progress, worker recovery, workflow outbox integration and asynchronous dispatch are not yet implemented. See [claim notes](../docs/learning-notes/run-claims.md). Prior phase descriptions below are historical.

Phase 6B foundation: migration 0005 adds a durable outbox and leased dispatcher for transport probes. Workflow runs remain synchronous; worker claims/recovery and workflow dispatch remain next. See [outbox notes](../docs/learning-notes/transactional-outbox.md). Earlier phase descriptions below are historical.

Phase 6A, 4 November 2026: optional Redis/Celery transport and separate payload-free probe worker are implemented and verified. Workflow run POST remains synchronous. Full isolated PostgreSQL/Redis checks: 935 passed; ordinary: 665 passed/270 skipped; Ruff 131 files/Pyright clean. Migration head remains 0004. See [worker transport notes](../docs/learning-notes/worker-transport.md) for startup, tests, limitations and the Groq roadmap. Prior phase counts below are historical.

Current Phase 5D verification (4 November 2026): **905 backend tests** with PostgreSQL, ordinary **638 passed/267 skipped**, Ruff **124 files**, Pyright clean; frontend **120 tests**, lint/TypeScript/build pass. Migration **0004** is applied to the local development database with no metadata drift and existing row counts preserved. API **18 operations/15 paths**. Earlier phase-specific counts below remain historical. See [execution command notes](../docs/learning-notes/execution-commands.md) and the [walkthrough](../docs/real-backend-walkthrough.md).

The active backend provides the tested FastAPI foundation plus optional PostgreSQL startup, SQLAlchemy connection pooling, and operation-local sessions. Ruff, Pyright, and Pytest share one repeatable check command with optional real PostgreSQL tests. User, workflow, and immutable workflow-version models are now managed by Alembic revision 0001. User/workflow repositories and caller-owned transaction contexts are implemented. Public registration now validates input, hashes passwords with Argon2id, and commits through AuthService. Login with short-lived access JWTs and authenticated /auth/me now work when a private signing key is configured. Phase 3C adds durable refresh families, one-use rotation, replay revocation and bound CSRF cookies through migration 0002. Phase 3D adds idempotent refresh-family logout and authenticated workflow/version ownership dependencies. Phase 4A adds authenticated metadata CRUD/archive. Phase 4B adds initial saved definitions, immutable snapshots, expected-version concurrency and historical reads. Phase 4C publishes an authenticated six-node configuration catalog and strict internal validators, with strict typed configuration contracts. Phase 4D adds owned saved/candidate graph validation and deterministic compilation without side effects. Phase 5A adds durable run, node-attempt and event tables, owner-scoped repository operations and guarded state transitions in migration 0003. Phase 5B adds synchronous manual/transform/end execution and owner-scoped run creation/history APIs with actual persisted inputs/results/errors. Phase 5C adds typed condition/calculator execution, selected-route traversal, chosen-predecessor merges and atomic skipped-node completion history. All six registered pure types now advertise execution readiness. Workers and Groq follow later. The default frontend now uses real authentication, owned workflow editing/validation and persisted execution history. GET /runs supplies owner-scoped summaries.

To view your own persisted data now, follow [View the real backend and remaining work](../docs/real-backend-walkthrough.md). Start both the API and Vite using that guide; new accounts have empty real data.

## Frontend integration — 4 November 2026

The default app now uses the real API; follow the [startup walkthrough](../docs/real-backend-walkthrough.md) for port 5173 origins and local cookie settings. Initial integration adds GET /runs, with no schema change. Verification at that increment: 858 backend tests with PostgreSQL; 607 passed/251 skipped ordinarily; Ruff 119 files and Pyright clean. Historical phase-specific results below remain historical. Frontend at that increment: 108 tests, lint, TypeScript and build passed. HTTP proxy/session/save/run/restart checks pass; visual browser QA remains unavailable.

## Run

From the repository root:

```bash
cd backend
uv sync --locked
uv run --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log --reload
```

No environment file or credentials are required for health-only mode. To customize settings, optionally copy `.env.example` to `.env` inside `backend/` and edit the copy. The real `.env` is gitignored; the example contains public defaults. Restart the server after changing configuration.

The development interpreter is pinned to **Python 3.13.13**, satisfying the declared Python 3.12+ requirement. `uv sync` may download the interpreter/packages on a fresh machine. Other permitted Python versions have not been tested.

Default URLs:

- Health: http://127.0.0.1:8000/api/v1/health
- Interactive API documentation: http://127.0.0.1:8000/docs
- Alternative API documentation: http://127.0.0.1:8000/redoc
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

Health returns HTTP 200 with:

```json
{ "status": "ok", "service": "agentflow" }
```

This checks **liveness**, not PostgreSQL/Redis/worker/provider readiness. It requires no login or API key and exposes no settings. `/health`, `/api/health`, and `/api/v2/health` return 404.

## Local PostgreSQL

From the repository root:

```bash
docker compose up -d --wait postgres
docker compose --profile test up -d --wait postgres_test
```

Compose pins tested PostgreSQL **16.14** by digest. Development uses localhost port **15432**, database/user `agentflow`, password `agentflow_local`, and a persistent named volume. Tests use port **15433**, database/user `agentflow_test`, password `agentflow_test_local`, and disposable tmpfs storage. These published credentials are for local development only.

To enable database-backed app startup, add the commented `AGENTFLOW_DATABASE_URL` line from `.env.example` to your private `.env`, then restart the app. The URL uses `postgresql+psycopg`; reserved password characters require URL encoding. With no URL health remains available and registration returns a safe 503. With a URL it must connect successfully before serving. `SecretStr` masks normal settings dumps, SQL echo is disabled, and startup connection errors use a static message rather than driver details.

The engine is shared per app process; Sessions are fresh per operation and must stay within their operation's thread. Callers explicitly commit/use session.begin(), or select Database.unit_of_work() to commit on normal exit and roll back on an escaping exception. Repositories only flush. Closing Database.session() without a commit still rolls back. The pool uses pre-ping, five retained plus five overflow connections, five-second pool wait, and five-second driver connect timeout; these do not impose query deadlines. Shutdown disposes checked-in connections. Stop active work and close its sessions before shutdown.

`TEST_DATABASE_URL` is a separate process variable for explicit integration tests, never loaded from `.env` or inferred from the development URL. Tests require localhost, database `agentflow_test`, and no query overrides. Default checks skip 267 real PostgreSQL cases; use --integration to run them. Missing/bad test configuration fails rather than substituting SQLite.

Stop owned services with `docker compose --profile test down`; the development volume is retained. Do not add --volumes if retaining data. Password/init changes do not rewrite an existing database role in populated storage. The existing development container is running with revision 0004 applied and no metadata drift. This additive upgrade preserves existing account/session/workflow identifiers and inserts no execution fixtures. Phases 4B–4D changed no schema; 0003 adds execution history. The verification test container was stopped/removed; start it with the command above when needed.

## Models and migrations

The active schema has `users`, `workflows`, `workflow_versions`, `refresh_sessions`, `refresh_tokens`, `workflow_runs`, `node_runs`, `execution_events`, `run_commands`, and Alembic's revision table. Revision 0003 adds only execution history and its guards; 0001/0002 remain unchanged. User/workflow UUIDs, timezone-aware timestamps, normalized unique emails, legal statuses, positive unique version numbers, a JSONB schema envelope, and restrictive foreign keys are enforced by PostgreSQL. The composite current-version FK prevents referencing another workflow's snapshot. A trigger rejects version UPDATE/DELETE/TRUNCATE; editing a definition requires inserting a new version. Workflow/user update triggers maintain updated_at, including direct SQL updates.

Authentication, workflow ownership and read-only graph validation are implemented through Phase 4D. Execution storage is implemented in 5A and synchronous manual/transform/end execution in 5B. Phase 5C adds exclusive branch/merge routing and calculators; recovery remains later work. Model foreign keys are not authorization. The JSONB envelope does not imply a valid executable DAG. Current-version ORM navigation is view-only: WorkflowRepository.append_version now inserts/flushes snapshots and advances the pointer in a caller-owned transaction. See [models and migration notes](../docs/learning-notes/migrations.md) for fields, relationships, transaction order, and limits.

From the repository root, with your development database URL configured:

```bash
uv run --directory backend --locked alembic upgrade head
uv run --directory backend --locked alembic current
uv run --directory backend --locked alembic check
```

For offline SQL review: `uv run --directory backend --locked alembic upgrade head --sql`. Online commands require AGENTFLOW_DATABASE_URL; they never infer TEST_DATABASE_URL. Alembic uses validated settings rather than storing/interpolating credentials in alembic.ini. The app does not auto-migrate on startup. Initial downgrade destroys the tables and their data; downgrade/re-upgrade verification is confined to disposable schemas in the guarded local test database. No development downgrade was performed.

If your terminal is already inside `agentflow/backend`, omit `--directory backend`:

```bash
uv run --locked python scripts/check.py
uv run --locked alembic upgrade head
uv run --locked alembic current
uv run --locked alembic check
```

“Repository root” means the `agentflow` directory, one level above `backend`; it is not a folder named `repository`. If Alembic reports `Set AGENTFLOW_DATABASE_URL`, enable the commented local Compose URL from `.env.example` in `backend/.env` by removing its leading `#`. Do not overwrite an existing `.env` to make this change. The default checks deliberately skip real database cases, so passing them does not verify database configuration.

## Repositories and units of work

UserRepository accepts normalized email and precomputed password hashes, inserts users, and performs ID/exact-email lookups. WorkflowRepository inserts draft metadata, reads workflow/version rows with an owner filter, lists bounded pages, and appends versions. Neither repository commits, hashes passwords, authenticates callers, or validates executable graphs.

A caller opens `with database.unit_of_work() as session:` and passes that session to both repositories. Normal exit commits all work; an escaping failure rolls it all back and closes the session. Database.session() remains available for reads/manual transactions and never commits automatically. Do not share sessions across threads or open a separate nested unit of work expecting it to join the first.

Version append uses SELECT FOR UPDATE with refreshed ORM state, compares expected_version (0 for a versionless draft), allocates the next history number, inserts a deep-copied snapshot, and moves the current pointer. Concurrent writers with the same expected number produce one commit and one stale-version conflict. The query refreshes cached state and expires current/history navigation after the write. Pending metadata is flushed before refresh and rolled back if the save later conflicts.

Missing/not-owned workflows raise WorkflowNotFoundError; stale versions raise WorkflowVersionConflictError. Database integrity errors remain internal SQLAlchemy outcomes for later services to classify. Workflow services now map missing ownership, stale saves and unavailable storage to safe HTTP outcomes. Production lock deadlines/retries remain pending. Services must derive owner_id from authenticated context and keep network/model calls outside transactions. See [execution persistence notes](../docs/learning-notes/execution-persistence.md), [workflow validation notes](../docs/learning-notes/workflow-validation.md), [node registry notes](../docs/learning-notes/node-registry.md), [workflow version notes](../docs/learning-notes/workflow-versions.md), [workflow metadata notes](../docs/learning-notes/workflow-metadata.md), [logout/ownership notes](../docs/learning-notes/logout-ownership.md), [refresh-session notes](../docs/learning-notes/refresh-sessions.md), [login/token learning notes](../docs/learning-notes/login-access-tokens.md), [registration learning notes](../docs/learning-notes/authentication.md), [repository learning notes](../docs/learning-notes/repositories.md) for functions, flow, tests, and limits.

## Registration — Phase 3A

With PostgreSQL running, the database URL configured, and revision 0001 applied, start the API using the command above and open `/docs`. Use **POST /api/v1/auth/register** with this JSON shape (choose your own local test password):

```json
{
  "email": "owner@example.com",
  "display_name": "Owner",
  "password": "a local example passphrase"
}
```

A successful request creates an actual account in the configured database. HTTP 201 returns only `id`, normalized `email`, trimmed `display_name`, `is_active`, `created_at`, and `updated_at`, with `Cache-Control: no-store`. It does not log the user in or issue tokens/cookies. Avoid reusing the sample credentials outside local testing.

Email is syntax-validated, trimmed, and lowercased for account identity; no deliverability lookup or verification email is sent. Display names are trimmed and limited to 1–100 characters. Passwords require 8–128 Unicode characters and at least one non-whitespace character; spaces/case are preserved exactly and no composition rules are imposed. Unknown fields and non-string values are rejected. SecretStr hides representations; Argon2id provides the stored salted hash.

Duplicate normalized email returns 409 `EMAIL_ALREADY_REGISTERED`, invalid input 422 `VALIDATION_ERROR`, and missing/unavailable storage 503 `SERVICE_UNAVAILABLE`, through the existing safe request-ID envelope. Database dependency resolution may return 503 before body validation when storage is not configured. Unknown integrity failures remain safe 500s rather than being mislabeled as duplicates.

Hashing runs before the SQL transaction. The synchronous route keeps hashing and its operation-local Session in one worker thread. The database unique constraint handles simultaneous signups; success is returned only after commit. See the [registration learning notes](../docs/learning-notes/authentication.md) for file/function explanations, request flow, tests, limitations, and one exercise. No rate limit, breached-password blocklist, account verification, is implemented yet; frontend authentication is now connected; this increment is not ready for public deployment.

## Login and authenticated profile — Phases 3B/3C

Login additionally requires `AGENTFLOW_JWT_SECRET_KEY` in your private `backend/.env` or process environment. There is no shared/default key. From `backend/`, generate a random local value with:

```bash
uv run --locked python -c 'import secrets; print(secrets.token_hex(32))'
```

Save that value locally as `AGENTFLOW_JWT_SECRET_KEY=<generated value>`, then restart the server. Keep it out of chat, source control, screenshots and logs. This implementation increment did not read or edit your private .env. The validator requires 32–4096 UTF-8 bytes and rejects outer whitespace before settings trimming; length alone cannot establish randomness.

After applying `alembic upgrade head`, call **POST /api/v1/auth/login** with JSON email/password (omit display_name), an exact allowed Origin, and `X-AgentFlow-Client: web`. Browsers supply Origin; in `/docs` fill the client header field with `web`. HTTP 200 returns `access_token`, `csrf_token`, `token_type: "bearer"`, `expires_in: 900`, and `user` with the same public fields as registration. It sets refresh/CSRF cookies. For local HTTP, configure `AGENTFLOW_REFRESH_COOKIE_SECURE=false`; otherwise Secure cookies require HTTPS. Default allowed origins include http://127.0.0.1:8000, http://localhost:8000, http://127.0.0.1:5173 and http://localhost:5173. An explicit private setting overrides these defaults. Choose **Authorize**, paste the access token, then call **GET /api/v1/auth/me**. This uses HTTP Bearer security, not the OAuth2 password-form protocol. Send `Authorization: Bearer <access_token>` from other HTTP clients. Access credentials for /me are accepted only in that header. Refresh uses its own cookie/CSRF protocol below.

Tokens use fixed HS256 and default to 15 minutes. Required claims include UUID sub/jti, issuer, audience, integer issued/not-before/expiry times and access purpose; validation checks signatures, allowed algorithm, token header/purpose, expiry, issuer/audience and bounded lifetime. No email, password, hash or role is stored in JWT claims. JWTs are signed, not encrypted.

Wrong passwords, unknown emails, inactive accounts, invalid/expired tokens and missing/deleted token subjects all return the same 401 UNAUTHENTICATED envelope and WWW-Authenticate: Bearer challenge. Login validates strict email/password input (password 1–128 characters; exact spaces/case preserved). Malformed bodies remain 422. Missing signing key or unavailable storage returns safe 503; health and registration do not require a JWT key. `/me` with no Bearer credential returns 401 before configuration/storage lookup.

The service closes its initial read transaction before Argon2 verification and performs a real dummy check for unknown emails. It then rechecks the current account/hash before issuing. `/me` reads the current account on every request and rejects inactive/deleted accounts. Successful login and `/me` responses use Cache-Control: no-store; login also uses Pragma: no-cache. Refresh cookies/families are now implemented; logout is now implemented; an access-JWT revocation list remains later work; the frontend connection is implemented. Reusable Bearer tokens remain valid until expiry unless account state/key configuration invalidates them. See [login/token notes](../docs/learning-notes/login-access-tokens.md) for flow, tests and limits.

## Refresh sessions — Phase 3C

`POST /api/v1/auth/refresh` takes no body credentials. Send the refresh/CSRF cookies plus `Origin`, `X-AgentFlow-Client: web`, and `X-AgentFlow-CSRF` equal to the current readable CSRF cookie (also returned as csrf_token in login/refresh JSON). Browsers manage cookies automatically. Use one consistent API hostname. Vite proxies same-origin browser requests and preserves Origin; no CORS middleware is required for this arrangement. An origin allowlist is not a CORS permission.

Default cookies are **\__Host-agentflow_refresh** (HttpOnly) and **\__Host-agentflow_csrf** (readable). Both are Secure, SameSite=Strict, Path=/, with no Domain. Local HTTP must explicitly set AGENTFLOW_REFRESH_COOKIE_SECURE=false, which changes names to agentflow_refresh/agentflow_csrf; production refuses this mode. Production signing-key configuration also requires explicit HTTPS allowed origins. For a different local port, set AGENTFLOW_AUTH_ALLOWED_ORIGINS to a JSON array of exact scheme/host/port origins, with no slash/path/wildcard.

Every login creates a separate family, with seven-day absolute expiry by default. Raw 256-bit refresh/CSRF values are never stored in PostgreSQL: refresh_tokens holds SHA-256 digests and consumed history, while refresh_sessions holds owner, expiry and revocation. A family row lock serializes rotation; consumption plus replacement commit atomically. Refresh returns a new access token, current user and csrf_token, and replaces both cookies without extending family expiry.

Missing/invalid/expired/revoked refresh credentials return safe 401 and clear this browser's cookie pair. Bad Origin/client/CSRF proof returns safe 403 without consuming tokens or clearing cookies. Storage failure returns safe 503 without discarding cookies. Replaying a consumed token with valid bound CSRF proof commits family revocation before returning 401. Other login families are unaffected. Existing access JWTs continue until their own expiry; refresh revocation is not an access-token denylist.

Clients must serialize refresh, including across tabs. Two uses of the same token are treated as reuse: at most one receives a replacement, then the family is revoked. A lost response after a committed rotation also requires a fresh login if the old token is retried. No grace window or transparent retry is claimed. Automatic history cleanup remains pending. Frontend wiring and logout are implemented. See [execution persistence notes](../docs/learning-notes/execution-persistence.md), [workflow validation notes](../docs/learning-notes/workflow-validation.md), [node registry notes](../docs/learning-notes/node-registry.md), [workflow version notes](../docs/learning-notes/workflow-versions.md), [workflow metadata notes](../docs/learning-notes/workflow-metadata.md), [logout/ownership notes](../docs/learning-notes/logout-ownership.md), [refresh-session notes](../docs/learning-notes/refresh-sessions.md) for file/transaction explanations, tests and review.

## Logout and ownership — Phase 3D

**POST /api/v1/auth/logout** uses the same allowed Origin and X-AgentFlow-Client: web as refresh. With a well-formed refresh cookie, include its matching readable CSRF cookie and X-AgentFlow-CSRF header. No access JWT or signing key is required, so an expired access token does not prevent logout. In /docs, fill the client and CSRF header fields; the browser supplies Origin/cookies.

Success is **204 with no body**, Cache-Control: no-store, Pragma: no-cache, and deletion of both cookies. The service revokes only the represented refresh family, including when called with a consumed ancestor, and commits before clearing cookies. Repeating logout is safe. Missing/malformed cookies return 204 without a database; well-formed unknown credentials return 204 after a database lookup. Known expired/inactive/revoked families also return 204 with valid proof. Wrong Origin/client/CSRF proof returns 403 without clearing or revoking; unavailable storage returns 503 without falsely claiming success or deleting retry credentials. JSON/query user IDs, all_sessions flags and Bearer values do not select a family.

Logout and refresh share family locks; their race cannot leave a usable refresh descendant after logout commits. Other login families stay usable. Existing access JWTs retain their expiry/current-account checks: the client must discard its in-memory access token on sign-out. There is no logout-all endpoint or access-JWT denylist.

Production ownership dependencies derive owner_id from the validated active user and query workflows/versions with that owner filter. Missing/not-owned resources and versions from another workflow all yield the same safe 404; storage failure yields safe 503. They return immutable identifier references, never ORM objects or open Sessions. These dependencies were verified through test-only routes in 3D. Phase 4A now adds public metadata CRUD using the authenticated user and owner filters inside every operation. Writes hold an owner-scoped row lock inside their transaction; an earlier dependency lookup is not a persistent permission grant. See [execution persistence notes](../docs/learning-notes/execution-persistence.md), [workflow validation notes](../docs/learning-notes/workflow-validation.md), [node registry notes](../docs/learning-notes/node-registry.md), [workflow version notes](../docs/learning-notes/workflow-versions.md), [workflow metadata notes](../docs/learning-notes/workflow-metadata.md), [logout/ownership notes](../docs/learning-notes/logout-ownership.md).

## Workflow APIs — Phase 4B

All five operations require `Authorization: Bearer <access JWT>` from login/refresh. In /docs, choose Authorize and paste the access JWT. They do not use refresh cookies for authentication or require cookie-operation Origin/client/CSRF headers. No new environment setting, dependency or migration is needed.

| Method and path                        | Implemented behavior                                                                                           |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| POST /api/v1/workflows                 | Create owned draft; optional definition creates version 1 atomically. Returns 201/Location.                    |
| GET /api/v1/workflows                  | Owned metadata pagination/search; default excludes archived, no graph payloads.                                |
| GET /api/v1/workflows/{workflow_id}    | Metadata plus current snapshot; optional version_id UUID selects an owned historical snapshot.                 |
| PATCH /api/v1/workflows/{workflow_id}  | Partial metadata and/or immutable definition append with expected_version; archived or stale saves return 409. |
| DELETE /api/v1/workflows/{workflow_id} | Archive only; empty 204, repeated owned archive is safe; history/pointer retained.                             |

Create accepts name (trimmed 1–200), optional description (trimmed max 5000, default empty) and optional definition. Omitting definition leaves current_version_id null; including it inserts immutable version 1. PATCH requires metadata or definition; omitted metadata is preserved, null rejected, empty description clears it. Definition and expected_version must be provided together. Use the server's current_version_number, or 0 for a versionless draft. Expected numbers must be strict nonnegative integers (max 2147483647), not strings/floats/booleans/null. Owner/status/pointer fields remain forbidden. Metadata-only edits retain serialized last-write behavior without a version precondition.

Definition requires schema_version "1.0", nodes/edges arrays of objects (max 500/2000), finite native JSON values, string keys, depth at most 32 and compact UTF-8 size at most 256 KiB. Top-level extension and nested business keys are preserved, including their case. These are draft storage checks: arbitrary node types/incomplete configurations can be saved; saving does not validate executable semantics; separate validation and run commands do. The limit applies after body parsing, not at the transport layer. Never place credentials in definitions; arbitrary business data is not automatically secret-redacted.

POST, item GET and PATCH return the eight metadata fields plus current_version_number and version. Snapshot fields are id, workflow_id, version_number, definition, created_by and UTC created_at. A versionless draft returns number 0/version null. Historical GET selects version by exact UUID but retains the workflow's current metadata/pointer/number; it does not restore old metadata or rewind the pointer. There is no history-list route yet. List items remain metadata only.

List still accepts page (1–1000000), page_size (1–100, default 25), optional status and trimmed q (literal case-insensitive name substring, max 200). Default ordering is updated_at descending then ID descending. status=archived selects archived rows. Owner/status/q filters apply to totals and items; unknown list query fields are 422. Offset pages/count are not a frozen snapshot under concurrent writes.

Writes own one transaction and refreshed owner-scoped row lock. A stale definition save returns 409 WORKFLOW_VERSION_CONFLICT and rolls back metadata, snapshot and pointer together. Reload and resolve with the retained local draft; blind retries are not a merge. Identical definitions still append on a successful current save. Archived rows/history remain readable, but saves/metadata edits return 409 WORKFLOW_ARCHIVED. DTO construction occurs before commit. Missing/unowned/mismatched versions share safe 404, malformed input 422, storage failure 503 and unexpected failure 500. Success responses are no-store. See [execution persistence notes](../docs/learning-notes/execution-persistence.md), [workflow validation notes](../docs/learning-notes/workflow-validation.md), [node registry notes](../docs/learning-notes/node-registry.md), [workflow version notes](../docs/learning-notes/workflow-versions.md) for payload examples, functions, tests and review.

## Node registry — Phase 4C

GET /api/v1/node-types requires the same active-user Bearer JWT as workflows. It returns schema_version "1.0" and six typed contracts: manual, transform, condition, calculator, merge and end. All six now declare execution_ready true and capabilities ["validate_config", "execute"]. Every entry declares name/category/description, output_handles and self-contained config_schema. Catalog reads do not execute nodes; no provider/model capability is invented. Success is no-store.

Structural node configs are empty objects. Transform permits identity or bounded unique top-level pick_fields. Condition requires a typed output-reference comparison; calculator permits add/subtract/multiply/divide with explicit literal/output operands. Strict validation rejects extra fields, guessed string/number/bool conversions, arbitrary expressions, non-finite or out-of-range literals and unbounded references. References use $.node_id.output.field dictionary paths, not templates/eval. The internal node config validator is now used by the Phase 4D graph compiler. Save still permits incomplete/unsupported draft configurations, preserving Phase 4B behavior.

The registry does not run nodes. LLM/HTTP/agent/approval/parser/classify/extract and schedule/webhook contracts are absent until implemented in their owning increments. See [execution persistence notes](../docs/learning-notes/execution-persistence.md), [workflow validation notes](../docs/learning-notes/workflow-validation.md), [node registry notes](../docs/learning-notes/node-registry.md) for exact JSON schemas, bounds, examples, functions and review.

## Graph validation — Phase 4D

POST /api/v1/workflows/{workflow_id}/validate uses active-user Bearer auth and requires a JSON body. Send {} for the current saved version, {"version_id":"<uuid>"} for exact owned history, or {"definition":{...}} for an unsaved candidate. Selectors are mutually exclusive; provided null/extra fields/malformed envelopes return safe 422. Missing/unowned/mismatched versions share generic 404. An owned versionless draft returns 200 valid false/NO_SAVED_DEFINITION. Archived graphs remain inspectable without restoration or activation.

Well-formed semantic failures return 200 valid false with bounded static issues and plan null. Success returns valid true and a summary: entry ID, node/edge counts, canonical topological order and terminal IDs. execution_ready is true only for valid graphs whose nodes all have current executors (all six registered types in 5C). Invalid graphs remain false. Readiness describes capability, not authorization or runtime input validity. The topological order includes alternative branches; it is not an execution log. Reports are no-store and do not echo raw configs or validator text. At most 100 diagnostics are returned, with issues_truncated for excess; staged validation can stop before later dependent checks.

The compiler accepts strict snake_case node/edge envelopes, unique bounded IDs, six registered configs, one manual entry, end terminals, declared default/true/false routes, explicit merge convergence, full reachability and no cycles/parallel fan-out. Only root schema_version/nodes/edges and optional metadata object are supported for compilation; existing arbitrary draft extensions remain stored but may need moving into metadata before validation succeeds. Node label/position are presentation only. Optional input_mapping maps literal input keys to output references. Referenced nodes must be present on every route reaching the consumer; a branch-local ancestor is insufficient after a merge. Actual field existence/types, dictionary resolution and operation failures remain runtime checks.

Ownership and immutable snapshot selection happen inside a short read Session. Its copied definition is compiled after storage closes. Validation never updates status, timestamp, current pointer or version history. Run creation independently recompiles the exact owned version and checks current execution support. See [workflow validation notes](../docs/learning-notes/workflow-validation.md) for schemas, algorithms, examples, files and limits. This adds one baseline endpoint: 13 implemented operations across ten paths. No migration/configuration/dependency change is needed.

## Execution storage — Phase 5A

Migration 0003 stores each run against an exact immutable workflow version, each retry as a separate node attempt, and each mutation as an ordered metadata event. ExecutionRepository uses owner-scoped run locks, expected revisions and caller-owned units of work so state, result and event commit together. SQL constraints/triggers protect identities, saved-node membership, legal transitions and retained history. Result/input snapshots are bounded JSON objects; events exclude raw business payloads and exception text.

Phases 5B/5C now use this persistence module for real execution, including existing skipped attempt states without a new migration. Reserved waiting/cancelled states still do not implement approval/cancellation commands. See [execution persistence notes](../docs/learning-notes/execution-persistence.md) for schema/lifecycle rules, and [first runner notes](../docs/learning-notes/first-runner.md) for the implemented runner/API flow.

## First execution — Phase 5B

In Swagger, save a valid manual → transform → end graph, then call **POST /api/v1/workflows/{workflow_id}/runs** with `{"workflow_version_id":"<saved-version-uuid>","input":{"CustomerID":42}}`. Both fields are required. Supported transforms are identity and pick_fields; see the [runnable example](../docs/real-backend-walkthrough.md). The POST executes synchronously and returns **201**, Location and no-store, with the persisted run/version/attempt DTO. A created run can have status failed: inspect status/error_code rather than treating every 201 as successful execution. **GET /api/v1/runs/{run_id}** returns owned exact-version history, even after another definition is saved or the workflow is archived.

Without input_mapping, each node receives the previous output. Explicit mappings replace that object and resolve only compiler-approved upstream dictionary outputs. A missing selected key gives EXECUTION_FAILED; missing/non-dictionary mappings give INPUT_MAPPING_FAILED. End output becomes run output. No downstream node is invoked after a failure. State/results/events commit together in short transactions; pure computation holds no operation Session open.

Every POST creates a distinct run. Optional Idempotency-Key now deduplicates commands; see the 5D contract below. Storage errors return safe 503; a known committed run has Location for inspection. Failed writes/crashes can retain queued/running history, with no automatic replay or recovery yet. Events APIs, worker dispatch and recovery remain pending; listing and cancel/retry commands are implemented; condition/calculator/merge execution is implemented in 5C. The API now has **18 operations across 15 paths** and migration **0004** for command receipts/attempt budgets. See [first runner notes](../docs/learning-notes/first-runner.md) for fields, functions, transactions, actual checks, limitations and review.

## Branches and arithmetic — Phase 5C

WorkflowRunner follows the chosen route from the manual entry. A condition outputs {"result":true/false}, selecting its declared true/false handle; a calculator outputs {"result":number}. merge copies only the chosen predecessor output. At a successful end, the end result, pending-to-skipped attempts for every unvisited node and succeeded run/output/events commit in one transaction. Skipped attempts have input {}, no output/start, duration 0 and revision 1. Selected-route failures stop with actual failure history and no completion skips.

Comparisons use typed scalars; boolean and numeric-string values are not numbers. Equality distinguishes scalar categories, ordering requires finite int/float values, and contains is case-sensitive substring. Runtime numbers and arithmetic intermediates/results stay within ±10^12; strings used by comparisons are bounded to 4096 characters. Divide by zero, invalid types and overflow produce static failures. Data input and declared config references resolve separately from executed upstream dictionary outputs, outside database transactions; literal path-looking strings remain literal.

Use the [runnable branching example](../docs/learning-notes/branch-execution.md) to get {"result":22} from amount 11 or {"result":5} from amount 4, and inspect the opposite skipped arm through run GET. Nested branches, shared merges, early ends and independent concurrent runs are verified. Existing compiler/dominator validation, owner/version/archive checks and storage-failure behavior still apply. No endpoint, model, dependency or migration change was required; head remains 0003. Next is 5D command hardening. See [branch execution notes](../docs/learning-notes/branch-execution.md) for functions, exact rules, actual tests, limits and review.

## Configuration

| Environment variable     | Default         | Behavior                                                                                                           |
| ------------------------ | --------------- | ------------------------------------------------------------------------------------------------------------------ |
| `AGENTFLOW_APP_NAME`     | `AgentFlow API` | FastAPI/OpenAPI title; trimmed; 1–100 characters                                                                   |
| `AGENTFLOW_ENVIRONMENT`  | `development`   | `development`, `testing`, or `production`; lifecycle metadata                                                      |
| `AGENTFLOW_DEBUG`        | `false`         | FastAPI debug flag; rejected in production; API failures still use safe JSON                                       |
| `AGENTFLOW_DOCS_ENABLED` | `true`          | Controls `/docs`, `/redoc`, and `/openapi.json` together; health remains available                                 |
| `AGENTFLOW_LOG_LEVEL`    | `INFO`          | Application level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`                                              |
| `AGENTFLOW_DATABASE_URL` | unset           | Optional secret postgresql+psycopg URL with explicit host/database; configured startup requires a reachable server |

Additional authentication settings:

| Environment variable               | Default       | Behavior                                                                                                                    |
| ---------------------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------------- |
| AGENTFLOW_JWT_SECRET_KEY           | unset         | Private random HS256 key; 32–4096 UTF-8 bytes, no outer whitespace. Unset disables token issuance/validation with safe 503. |
| AGENTFLOW_JWT_ISSUER               | agentflow     | Exact issuer to issue/validate; trimmed 1–100 characters                                                                    |
| AGENTFLOW_JWT_AUDIENCE             | agentflow-api | Exact single audience to issue/validate; trimmed 1–100 characters                                                           |
| AGENTFLOW_ACCESS_TOKEN_TTL_SECONDS | 900           | Integer 60–3600 seconds; also maximum accepted token lifetime                                                               |

Refresh settings:

| Environment variable                | Default                        | Behavior                                                                                                    |
| ----------------------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------- |
| AGENTFLOW_REFRESH_TOKEN_TTL_SECONDS | 604800                         | Absolute family lifetime, 300–2592000 seconds; refresh never extends it                                     |
| AGENTFLOW_REFRESH_COOKIE_SECURE     | true                           | Secure + __Host- cookie names; false is explicit local HTTP only, forbidden in production                   |
| AGENTFLOW_AUTH_ALLOWED_ORIGINS      | local API origins on port 8000 | JSON array of 1–10 exact HTTP(S) origins, no paths/wildcards; HTTPS required for configured production auth |

Settings load once per `create_app()` invocation. Precedence: **explicit constructor values → process environment → `backend/.env` → field defaults**. The absolute dotenv path is derived from `config.py`, independent of the working directory. `Settings(_env_file=None)` skips the file while retaining environment values. See [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

Variable names are case-insensitive with the `AGENTFLOW_` prefix. Unrelated dotenv keys are ignored to support a shared file; misspelled names therefore do not produce an error. Recognized settings must validate. The optional database URL is consumed at startup. Provider credentials/settings remain future work.

`Settings` validates types and cross-field rules. `frozen=True` prevents assigning new field values after validation. `load_settings()` turns validation failures into `ConfigurationError` with field names and readable messages, omitting supplied values and suppressing the original exception traceback. Invalid configuration prevents app construction before ASGI startup; it is not an HTTP error.

Production rejects debug as defense in depth. Phase 1C also keeps safe JSON for HTTP failures inside the request boundary when local debug is enabled. Documentation visibility is independent and is not an authorization boundary. Python callers can inject a validated object with `create_app(settings=Settings(...))`. Each app stores its settings in `application.state.settings`; there is no global settings cache or reload-on-request behavior.

## Request IDs and HTTP errors

Every HTTP response receives `X-Request-ID: req_<32 hexadecimal characters>`. Caller-supplied IDs are ignored; use the response ID to correlate application logs. The health JSON stays unchanged.

Errors now use the planned envelope instead of the framework's `detail` body:

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

Routing, request validation, and unexpected errors before response start share this shape. Status codes remain meaningful; `Allow`, `WWW-Authenticate`, and `Retry-After` are preserved when applicable. Raw exception/validation messages, inputs, and custom headers are withheld. Validation details deliberately stay null until a module defines safe public field details. OpenAPI documents the default error schema and correlation headers.

Completion logs contain method, route template (or `<unmatched>`), status, duration, environment, request ID, and unexpected exception type. They do not include raw paths, query strings, bodies, credentials, or exception text. Arbitrary extras are ignored, but future callers must still avoid secrets in the log message itself. Failures after headers/streaming begins retain the committed status, log ERROR, and propagate; the response cannot be rewritten. Such server-level tracebacks need separate privacy handling. HTTP cancellation is not converted into 500. WebSocket correlation and tracing remain future work.

## Files and responsibilities

| File                                                                                                                                                                    | Responsibility and important calls                                                                                                                                                                                                                                           |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/main.py`                                                                                                                                                           | `create_app(settings: Settings \| None = None) -> FastAPI` loads or accepts settings; configures title/debug/docs; registers lifespan, app state, router, error handlers, request middleware, and shared OpenAPI errors                                                      |
| `app/core/config.py`                                                                                                                                                    | `Settings(BaseSettings)` loads/validates configuration. `SettingsConfigDict` defines sources and behavior; `Field` bounds the name; `model_validator(mode="after")` rejects production debug. `load_settings() -> Settings` sanitizes failures into `ConfigurationError`     |
| `app/core/lifespan.py`                                                                                                                                                  | `application_lifespan(application)` uses `asynccontextmanager`: startup before `yield`, shutdown in `finally`; configures JSON logging; optionally checks PostgreSQL in a worker thread, stores the Database on app state, and disposes its pool at shutdown/startup failure |
| `app/infrastructure/database/base.py`, `models.py`                                                                                                                      | Shared named metadata and explicit registry for all mapped tables; no create_all or import-time network                                                                                                                                                                      |
| `app/core/refresh_tokens.py`, `app/modules/auth/refresh_models.py`, `refresh_repository.py`, `app/api/auth_cookies.py`, `migrations/versions/0002_refresh_sessions.py`  | Opaque credential generation/digests, family and consumed-token history, family locks, browser cookies and explicit schema migration                                                                                                                                         |
| `tests/unit/test_refresh_config.py`, `tests/api/test_refresh_contract.py`, `tests/integration/test_refresh.py`, `test_refresh_concurrency.py`, `test_refresh_models.py` | Cookie/Origin/CSRF policy, rotation/replay/rollback/recovery, independent-connection races, DB constraints and 0002 downgrade preservation                                                                                                                                   |
| `app/modules/workflows/schemas.py`, `service.py`, `app/api/v1/workflows.py`                                                                                             | Strict metadata DTOs/query contract, owner-scoped transactions, metadata CRUD/archive routes and no-store responses                                                                                                                                                          |
| `tests/unit/test_workflow_schemas.py`, `tests/api/test_workflow_contract.py`, `tests/integration/test_workflow_crud.py`, `test_workflow_crud_concurrency.py`            | Input/OpenAPI/auth contract, two-user CRUD, literal search/pagination, archive history, rollback and concurrent stale-cache rules                                                                                                                                            |
| `app/modules/workflows/access.py`, `app/api/workflow_dependencies.py`                                                                                                   | Authenticated workflow/version ownership resolution, immutable references and indistinguishable safe 404/503 mappings; no public CRUD routes                                                                                                                                 |
| `tests/api/test_logout_contract.py`, `tests/integration/test_logout.py`, `test_logout_concurrency.py`, `test_workflow_ownership.py`                                     | Idempotent committed logout, CSRF/cookie/retry behavior, real races and two-user HTTP ownership boundaries                                                                                                                                                                   |
| `app/core/tokens.py`                                                                                                                                                    | Fixed-algorithm access JWT signing/validation, required claims, safe InvalidAccessTokenError                                                                                                                                                                                 |
| `tests/unit/test_access_tokens.py`, `test_auth_config.py`, `tests/api/test_login_contract.py`, `tests/integration/test_login.py`                                        | Real signatures/hostile claims, key/lifetime validation, HTTP Bearer contracts, PostgreSQL credential/status/state/privacy checks                                                                                                                                            |
| `app/core/security.py`, `app/modules/auth/schemas.py`, `service.py`, `exceptions.py`                                                                                    | Argon2id hash/verify, strict credential/public DTOs, registration transaction, login/current-user service and plain duplicate/storage/auth outcomes                                                                                                                          |
| `app/api/dependencies.py`, `app/api/v1/auth.py`                                                                                                                         | Resolve engine/token policy/current user, run SQL and password work in worker threads, document auth routes and map safe errors                                                                                                                                              |
| `tests/unit/test_password_hashing.py`, `test_registration_schemas.py`, `tests/api/test_registration_contract.py`, `tests/integration/test_registration.py`              | Real hash profile/verification, input/output privacy, HTTP/OpenAPI contracts, rollback, and concurrent PostgreSQL signup checks                                                                                                                                              |
| `app/modules/auth/repository.py`                                                                                                                                        | Concrete user add and ID/normalized-email lookups using a caller-owned Session; no commits or hashing                                                                                                                                                                        |
| `app/modules/workflows/repository.py`, `exceptions.py`                                                                                                                  | Owner-scoped reads/listing, locked expected-version append, snapshot copying, and plain missing/stale outcomes                                                                                                                                                               |
| `tests/integration/test_repositories.py`, `test_repository_concurrency.py`                                                                                              | Atomicity, flush visibility, rollback/recovery, ownership, cached data, history, real version/email races                                                                                                                                                                    |
| `app/modules/auth/models.py`                                                                                                                                            | User mapping with normalized unique email, bounded fields, defaults, and relationships                                                                                                                                                                                       |
| `app/modules/workflows/models.py`                                                                                                                                       | Workflow metadata/status, immutable version snapshots, same-workflow pointer, JSONB checks, indexes, and explicit ORM joins                                                                                                                                                  |
| `alembic.ini`, `migrations/`                                                                                                                                            | Credential-free Alembic setup, template, explicit revision 0001 upgrade/downgrade, timestamp and immutability triggers                                                                                                                                                       |
| `tests/unit/test_orm_metadata.py`, `tests/integration/test_models.py`, `test_migrations.py`                                                                             | Mapper/offline DDL checks; real constraints, snapshots, populated migration round trip, and metadata drift                                                                                                                                                                   |
| `app/infrastructure/database/session.py`                                                                                                                                | Database owns the shared engine, connection check, per-operation Session context, and pool disposal; sessions never implicitly commit                                                                                                                                        |
| `compose.yaml` (repository root)                                                                                                                                        | Isolated local PostgreSQL development and test services, healthchecks, loopback ports, separate storage                                                                                                                                                                      |
| `app/core/middleware.py`                                                                                                                                                | Pure ASGI request IDs, isolated state/context, header injection, safe pre-response 500s, stream passthrough, and completion timing/logging                                                                                                                                   |
| `app/core/exceptions.py`                                                                                                                                                | Validated error envelope, static status/message mappings, HTTP/validation handlers, safe protocol headers, shared OpenAPI definitions                                                                                                                                        |
| `app/core/logging.py`                                                                                                                                                   | Allowlisted JSON formatter, ContextVar correlation, idempotent application-only logging configuration                                                                                                                                                                        |
| `app/core/__init__.py`                                                                                                                                                  | Package marker; no startup actions                                                                                                                                                                                                                                           |
| `app/api/router.py`                                                                                                                                                     | Existing module-router composition under `/api/v1`                                                                                                                                                                                                                           |
| `app/api/v1/health.py`                                                                                                                                                  | Existing `HealthResponse` with required `Literal` fields and forbidden extras; `get_health()` returns the documented JSON contract; documents the new response correlation header                                                                                            |
| `tests/conftest.py`                                                                                                                                                     | Selects asyncio through AnyIO; clears prefixed environment variables and disables private dotenv loading, restored after each test by `monkeypatch`; also captures/restores AgentFlow logging state                                                                          |
| `tests/unit/test_config.py`                                                                                                                                             | Defaults/parsing, precedence, fixed dotenv location, safe errors, production protection, immutability, per-app isolation                                                                                                                                                     |
| `tests/api/test_application.py`                                                                                                                                         | Injected title/debug and documentation controls; exact health response preserved                                                                                                                                                                                             |
| `tests/api/test_lifespan.py`                                                                                                                                            | Explicit ASGI startup/shutdown, continued service after HTTP 500, and `finally` on exceptional context exit                                                                                                                                                                  |
| `tests/api/test_health.py`                                                                                                                                              | Existing HTTP/OpenAPI contract, routing, public health, independent app state/routes, docs HTML                                                                                                                                                                              |
| `tests/api/test_errors.py`, `tests/api/test_request_context.py`                                                                                                         | Error contracts, protocol headers, input privacy, request ID uniqueness/isolation, concurrency, JSON log correlation, OpenAPI                                                                                                                                                |
| `tests/unit/test_logging.py`, `tests/unit/test_middleware.py`                                                                                                           | Formatter privacy, level filtering, handler isolation, unbuffered streaming, late failures, cancellation, context reset                                                                                                                                                      |
| `.env.example`                                                                                                                                                          | Foundation settings and a commented local-only PostgreSQL URL; private .env unchanged                                                                                                                                                                                        |
| `tests/unit/test_database_config.py`, `test_database_startup_failure.py`                                                                                                | URL/secret validation and sanitized startup failure cleanup                                                                                                                                                                                                                  |
| `tests/integration/`                                                                                                                                                    | Real PostgreSQL connectivity, explicit commit, rollback, concurrent transactions, closed sessions, and lifespan/pool cleanup                                                                                                                                                 |
| `scripts/check.py`                                                                                                                                                      | Runs Ruff lint, format verification, Pyright, then Pytest; fixes the working directory, stops on failure, and forwards optional --integration                                                                                                                                |
| `pyproject.toml`, `uv.lock`, `.python-version`                                                                                                                          | Dependency ranges, resolved versions, test/lint/type-check settings, interpreter                                                                                                                                                                                             |

Core owns configuration/lifecycle; database infrastructure owns the engine and Session factory. Future services own transaction decisions. A constant health response needs no service/repository and never queries PostgreSQL. Phase 2B adds users, workflows, and workflow_versions through Alembic. Phase 2A session tests still use temporary tables/locks; new migration/model tests use random disposable schemas in the dedicated test database. Earlier `backend/agentflow/` drafts remain unchanged and unintegrated.

## Startup, request, and shutdown flow

```text
Uvicorn --factory
  → create_app() → load/validate Settings (invalid settings stop construction)
  → configure FastAPI + app.state.settings + router + handlers + middleware
  → ASGI startup → configure logging → optional PostgreSQL connect/check → startup record
  → serve requests:
      middleware sets request ID → router → handler / safe error mapping
        → response with X-Request-ID → completion JSON record → reset context
  → ASGI shutdown → lifespan finally → optional pool disposal → shutdown record
```

FastAPI's [lifespan context manager](https://fastapi.tiangolo.com/advanced/events/) groups startup/shutdown ownership. Future modules will acquire and close resources here. When a database URL is present, the lifespan checks connectivity before serving and disposes checked-in pooled connections at exit, also cleaning up after a failed startup check. Blocking database operations are offloaded through a worker thread. `finally` handles context unwinding, not forced process kills.

The lifespan configures one stdout JSON handler for `agentflow` loggers at the selected level. Repeated startup does not add duplicate handlers; root and Uvicorn loggers are not reconfigured. Logging is process-global, so the most recent startup selects the shared application level. With `--no-access-log`, the application completion records replace Uvicorn raw-URL access logs; Uvicorn system/startup messages keep their own format. See [HTTP observability learning notes](../docs/learning-notes/http-observability.md) for field selection and limits.

## Dependencies and verified versions

| Package                  | Verified version | Purpose                                            |
| ------------------------ | ---------------- | -------------------------------------------------- |
| PyJWT                    | 2.15.1           | Access JWT signing and signature/claim validation  |
| argon2-cffi              | 25.1.0           | Salted Argon2id password hashing                   |
| email-validator          | 2.3.0            | EmailStr syntax validation/normalization           |
| Alembic                  | 1.20.1           | Versioned database schema management               |
| SQLAlchemy               | 2.0.55           | PostgreSQL engine, pool, and ORM Session           |
| Psycopg / psycopg-binary | 3.3.6            | PostgreSQL driver with bundled binary dependencies |
| FastAPI                  | 0.162.0          | ASGI, routes, response schema, OpenAPI             |
| Pydantic                 | 2.14.2           | Response/settings validation                       |
| pydantic-settings        | 2.16.2           | Environment/dotenv loading (added in 1B)           |
| Uvicorn                  | 0.54.0           | ASGI server                                        |
| asgi-lifespan            | 2.1.0            | Startup/shutdown in async tests (added in 1B)      |
| HTTPX                    | 0.28.1           | ASGI HTTP tests                                    |
| Pyright                  | 1.1.414          | Static type checking (dev only; added in 1D)       |
| Pytest                   | 9.2.0            | Tests and fixtures                                 |
| Ruff                     | 0.17.3           | Formatting and lint                                |

Phases 5B/5C add no dependency, configuration or migration; revision stays 0003. Phase 5A added models and migration 0003 without dependencies. Phases 4A–4D added no dependency, model or migration changes; their revision stayed 0002. Phase 3D also required none. Phase 3C adds no dependencies; Alembic 0002 creates refresh families and token history. Phase 3B added PyJWT 2.15.1 without extra transitive dependencies or a migration. Phase 3A adds argon2-cffi 25.1.0 and email-validator 2.3.0; their new transitive dependencies are argon2-cffi-bindings 26.1.0, cffi 2.1.1, pycparser 3.12, and dnspython 2.9.1. Phase 3A needed no migration; revision stayed 0001 until 3C. Phase 2C added no dependencies or migrations. Phase 2A added SQLAlchemy 2.0.55 and Psycopg/Psycopg-binary 3.3.6, with transitive greenlet 3.5.6. Phase 1D added dev-only Pyright 1.1.414 with transitive nodeenv 1.11.1. Pyright uses Node.js; the verified runtime is the existing Node 22.22.3. Its Python wrapper can download Node if missing, a fallback not pinned by uv.lock. No dependencies changed in Phase 1C. Phase 1B installed transitive `python-dotenv` 1.2.4 and `sniffio` 1.3.1. The lockfile records the resolution. AnyIO already supplies asyncio pytest integration. PostgreSQL/SQLAlchemy behavior is verified below. Alembic 1.20.1 with Mako 1.4.3 and MarkupSafe 3.0.4 are now locked and verified. Worker/provider package compatibility remains later work.

## Verification

From `backend/`:

```bash
uv run --locked python scripts/check.py

# With real PostgreSQL integration tests (after starting postgres_test):
TEST_DATABASE_URL='postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test' \
  uv run --locked python scripts/check.py --integration

# Individual checks:
uv run --locked ruff check app tests scripts migrations
uv run --locked ruff format --check app tests scripts migrations
uv run --locked pyright --project pyproject.toml
uv run --locked pytest -q
```

From the root, run `uv run --directory backend --locked python scripts/check.py`. The script uses the current Python interpreter and an explicit backend working directory for every subprocess. It stops on the first failure without modifying source formatting. All checks target active `app`, `tests`, `scripts`, and `migrations`, excluding legacy drafts. Pyright uses standard mode and a Python 3.12 static target against the local `.venv`; tests actually run on Python 3.13.13. See [tooling learning notes](../docs/learning-notes/backend-checks.md) for the configuration and limits.

Current Phase 5C verification (3 November 2026): **845 passed** with real PostgreSQL; default checks **598 passed/247 skipped**. Ruff lint/format pass 118 files, Pyright zero errors/warnings. Added 68 ordinary and 23 PostgreSQL cases, replacing two obsolete refusal cases for condition/calculator (net +89). Verified typed equality/order/contains, finite bounded arithmetic, literal versus declared config references, chosen routes/merge inputs, actual skipped fields/events, nested conditions/early ends/same-target convergence, no unchosen runtime evaluation, static failures, concurrent opposite-route runs and rollback after a flushed skipped event. All earlier migration/auth/compiler/ownership/state tests remain green.

Real Uvicorn HTTP checks computed both branch results, persisted skipped attempts and a typed condition failure, and returned identical history across restart. Catalog/OpenAPI report six ready types and the unchanged 15 operations/12 paths. Private correlated logs and graceful shutdown passed; only Database used a disposable migrated test schema with process-local key. Development head remains 0003 with no drift; no private .env/development data read or change. See [branch execution notes](../docs/learning-notes/branch-execution.md).

Historical Phase 5B verification (3 November 2026): **756 passed** with real PostgreSQL; ordinary checks report **530 passed, 226 skipped**. Ruff lint/format pass 115 Python files; Pyright reports zero errors/warnings. Added 30 ordinary and 18 database cases for actual pure operations, exact input mappings, command/OpenAPI/auth/privacy, historical versions, unsupported graphs, archive/inactive/owner checks, failure history, independent concurrent requests, worker-thread/no-session computation and storage-write rollback/recovery. Existing migration/auth/compiler/lifecycle checks remain green.

Temporary real Uvicorn HTTP checks produced actual selected-field output and persisted failed runs, then verified identical history after server restart, 401/owner 404, catalog readiness, the 15-operation/12-path inventory, private request-correlated logs and graceful application shutdown. Database alone targeted an isolated migrated test schema; no development data or private .env was read/changed. Revision remains 0003 head with no drift. See [first runner notes](../docs/learning-notes/first-runner.md).

Historical Phase 5A verification (3 November 2026): **708 passed** with real PostgreSQL; ordinary checks report **500 passed, 208 skipped**. Ruff lint/format pass 108 Python files, Pyright reports zero errors/warnings, and locked offline synchronization passes. Added 97 ordinary and 51 PostgreSQL cases for transition matrices, JSON boundaries, owner/version/attempt scope, result/state constraints, rollback after event flush, stale cached rows, three independent-connection races, retention guards and populated migration round trips. Registration tests/current guides now match the existing 8-character minimum schema edit; no auth production code was changed in this increment.

Independent write/read Python processes verified fixture history, exact old version identity and ordered events across process exit. Those fixtures are persistence probes, not executed workflows. The additive local development upgrade reports **0003 (head)**, no drift, retained existing record identifiers and no inserted execution fixtures. No private .env was read or edited. See [execution persistence notes](../docs/learning-notes/execution-persistence.md) for results, limits and the next increment.

Historical Phase 4D verification on 2 November 2026: ordinary checks report **403 passed, 157 skipped**; the real PostgreSQL suite reports **560 passed**. Ruff lint/format pass 97 Python files, Pyright zero errors/warnings and locked offline synchronization passes. Added 82 ordinary cases and 13 integration cases: 59 compiler, 23 API contract and 13 PostgreSQL checks. Coverage includes topology/nested branches/merges/early ends, cycles/reachability/handles/degrees, strict schema/configs, dominator-based reference availability, literal path strings, stable frozen plans, bounded secret-free issues, source selection/ownership, immutable history, concurrent pointer advance, unchanged timestamps/status/pointer/versions and safe503 recovery. Prior migrations/auth/version/rollback/concurrency checks remain green. Independent maximum-size local probes passed; no production benchmark is claimed.

Live Uvicorn verified real register/login, current/candidate/history validation, owner denial, semantic failures without raw configs, unchanged workflow state, continued permissive draft saves, exact old snapshot reports across restart, archived inspection, 13 operations/ten paths, private logs/request IDs and graceful shutdown. Only Database targeted a disposable migrated test schema with a process-local key. Zero temporary schemas/public test tables remained. Temporary server/factory/scripts/test container were removed, development PostgreSQL retained, private .env untouched; revision at that historical check was 0002. See [the walkthrough](../docs/real-backend-walkthrough.md) for viewing your own data.

Previously in Phase 1C, real Uvicorn checks verified health, 404, 405/Allow, 422, safe 500, OpenAPI, matching IDs/statuses in JSON logs, and graceful startup/shutdown. Test-only smoke routes were defined outside the production app and removed afterward; the owned server was stopped.

Invalid settings include blank/oversized names, unsupported environments, invalid booleans/log levels, and production debug. Tests check errors without supplied invalid values. Dotenv precedence and directory independence use temporary files; tests do not read private local configuration.

HTTPX ASGITransport does not run lifecycle events automatically. Lifecycle tests use [asgi-lifespan](https://github.com/florimondmanca/asgi-lifespan) and pass `manager.app` to HTTPX. The exceptional-exit test enters the lifespan context directly: an exception inside a manager body does not itself request ordinary ASGI shutdown. HTTP 500 behavior is tested separately. Ordinary checks need no external services. Explicit integration tests require the isolated real PostgreSQL service and socket access.

Docker/socket integration checks needed permitted access outside the sandbox. The fake startup-failure unit test runs its fake operation inline, while integration tests exercise the actual worker-thread/database boundary. Ordinary checks run without PostgreSQL; --integration requires TEST_DATABASE_URL and refuses non-local, non-test databases and URL query overrides. Initial frontend API integration is implemented; provider, worker, browser UI verification and access-JWT-denylist completion are not claimed. Workflow CRUD, immutable history, validation and synchronous six-type pure-node run APIs with exclusive routing/skips are implemented and owner scoped. Retry/cancel/idempotency commands are implemented; recovery remains later work. Ordinary logout contract tests exercise a real worker thread, so this environment required permitted execution outside the sandbox even without a database. There is no remote CI configuration yet.

## Review and next increment

Next: **Phase 6B — transactional outbox and dispatcher**, then claims/leases, recovery and scheduled retries. Phase 5C exclusive routing and arithmetic are complete. Background workers, Groq and remaining frontend capabilities follow later. Initial frontend integration is complete; see [frontend notes](../docs/learning-notes/frontend-api.md).

Independent exercise: extend the branching example with a nested condition and early end while other routes share a merge. Predict and verify succeeded/skipped node sets for three inputs, then save a new version and confirm old results remain unchanged. Use your own test data; no solution is supplied.

See [execution persistence notes](../docs/learning-notes/execution-persistence.md), [workflow validation notes](../docs/learning-notes/workflow-validation.md), [node registry notes](../docs/learning-notes/node-registry.md), [workflow version notes](../docs/learning-notes/workflow-versions.md), [workflow metadata notes](../docs/learning-notes/workflow-metadata.md), [logout/ownership notes](../docs/learning-notes/logout-ownership.md), [refresh-session notes](../docs/learning-notes/refresh-sessions.md), [login/token learning notes](../docs/learning-notes/login-access-tokens.md), [registration learning notes](../docs/learning-notes/authentication.md), [repository learning notes](../docs/learning-notes/repositories.md), [PostgreSQL/session learning notes](../docs/learning-notes/sqlalchemy.md), [backend checks learning notes](../docs/learning-notes/backend-checks.md), [HTTP observability learning notes](../docs/learning-notes/http-observability.md), [configuration/lifespan learning notes](../docs/learning-notes/configuration.md), [FastAPI notes](../docs/learning-notes/fastapi.md), the [phase plan](../docs/backend-implementation-plan.md), and the [development log](../docs/development-log.md).

## Execution commands — Phase 5D

Run POST now accepts optional Idempotency-Key (1–128 ASCII letters/digits or . _ : -) and max_attempts (strict integer 1–3, default 1). Receipt/run/initial-event creation is atomic and serialized per owner. Matching commands return the current original run with 201/Location/no-store; changed commands under the key return 409. Keys are owner-scoped across workflow create/retry commands, stored as digests, retained without expiry and do not trigger recovery. Unkeyed POST remains a new run each time.

POST /runs/{run_id}/retry accepts JSON {} or max_attempts and an optional key. Only owned failed/cancelled pure runs can be retried; it creates a child using the exact original version/input, from the beginning. Original attempts remain unchanged. Active/succeeded/archived cases return 409; missing/unowned return 404. POST /runs/{run_id}/cancel locks the run, cancels all open attempts and records cancellation atomically. Repeated cancellation returns 200; other terminal states return 409. Computation may finish in memory, but cannot overwrite committed cancellation.

Automatic attempts retry only INTERNAL_FAILURE/DEADLINE_EXCEEDED for six explicitly pure types. Every failed attempt is retained; mapping/type/arithmetic errors do not retry. No backoff, worker, elapsed deadline enforcement, external partial replay or crash recovery is added. The frontend uses command keys, an attempt selector and actual retry/cancel actions. Browser visual QA remains pending. See [full contract and learning exercise](../docs/learning-notes/execution-commands.md).
