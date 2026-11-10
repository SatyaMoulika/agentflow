# Proposed backend architecture

Phase 6C groundwork adds queued-run claim leases and fencing primitives. Workflow execution remains synchronous; persisted progress, worker recovery, workflow outbox integration and asynchronous dispatch are not yet implemented. See [claim notes](../learning-notes/run-claims.md). Prior phase descriptions below are historical.

Phase 6B foundation: migration 0005 adds a durable outbox and leased dispatcher for transport probes. Workflow runs remain synchronous; worker claims/recovery and workflow dispatch remain next. See [outbox notes](../learning-notes/transactional-outbox.md). Earlier phase descriptions below are historical.

Phase 6A now verifies Redis/Celery transport with a separate payload-free probe worker; it does not dispatch workflow runs. Outbox, claims/leases and recovery remain future increments before Groq Phase 7. See [worker transport notes](../learning-notes/worker-transport.md).

Phase 5D complete, 4 November 2026: command receipts, bounded pure retries, whole-workflow retry lineage and cooperative cancellation are implemented and wired to the frontend. API 18 operations/15 paths; migration head 0004. Backend 905 tests, frontend 120 tests pass. Next is Phase 6 background dispatch/recovery. See [execution command notes](../learning-notes/execution-commands.md). Earlier snapshots below describe their historical increments.

Current status, 4 November 2026: initial frontend API integration was brought forward after backend Phase 5C. The active App uses src/api for real authentication, owned workflow editing/validation and execution history; earlier prototype modules described below remain unrouted reference code. GET /runs is implemented (16 operations/13 paths); migration head remains 0003. Backend 5D is next. See [frontend API notes](../learning-notes/frontend-api.md) and the [startup walkthrough](../real-backend-walkthrough.md). Browser visual QA remains outstanding.

Phase 0 target design, 30 October 2026. The [implementation plan](../backend-implementation-plan.md) tracks actual progress: the FastAPI foundation, PostgreSQL/session infrastructure, user/workflow/version mappings and migrations, and Phase 2C repositories/transaction contexts are implemented. Phase 3A now implements registration AuthService, Argon2id hashing, and the registration HTTP boundary on that foundation; see [registration notes](../learning-notes/authentication.md). Phase 3B adds login, fixed-algorithm access JWTs and current active user resolution; see [login/token notes](../learning-notes/login-access-tokens.md). Phase 3C implements durable refresh families and token history, atomic rotation/replay revocation, and Origin/bound-CSRF cookie defenses; see [refresh-session notes](../learning-notes/refresh-sessions.md). Phase 3D adds represented-family logout and authenticated workflow/version ownership dependencies, without public workflow CRUD; see [logout/ownership notes](../learning-notes/logout-ownership.md). Phase 4A adds owner-scoped metadata CRUD/archive with versionless draft creation and row-locked metadata mutations; see [workflow metadata notes](../learning-notes/workflow-metadata.md). Phase 4B adds bounded immutable draft-definition saves, expected-version 409/atomic rollback, initial versions and owner-scoped historical UUID reads; see [workflow version notes](../learning-notes/workflow-versions.md). Phase 4C implements authenticated node-contract discovery and strict configuration models for six initial types, with validate_config capability only and execution_ready false; see [node registry notes](../learning-notes/node-registry.md). Phase 4D implements authoritative read-only graph validation/compiler for the six initial contracts, with exclusive DAG topology, explicit merges, immutable plans and dominator-safe references; see [workflow validation notes](../learning-notes/workflow-validation.md). Phase 5A implements exact-version run/attempt/event models, owner-scoped repository operations, guarded revisioned state transitions and atomic ordered metadata events in migration 0003; see [execution persistence notes](../learning-notes/execution-persistence.md). Phase 5B adds synchronous exact-version manual/transform/end execution and owned run POST/item GET, with computation outside short transactions, actual result/failure/attempt history and current executor readiness; see [first runner notes](../learning-notes/first-runner.md). Phase 5C now implements typed condition/calculator operations, exclusive selected-route traversal, chosen-predecessor merge behavior and atomic skipped history at successful completion; see [branch execution notes](../learning-notes/branch-execution.md). Remaining run commands, leases/checkpoints, remaining tables, workers, and provider flows below remain proposals. The synchronous POST currently returns 201; 202/outbox/worker behavior below belongs to Phase 6. [The real backend walkthrough](../real-backend-walkthrough.md) explains the connected frontend and real persistence and lists remaining work.

