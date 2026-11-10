# Phase 5A — durable runs, node attempts and ordered events

Current follow-on: [Phase 5C branch execution](branch-execution.md) implements all six pure types, selected-route merges and atomic skipped completion history. Scope/results below record the original 5A storage increment.

Implemented 3 November 2026. This increment adds PostgreSQL execution-history storage and guarded lifecycle transitions. It does not run workflow nodes, expose run HTTP endpoints, schedule retries, dispatch workers or resume approvals. Fixture transitions in tests demonstrate persistence; they are not real automation results.

## Why three tables

A workflow version is an immutable definition. A workflow_run records one requested execution of one exact version, including its input and lifecycle. A node_run records one node attempt within that run. A retry is a new attempt row, preserving the old failure. execution_events records ordered changes for later history/SSE; it is append-only.

Migration **0003** adds these tables after 0002. It adds no columns or row writes to users, workflows, workflow_versions or refresh tables. Existing account/session/workflow data remains in place. New execution tables start empty in development; no demo runs/results are seeded. No new dependency, environment variable, provider key, API route or frontend change is required. The API remains 13 operations across ten paths and node execution readiness remains false.

| Table            | Implemented data and invariants                                                                                                                                                                                                                                                                                        |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| workflow_runs    | UUID ID, workflow/exact version, optional parent run, manual trigger, status/revision/event counter, input/output JSON, bounded failure code, created/updated/start/completion timestamps. Composite FKs require version and parent lineage to belong to the same workflow; a parent also uses the same exact version. |
| node_runs        | UUID ID, containing run, saved node ID, positive attempt number, status/revision, input/output JSON, failure code, timestamps and nonnegative wall-clock duration. Unique run/node/attempt and a partial index allowing only one open attempt for each run/node.                                                       |
| execution_events | Global bigint identity, run ID, optional same-run node-attempt ID, positive per-run sequence, one of four event types, metadata payload and creation timestamp. Unique run/sequence and a composite FK prevent cross-run attempt references. Node events require an attempt ID; run events do not accept one.          |

All business-history FKs restrict deletion. SQL triggers prevent ordinary run/attempt DELETE/TRUNCATE and all event UPDATE/DELETE/TRUNCATE. Another guard freezes each run's workflow/version/parent/input and each attempt's run/node/number/input. Attempts must name an actual string node ID in the run's saved definition, including through direct SQL; advancing the workflow's current pointer never changes that membership.

The schema records manual trigger only. Lease/checkpoint/outbox/idempotency/cancellation-request/telemetry/approval features arrive with their owning increments. Status revision is not a lease-generation fence, and the presence of a waiting_approval enum value does not implement an approval service.

## State and result rules

| Run state                      | Allowed next states                            |
| ------------------------------ | ---------------------------------------------- |
| queued                         | running, failed, cancelled                     |
| running                        | waiting_approval, succeeded, failed, cancelled |
| waiting_approval               | running, failed, cancelled                     |
| succeeded / failed / cancelled | none                                           |

| Attempt state                            | Allowed next states                            |
| ---------------------------------------- | ---------------------------------------------- |
| pending                                  | running, skipped, failed, cancelled            |
| running                                  | waiting_approval, succeeded, failed, cancelled |
| waiting_approval                         | running, succeeded, failed, cancelled          |
| succeeded / failed / skipped / cancelled | none                                           |

A repeated same-state request is not a transition. Failed attempts cannot return to running; adding another attempt allocates the next number while holding the containing run lock. Existing attempts after success/skip/cancellation cannot be retried through this repository. Retry eligibility, automatic backoff and public retry/idempotency commands remain later work. Parent-run linkage stores identity only; retry endpoint authorization/eligibility is not implemented.

New runs start queued/revision 0; attempts start pending/revision 0 in a running run. Each status transition advances that row's revision by one. The caller supplies the expected revision; a stale value raises static ExecutionConflictError. Attempt mutations also check the containing run revision. This catches a stale writer even when running → waiting_approval → running returns to the same status. SQL triggers independently reject illegal transitions and wrong revision increments.

