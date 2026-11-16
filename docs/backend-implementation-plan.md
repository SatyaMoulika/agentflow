# Backend implementation plan

## Current status — 16 November 2026

This section is the authoritative phase status. The original design sequence below remains the roadmap; detailed historical snapshots live in the development log rather than competing current-status notices.

| Phase | Status                          | Scope and remaining work                                                                                                                                                                                                                               |
| ----- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1–5   | Implemented and verified        | Foundation, PostgreSQL, auth/ownership, immutable workflows, compilation, deterministic execution, retries, cancellation and command idempotency.                                                                                                      |
| 6     | Implemented for pure workflows  | Redis/Celery, durable outbox, claim leases/fences, recovery discovery, heartbeats and scheduled retries. External calls are excluded from automatic replay/recovery.                                                                                   |
| 7     | Scoped implementation complete  | Groq LLM, reviewed generation/version-bound edits, classify/extract, JSON parsing, protected fixed-endpoint HTTP GET, encrypted optional credentials, provider failures/usage and authorized connection selection. Browser acceptance remains pending. |
| 8     | 8A/8B and scoped 8C implemented | Bounded LangGraph calculator/authorized HTTP tools and persistent checkpoints with explicit continuation at saved post-tool pauses. Unknown in-flight external calls are not automatically recovered.                                                  |
| 9     | Partial                         | Authenticated SSE replay/reconnect/heartbeat and polling fallback exist. Fixed-name in-process trace instrumentation is in place; cross-process correlation and Phoenix export remain.                                                                 |
| 10    | Pending                         | Durable approval, authorization/expiry and safe resume/reconciliation.                                                                                                                                                                                 |
| 11    | Partial                         | Real auth, workflow editor, integrations and run history are wired. Approval UI, browser/security/performance acceptance and deployment hardening remain.                                                                                              |

Current source and local development migration head is **0012**. Gmail connection tables were added on 13 November 2026; Alembic reports no metadata drift. The checkpoint schema was set up on 12 November. No fixtures or destructive tests were run against development.

Verification on 16 November 2026: the complete backend checker passed **1,390 tests** with isolated PostgreSQL/Redis, Ruff lint/format and Pyright; frontend checks passed **146 tests**, lint, TypeScript and production build. No live Google/Groq call or browser acceptance check was performed for this snapshot. The earlier synthetic live HTTP agent fetched two slides, used the calculator to produce **20**, replayed the committed command without external calls and refused a fresh run after revocation. Only a disposable test schema was used and removed. See [verification](verification.md) for commands and limits, and the [sample review](learning-notes/http-agent.md) for the exact flow.

Operational setup is in the [real-data walkthrough](real-backend-walkthrough.md). Broader HTTP methods, OAuth for additional providers, credential rotation and side-effect reconciliation are future expansion. No paid provider fallback is configured.

The requested Gmail integration has a [separate incremental plan](gmail-implementation-plan.md). Owner-bound read-only OAuth connection setup and manual message reading are available but need Google project configuration and live verification; automatic triggers, approvals and Gmail actions remain to be implemented.

## Historical repository findings at Phase 0

- React/TypeScript frontend with normalized workflow, execution, approval, and integration types in `src/types/index.ts`.
- Local registry/configuration schemas in `src/lib/node-registry.ts`, graph validation in `src/lib/graph.ts`, and deterministic frontend generation/execution services.
- Zustand owns local mock state; its mutations return synchronously. TanStack Query currently loads a mock dashboard, not a backend resource.
- The last frontend verification recorded 71 passing tests, TypeScript, lint, formatting, and production build. These are frontend results; they do not validate a backend. Browser QA remains outstanding.
- `backend/agentflow/` contains unintegrated SQLite/JSON and in-process runner drafts. They lack the requested PostgreSQL ORM, migrations, auth, service separation, and worker architecture. They are **reference material, not the implementation baseline**. Do not extend or present them as complete modules.
- The existing Python lockfile/environment was created for those drafts; it is not an approved dependency set. The shell Python is 3.12.3 and the draft uv environment uses 3.13.13. Phase 1 must choose and pin one supported development interpreter.
- Docker, Docker Compose, and a PostgreSQL client binary are available. The database server, Docker daemon access, Redis connectivity, and Groq account permissions have not been verified. A Redis CLI is not required if Redis runs in Compose.

## Proposed decisions