## Processes and responsibilities

```text
React frontend
    │ HTTPS / versioned JSON / authorized SSE
    ▼
FastAPI routers → application services → pure domain rules
    │                   │                      │
    │                   ▼                      └─ graph/compiler/state-machine logic
    │           repositories and transaction boundary
    │                   │
    │                   ▼
    │              PostgreSQL
    │         definitions, versions, runs, attempts,
    │         approvals, ordered events, outbox
    │                   │
    │              outbox dispatcher
    │                   ▼
    │            Redis → Celery workers
    │                        │
    │                 deterministic DAG engine
    │                        ├─ pure registered nodes
    │                        ├─ Groq/local model adapter
    │                        ├─ controlled HTTP/tool adapters
    │                        └─ LangGraph agent node/checkpoints
    │
    └─ SSE reads durable events; Redis notification is only an optional wake-up

API + workers → OpenTelemetry → optional Phoenix
```

The processes use one modular codebase and the same domain model. Separating a worker process keeps long executions out of an HTTP request; it does not create another independently owned service.

The main distinction is between **where work runs** (Celery), **which workflow step is allowed next** (the deterministic engine), and **how an agent chooses tools internally** (LangGraph). The LLM has no authority to bypass the registered executor and permission checks.

## Modules and dependency direction

Use the brief's `backend/app/` layout, creating files only as the owning increment is implemented:

| Location/module                     | Responsibility                                                                      |
| ----------------------------------- | ----------------------------------------------------------------------------------- |
| `app/main.py`, `api/router.py`      | Application factory, lifecycle and route composition                                |
| `api/v1/` and `api/dependencies.py` | HTTP schemas, auth dependencies, services and error mapping                         |
| `core/`                             | Validated settings, security primitives, logging, exceptions and telemetry          |
| `modules/auth/`                     | Registration, passwords, access tokens, refresh session rotation/revocation         |
| `modules/workflows/`                | Ownership, metadata, immutable version saves, definition validation and compilation |
| `modules/nodes/`                    | Available type registry, type-specific schemas, bounded executor interface          |
| `modules/executions/`               | Run/node state machines, graph progress, retry policy, dispatch and cancellation    |
| `modules/agents/`                   | Planner prompts, model provider boundary, LangGraph agent construction              |
| `modules/connections/`              | Owned connection metadata, secret references and destination restrictions           |
| `modules/approvals/`                | Assignment, decision authorization, expiry and durable resume                       |
| `modules/observability/`            | Durable events, run/node metrics, replay and redacted telemetry                     |
| `infrastructure/database/`          | SQLAlchemy engines, session factories and DB adapters                               |
| `infrastructure/queue/`, `workers/` | Celery application, dispatcher and task entry points                                |
| `migrations/`, `tests/`             | Alembic schema history and executable module verification                           |

Routers call services; services own transaction boundaries and call repositories; repositories query PostgreSQL. Domain rules return domain results/errors and do not import FastAPI, SQLAlchemy, Celery or LangGraph. Interfaces are introduced only where there is a real boundary: repositories needed by pure services, executor contracts, queue dispatch, provider calls and telemetry. Do not create a generic base repository or a full interface/class tree for every function.

### Initial concurrency/session recommendation

Start with SQLAlchemy 2.x synchronous `Session` units of work and a supported PostgreSQL driver. Synchronous FastAPI `def` handlers use its thread-pool execution model; Celery workers use their own sessions. Each service operation creates/closes a session in the thread/process that uses it. ORM entities/sessions never cross a task/thread boundary. Agent/provider calls are bounded and happen outside an open database transaction.