Running/waiting requires a start timestamp; terminal states require completion. A successful result requires a JSON object and no failure code. Failure requires a code-owned FailureCode (EXECUTION_FAILED, INPUT_MAPPING_FAILED, DEADLINE_EXCEEDED or INTERNAL_FAILURE), with no successful output. Other states retain neither output nor failure code. No raw exception message is persisted. Start time is preserved through wait/resume; skipped/pre-start-cancelled attempts have no start and zero duration. Duration measures elapsed wall time, including waiting, not CPU time. PostgreSQL clock_timestamp supplies execution timestamps, including actual insertion times rather than transaction-start timestamps.

Repository run completion refuses open attempts. Success also requires a succeeded end attempt from the saved version and no failed/cancelled latest attempt; an old failed attempt can coexist with its succeeded retry. Waiting requires a waiting attempt and no running attempt. These are consistency checks, not a scheduler: the Phase 5B runner must still compile/authorize the exact version, select the correct route and ensure all required work really executes.

Backend attempt status includes cancelled, which the current demo frontend union does not yet represent. The eventual API adapter must handle it explicitly rather than silently display failure. No frontend contract was changed during this storage increment.

## Transactions, ownership and event ordering

ExecutionRepository never commits. Call each mutation inside Database.unit_of_work and let failures escape it:

```python
with database.unit_of_work() as session:
    repository = ExecutionRepository(session)
    repository.transition_run(
        run_id=run_id,
        owner_id=authenticated_user_id,
        expected_revision=0,
        target=RunStatus.RUNNING,
    )
```

This is an internal persistence example, not a public run-start API. A later service owns compilation and command authorization. Run ownership is derived by joining workflows.owner_id, never from input JSON or an exposed owner field. Reads, row locks, mutations, attempt membership and event paging are owner scoped. Missing/unowned resources raise the same static ExecutionNotFoundError. Archived workflows reject new run records; existing records remain readable and are not automatically cancelled by archive.

Every mutation appends one of run.created, run.status_changed, node.created or node.status_changed. Payloads contain only code-owned status/attempt metadata; raw inputs, outputs and exception messages are excluded. Inputs/outputs are stored in their owning rows, with future capture/retention/access rules still needed before broader tooling. Their arbitrary JSON can itself be sensitive; storage does not guess how to redact every business field.

The repository locks the run first, then an attempt when needed, refreshes cached state, validates revisions, applies the mutation, increments event_sequence and inserts the event in the same transaction. Event flush failures roll back status, revision, input/attempt creation, timestamp and event counter together. A caller must not catch an operation failure and commit a partially completed unit of work.

All cooperating writers for a run serialize on its row lock. The next committed event therefore follows the prior committed sequence. Rollback leaves no committed cursor gap. The global event identity may have gaps after rollback and is not the per-run replay cursor. events_owned accepts a nonnegative after_sequence and bounded limit (1–1000), returning ordered rows; SSE and an HTTP event endpoint are not yet implemented.

Database constraints/guards protect identities, membership, states, context, unique sequences and existing history. The obligation to append an appropriate event with each business mutation belongs to the repository/unit-of-work boundary; raw privileged SQL is not a substitute for it. There is no claim that arbitrary administrative status/counter writes automatically synthesize valid audit events.

## Payload and schema boundaries

copy_payload accepts JSON objects with native JSON values, string keys, finite numbers, depth at most 32 (root 0) and compact UTF-8 encoding at most 262144 bytes. A JSON round trip creates independent snapshots, preserving key case and scalar types. Unknown Python values, invalid Unicode, non-object roots and oversized payloads raise a static InvalidExecutionPayloadError. SQL object checks add a 1 MiB textual JSONB ceiling for direct writers; this allows PostgreSQL's added formatting while the repository keeps the tighter compact limit. These are storage bounds, not transport/rate limits.

State guards use schema-qualified related-table queries based on TG_TABLE_SCHEMA and bound data parameters. They work for production public tables and independently pooled test connections using schema_translate_map, without depending on the connection's current search path. Runtime sessions/ORM objects still belong to one thread/transaction; no ORM entities cross process boundaries.

## Files and functions