1. Modular monolith: one codebase, FastAPI process, Celery worker process(es), PostgreSQL, Redis, optional Phoenix.
2. PostgreSQL + SQLAlchemy 2.x + Alembic from the database phase onward. No SQLite substitute for integration tests.
3. A deterministic domain engine controls the outer DAG. LangGraph is restricted to agent nodes.
4. PostgreSQL owns workflow versions, runs, attempts, approvals, and replayable events. Redis transports work and transient notifications.
5. Groq through an OpenAI-compatible provider adapter; model ID, endpoint, and key remain backend configuration. No paid provider fallback.
6. Keep existing frontend node identifiers (`manual`, `llm`, `extract`, etc.) as canonical identifiers for schema 1.0. Treat the longer identifiers in the brief as illustrative, not a second incompatible registry.
7. Introduce a typed snake_case API contract with a narrow frontend adapter at the integration phase. Lowercase serialized statuses match the existing UI. Arbitrary business JSON keys are never case-converted.
8. JWT access tokens, rotating/revocable refresh sessions, Argon2 password hashes, ownership checks, and explicit approver authorization. Browser token delivery and SSE authentication are designed together.
9. One PostgreSQL transaction owns each state change and its corresponding event. Queue publication becomes reliable through a transactional outbox in Phase 6.
10. Do not create all proposed folders or install the complete stack at once. Add each dependency with its owning module.

These baseline decisions are explained in the linked architecture and ADRs. The registry now uses the exact canonical types published by the active backend; earlier frontend aliases are prototype references.

## Implementation sequence and working checks

Each phase is split into the small increments below. Complete one increment's test and review before starting the next; completing a phase does not mean generating all its files in one pass.

| Phase                                       | Manageable increments, in order                                                                                                                                                                                                                                                             | Observable completion check                                                                                                                                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **0. Architecture**                         | Repository/contracts review; ER design; API inventory; Groq research; risks/prerequisites                                                                                                                                                                                                   | Planning documents agree on IDs, ownership, state, transactions, and execution responsibilities; architecture reviewed before coding                                                                                                         |
| **1. Backend foundation**                   | 1A application factory and `/api/v1/health`; 1B validated settings and startup/shutdown; 1C request IDs, structured logging, consistent errors; 1D Ruff/Pyright/Pytest                                                                                                                      | Fresh environment starts the API; HTTPX tests exercise health, validation, and sanitized errors; logs correlate request IDs; no DB, Redis, or model required                                                                                 |
| **2. Database foundation**                  | 2A Compose PostgreSQL + SQLAlchemy session lifecycle; 2B users/workflows/versions migrations; 2C repository/UoW transaction tests; add later tables with their owning modules                                                                                                               | `alembic upgrade head` works on an empty real PostgreSQL DB; rollback/re-upgrade and constraints pass; no `create_all()` migration shortcut                                                                                                  |
| **3. Authentication**                       | 3A register + Argon2; 3B login/access JWT + `/auth/me`; 3C refresh sessions/rotation/reuse detection; 3D ownership dependencies and logout proposal                                                                                                                                         | Correct/incorrect/expired credentials tested; two users cannot read each other's objects; revoked/replayed refresh credentials fail                                                                                                          |
| **4. Workflow management**                  | 4A CRUD/archive; 4B immutable saved definitions + optimistic concurrency; 4C node registry and typed configuration; 4D authoritative validation/compiler                                                                                                                                    | User creates, edits, validates, and retrieves a workflow; old versions remain unchanged; concurrent stale save returns 409; invalid graphs never compile                                                                                     |
| **5. Deterministic execution**              | 5A run/node-attempt/event tables + state transitions; 5B manual → predefined transform → end; 5C condition + calculator; 5D failures/cancellation/idempotency/bounded pure-node retries                                                                                                     | API-triggered run produces actual persisted results; selected branch runs, other branch is skipped; retry attempts and events agree; restart history survives. Controlled in-process runner only at this phase                               |
| **6. Reliable background work**             | 6A Redis/Celery transport; 6B outbox + dispatcher; 6C run claims, leases, recovery/reconciliation; 6D retry scheduling                                                                                                                                                                      | API returns 202; worker executes; kill/restart and duplicate delivery tests pass; broker failure after DB commit does not lose a run; work is not claimed exactly-once                                                                       |
| **7. Groq generation and controlled tools** | 7A provider capability/timeout/rate-limit adapter; 7B LLM node; 7C registry-based workflow planner and review-only proposal; 7D version-bound edit proposals; 7E connections/secrets + SSRF-safe HTTP executor; 7F classify/extract/text-parser support as explicit registered capabilities | One optional live Groq smoke test produces a schema/graph-valid proposal and a real LLM result. Mocked tests cover bad JSON, unavailable models, timeouts and 429s. Unknown/unauthorized tools and private-network HTTP targets are rejected |
| **8. LangGraph agent nodes**                | 8A typed state and bounded read-only calculator tool loop; 8B authorized HTTP tool; 8C persistent checkpointer and recovery correlation                                                                                                                                                     | Agent can select a permitted tool, consume its result, and finish; invalid arguments/unknown tools/iteration exhaustion fail visibly; interrupted agent resumes with its thread mapping                                                      |
| **9. Observability and SSE**                | 9A extend initial trace hooks to API/dispatch/worker/node/LLM/tool spans; 9B Phoenix export/redaction; 9C authorized event replay, heartbeat, reconnect and ordering                                                                                                                        | Traces correlate API and worker; SSE reconnect returns committed events after the cursor; no gaps under concurrent writers; Phoenix outage does not fail execution                                                                           |
| **10. Human approval and recovery**         | 10A approval request + release worker; 10B authorized decision/expiry; 10C outbox resume and crash recovery; 10D side-effect ambiguity/reconciliation                                                                                                                                       | Pause, restart processes, then approve/reject; correct branch continues once; simultaneous decisions have one winner; expired/cancelled approval cannot revive a run                                                                         |
| **11. Frontend integration and hardening**  | 11A explicit API mode and asynchronous state adapters; 11B real auth/workflow CRUD; 11C runs/SSE/approvals; 11D browser/security/performance checks; 11E final Compose/documentation                                                                                                        | Register → create/generate → edit/version → run → approve → inspect real results; both users' boundaries hold; full stack starts with documented commands                                                                                    |