SSE handlers are asynchronous and must send heartbeat/wait without blocking the event loop. Their short database reads execute in a thread-pool function that creates and closes its own synchronous session; never hold a transaction for the stream's lifetime. An all-async API with `AsyncSession` is a reasonable later alternative, but combining that with synchronous Celery requires distinct lifecycle/session rules. We should learn and verify one transaction model first.

This choice uses FastAPI's supported sync/async separation and SQLAlchemy's session-per-concurrency-unit guidance. [FastAPI concurrency](https://fastapi.tiangolo.com/async/), [SQLAlchemy sessions](https://docs.sqlalchemy.org/en/20/orm/session_basics.html).

## Versioning and validation

A workflow row is mutable metadata; a workflow-version row is an immutable saved definition. A run points at one exact version. Updating a workflow never changes a running execution. Save uses an expected current version (optimistic concurrency); a stale save is 409 rather than a silent overwrite.

The schema 1.0 definition preserves the current node type IDs and explicit edge handles. Positions and labels are editor metadata retained for round-tripping; the compiler does not execute them. Validation checks typed configs, node uniqueness, input mappings, authorization, owned connections, supported cycles/branches, completion paths and complexity limits. Draft saves can preserve incomplete configuration; only validated definitions can be compiled for execution. The authoritative check runs again before starting a run.

MVP topology is sequential steps and exclusive branches with reconvergence, not parallel fan-out. `merge` joins the chosen route; conditions/approvals select one labeled edge. Parallel scheduling and loops need new explicit semantics later.

## Deterministic executor boundary

Recommend a small typed execution context containing `run_id`, `node_id`, attempt, actor/permission context, cancellation/deadline checks, allowed connections and trace context. An executor accepts validated node-specific configuration and resolved input, and returns structured output/metadata or a classified domain failure. This improves on passing arbitrary dictionaries because cancellation, authorization and retry decisions need an explicit owner.

Add that context when the first real executor requires it. Pure transform/condition/calculator functions remain ordinary functions. No `eval`, unrestricted Python expression, shell command or arbitrary filesystem executor is introduced.

The engine owns scheduling and graph routing. A node executor cannot change another node's persisted state or invent new authorized capabilities. Tool arguments returned by a model go through exactly the same executor validation boundary.

## Transaction and recovery flows

### Create or save a workflow

```text
Authenticated request → typed DTO → ownership/version check
→ validate definition structure → begin transaction
→ insert immutable workflow version → update current-version pointer
→ commit → serialize response
```

Do not keep the transaction open while planning with an LLM. Generated workflows are proposals, not automatically persisted, activated or executed. Reviewed modifications must identify their base version before applying.

### Start and execute a run

```text
Authenticated request + Idempotency-Key
→ load owned exact version → compile/authorize
→ transaction: run + initial event + idempotency record + outbox entry
→ commit → 202 response
→ dispatcher publishes outbox → worker claims persisted run lease
→ resolve next node → transaction: create attempt + started event
→ release DB transaction → execute bounded node operation
→ transaction: result/status + event + next progress
→ complete, fail, retry later or pause
```

Phase 5 initially uses the same services in a controlled in-process vertical slice. It proves state semantics, not durable queue delivery. Phase 6 replaces dispatch, not the domain engine.

The outbox solves the DB-commit/broker-publish gap. It does **not** make delivery exactly-once: a publisher can crash after enqueueing but before marking an outbox row delivered. Worker claims, row locks/leases and idempotent operations handle duplicates. Celery delivery/acknowledgement settings require crash tests; `acks_late` alone is not a correctness proof. [Celery task semantics](https://docs.celeryq.dev/en/stable/userguide/tasks.html).

Store run progress and claims in PostgreSQL, including current attempt, next work, lease owner/expiry and cancellation request. Short transactions protect claims/state transitions. Renew leases for long operations; fence stale workers from committing results after takeover. A stale worker may already have sent an external request, so fencing database writes is not enough to guarantee safe external effects.

For side-effecting tools, use a stable logical-operation idempotency key when the destination supports it. After an ambiguous timeout or crash, reconcile the external result or require review; never blindly repeat an unsafe request. Pure-node retries can use bounded exponential backoff. Long backoff waits and human review release worker capacity and are rescheduled durably.

### Approval pause/resume

```text
Approval node → transaction: pending request + waiting run + event → worker exits
Decision HTTP request → authorize assigned approver → lock pending approval/run
→ transaction: decision + saved resume state + event + resume outbox
→ commit → worker resumes the saved version and selected route
```

An approver must be an active authorized user. MVP assignment is restricted to the workflow owner until shared-workspace ACLs exist; free-text display names are not identities. A user cannot assign an unrelated user to gain access to their data. A scheduled expiry task uses the same locked transition path. Two concurrent decisions have one winner; cancellation/expiry prevents resumption. Rejection follows the rejected edge; successful execution of that branch can still be a `succeeded` run with a rejected business outcome.

### LangGraph checkpoints

LangGraph manages the internals of an agent node, not application workflow runs. Persist resumable agent state in separate checkpoint tables/schema. Record a stable thread ID correlated to the application run, node and invocation/attempt. Crashed invocation recovery reuses that thread; a deliberate new invocation is distinct. Application records remain the source for ownership, approvals and the UI.

Persistent checkpoints support interrupted agent continuation; external effects still need idempotency/reconciliation. Do not rerun side effects merely because agent code before an interruption is replayed. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence).

## Events and telemetry

Application events are database records that power history and SSE; OTel spans are operational diagnostics. Neither substitutes for the other. Persist state and its event atomically, and notify clients only after commit. SSE supports authorization, ordered IDs, replay with `Last-Event-ID`, heartbeats and resynchronization after retention. Redis Pub/Sub may wake streams but cannot replace replay storage.

Allocate a per-run event sequence while holding the run-row lock. A global auto-increment event ID alone does not guarantee commit order across concurrent transactions. The cursor is per run; `(run_id, sequence)` is unique and indexed. A reconnect must never advance beyond an uncommitted event and miss it permanently.

Propagate W3C trace context through outbox/Celery headers into execution/node/LLM/tool spans. Approval continuation links to the decision request while retaining correlation to the original run. Do not leave database transactions, worker slots or request spans open during human waiting. Measure wall-clock run duration and active compute duration separately.

Token counts/model IDs come from provider metadata when available; do not fabricate missing usage, costs, span IDs or retries. Do not export hidden reasoning, credentials or raw document/prompt payloads by default. Phoenix is optional: export failures are bounded/logged, and an exporter outage does not fail business execution.

## Authentication and external access

Recommend short-lived JWT access tokens held in browser memory and a rotated, opaque refresh token in a Secure/HttpOnly cookie. Store only its hash/server session metadata, revoke the family on detected reuse, and validate JWT signature, algorithm, issuer, audience and expiry. Browser cookies need explicit Origin/CSRF protections, SameSite and exact credentialed CORS. Local HTTP development uses a deliberate dev cookie configuration; production requires HTTPS.

Authenticated SSE should use a fetch-based streaming client with Authorization headers and an abort/reconnect policy. Native `EventSource` cannot simply accept custom Authorization headers; do not place long-lived JWTs in query strings.

HTTP executors allow only configured destinations, verify resolved IPs, reject loopback/private/link-local/metadata targets, and revalidate every redirect. Validate the actual connection destination to address DNS rebinding, bound payloads/timeouts/response sizes, and redact credentials. Connection records store secret references; a deployment-owned encryption key or secret manager holds the secret material. Groq's initial workspace API key is server configuration, not a browser connection field.

## Package and deployment policy

Target Python 3.12+, FastAPI/Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL and a supported driver. Add JWT/Argon2 in Phase 3, Redis/Celery in Phase 6, OpenAI-compatible SDK in Phase 7, LangGraph/checkpointer in Phase 8 and telemetry/exporter packages when their owning increments begin. Ruff, Pyright, Pytest and HTTPX are development tools.

Exact versions and image tags/digests are chosen and locked during each owning phase after compatibility tests. The draft lockfile is not evidence of stack-wide compatibility. Document the selected Python/driver/ORM versions, broker/worker versions, LangGraph/checkpointer pair and Phoenix/exporter contract. The app must work without Groq credentials until model features are enabled, and without Phoenix throughout.