- modules/executions/state.py defines lowercase RunStatus/NodeStatus, static FailureCode/EventType enums and explicit immutable transition maps. require_run_transition/require_node_transition reject unsupported edges, no-ops and terminal reopening.
- models.py maps WorkflowRun/NodeRun/ExecutionEvent with composite same-version/same-run FKs, legal-state/payload/timestamp/result checks and indexes. WorkflowRun.version is view-only and pinned to the immutable definition; relationships allow history inspection without ORM delete cascades.
- payloads.py validates and copies bounded native JSON objects. exceptions.py defines static missing/conflict/result outcomes. No execution HTTP error handlers are added before execution endpoints exist.
- repository.py implements create_run, owner-scoped get/lock, guarded run/attempt transitions, append-only attempt allocation and cursor paging. Private _event updates the locked counter and flushes one metadata event. Latest-attempt queries refresh cached ORM rows before consistency decisions; _version_nodes uses the exact saved version rather than the mutable current pointer.
- infrastructure/database/models.py registers the new mappings for Alembic. migrations/versions/0003_execution_history.py contains static reviewed DDL plus lifecycle/membership/retention/event guards. It does not import current application models at migration time. Downgrade explicitly removes the new history tables/functions; it is destructive to execution history and is tested only in disposable storage.
- tests/unit/test_execution_state.py exercises all run/attempt transition pairs; test_execution_payloads.py checks copy/type/byte/depth boundaries. Integration execution repository/migration tests cover real history, rollback, constraints, ownership, frozen version identity, independent connection races, cached-state refresh and populated 0003 → 0002 → 0003 migration. Existing ORM/full migration inventories include the new tables.

## Actual verification — 3 November 2026

The full backend checker passed **708 tests** against PostgreSQL 16.14. Ordinary checks passed **500**, with **208** explicit PostgreSQL cases skipped. Ruff lint/format passed all 108 active Python files, Pyright reported zero errors/warnings, and locked offline dependency synchronization passed. This increment adds 97 ordinary and 51 database cases without new packages.

- Transition matrices cover every run/attempt pair, including terminal reopening/no-op rejection. Payload checks cover copying, native types, finite values, Unicode and byte/depth boundaries.
- PostgreSQL verifies old-version identity after current-pointer advancement, separate failed/retry attempts, metadata-only ordered events, owner/attempt scope, legal results/timestamps, reserved waiting/resume, stale revisions, refreshed cached attempts and archive refusal.
- Faults injected after flushed run/attempt/state/result events prove the entire unit of work rolls back; a new Session sees the old state and cursor before a successful retry.
- Three bounded independent-connection races verify one winner for competing terminal writes and same-node attempt creation, and contiguous committed events when different-node operations both succeed. Tests verify distinct PostgreSQL backend PIDs and use lock/statement deadlines.
- Direct SQL checks exercise payload/status/identity/revision/membership/context/FK/unique/retention guards. Populated 0002 → 0003 → 0002 → 0003 and full migration round trips pass with no metadata drift, retaining earlier user/workflow/refresh rows. Downgrades run only in disposable schemas.

An independent write process persisted synthetic lifecycle fixtures; a separate read process verified saved states, exact version identity, timestamps and event sequence 1–9 after the first process exited. It also checked the unchanged 13-operation/ten-path API inventory. This is a persistence smoke check, not a node executor or real workflow result.

The guarded additive development migration reached **0003 (head)** with no drift. It verified that existing account/session/workflow/version identifiers were retained and execution tables received no fixture rows. No private .env was read or edited. Test schemas/public test tables were cleaned up and only the owned disposable test container was stopped/removed; the development database remains running.

During verification, the current RegisterRequest schema had already been edited to an 8-character minimum. The existing 15-character tests initially failed; preserving that schema edit, current boundary/redaction/OpenAPI tests and guides were aligned to 8–128. No production authentication code changed in this increment. Historical Phase 3A notes retain their original policy with an explicit current-contract note.

## Review and next increment

Next is Phase 5B: the first controlled manual → transform → end runner and scoped run API slice, using this persistence layer and the Phase 4D compiler. Conditions/calculator follow in 5C, command/idempotency/retry/cancellation hardening in 5D, Redis/Celery/outbox/recovery in Phase 6, and Groq in its provider phase. No node has executed through the application yet. Real workflow CRUD/validation remains available through Swagger, while the React UI still uses local mock state.

Exercise (no solution supplied): inject an exception after a transition's event flush in an isolated unit of work. Verify a new Session observes the original status/revision/cursor and no extra event, then retry successfully. Do not use development data.

Review questions, one at a time:

1. Why must a state change and its event commit in the same transaction?
2. Why does a retry create a new node-attempt row instead of resetting a failed row?
3. Why is a revision check needed when a run can return to the running status after waiting?
4. Why is a global event ID insufficient as a per-run replay sequence?