`end` is a necessary structural node even though the brief's ordered list focuses on eight substantive executors. LLM is introduced before controlled HTTP, then agent, then approval. Unsupported frontend samples remain unavailable in backend mode until their executors genuinely exist.

Compose can be introduced incrementally for PostgreSQL in Phase 2, Redis in Phase 6, and Phoenix in Phase 9; Phase 11 verifies the complete stack. Initial request IDs and telemetry correlation are added early; Phase 9 completes the tracing experience. Durable execution events start in Phase 5, not only when SSE is added.

## Verification policy

- Unit tests: domain invariants, graph compilation, mapping, conditions, state transitions, retry eligibility, authorization decisions.
- PostgreSQL integration tests: constraints, rollback, immutable versions, concurrent updates/approvals, ordered events and outbox atomicity. Use an isolated test database with Alembic.
- Queue integration tests: a real Redis broker and a real Celery worker; eager-mode tests alone cannot prove recovery or broker behavior.
- API tests: HTTPX against the app, covering success, ownership, validation, pagination, errors, idempotency, and token lifecycle.
- Provider tests: deterministic HTTP fixtures/fakes by default; live Groq is a separate opt-in check with an account key, never a prerequisite for CI.
- End-to-end tests: separate services; worker restart, approval restart, duplicate deliveries, redelivery after a side effect, and unavailable telemetry.
- Run relevant tests after each increment and report actual output. Do not claim model calls, worker recovery, browser behavior, or deployment without evidence.

## Learning/review format for each increment

Before implementation: identify requirements, module owner, proposed files, dependencies and their purpose, request flow, transaction/migration changes, API shape, failure cases, and tests. Explain new concepts before introducing them.

After implementation: show the small diff, explain each file/function and important library calls, show the observable request flow, run the tests, document limitations and the next increment, then offer one small exercise. Use 3–5 knowledge-check questions across the review, one at a time during interactive learning. Do not publish the exercise solution before an attempt.

## Current prerequisites and next increment

- Keep the existing private database, signing, Groq and optional connection-encryption settings; never commit their values.
- Use only the guarded PostgreSQL/Redis test services for integration fixtures and migration round trips.
- Browser acceptance remains outstanding: the browser access host was retried on 10 November 2026 and is unavailable.
- **8A–8C** implements bounded LangGraph tools and durable state with explicit continuation at saved post-tool boundaries. See the [HTTP agent sample](learning-notes/http-agent.md) and [checkpoint guide](learning-notes/agent-checkpoints.md). External calls remain synchronous with no automatic replay of uncertain requests.

Historical increment results and learning exercises are retained in the [development log](development-log.md) and individual [learning notes](learning-notes/provider-integration-hardening.md).

## Related design documents

- [Backend architecture and request flows](architecture/backend-architecture.md)
- [Database ER diagram](database/er-diagram.md)
- [Schema, constraints and transaction boundaries](database/schema.md)
- [API inventory and frontend contract alignment](api/endpoints.md)
- [Groq provider plan](architecture/groq-provider.md)
- [Modular monolith decision](decisions/ADR-001-modular-monolith.md)
- [PostgreSQL decision](decisions/ADR-002-postgresql.md)
- [Execution ownership decision](decisions/ADR-003-workflow-engine.md)
