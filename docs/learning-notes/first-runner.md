# Phase 5B — first real synchronous workflow execution

Current follow-on: [Phase 5C branch execution](branch-execution.md) adds conditions/calculators, selected-route merges and persisted completion skips. All six registered types are now execution-ready. Scope and verification below record the original increment.

Implemented 3 November 2026. AgentFlow now executes an owned, explicitly selected saved manual → transform → end workflow and persists actual results in PostgreSQL. This is a controlled synchronous runner; the React frontend still uses its local simulator. No Groq call, worker, branching, retry, cancellation, approval or recovery service is added in this increment.

## Public contract and how to try it

Start the backend using the [real-data walkthrough](../real-backend-walkthrough.md), register/login, authorize Swagger with your access token, and save its three-node example. Keep the response's workflow id and current_version_id.

Call **POST /api/v1/workflows/{workflow_id}/runs** with:

```json
{
  "workflow_version_id": "<current_version_id from the saved workflow>",
  "input": { "CustomerID": 42, "items": [1, false, null] }
}
```

Replace the placeholder with an actual UUID. Both fields are required. Input must be an object of finite native JSON values, at most 32 levels deep and 256 KiB in compact UTF-8 form. Input key case is preserved; extra command fields and null/scalar/list input are rejected. A versionless workflow must first save a definition. Candidates cannot be run directly.

The response is **201 Created**, with Location pointing to **GET /api/v1/runs/{run_id}** and Cache-Control: no-store. The POST waits for execution; it does not return a queued job or use background tasks. The body includes run/version IDs, status/revision/event_sequence, input/output/error_code, UTC timestamps, the exact saved version snapshot and ordered node_runs attempt history. Node attempts contain actual resolved inputs, outputs, failure codes, timestamps and wall-clock duration. This API has snake_case DTO fields; arbitrary business keys are not converted. No fabricated usage/token/span data is returned.

A successfully created run can have status failed: inspect status/error_code, not just HTTP 201. Missing/unowned/mismatched workflows/versions/runs share generic 404, malformed commands return 422, invalid/unsupported saved graphs return 422 WORKFLOW_NOT_EXECUTABLE before any run is created, archived starts return 409, and storage failure returns safe 503. Active-user Bearer authentication protects both routes; X-AgentFlow-Client is needed for login/cookie operations, not these Bearer commands.

The earlier design's 202 response belongs to the worker phase. The current synchronous contract deliberately uses 201 and a completed/failed representation. GET /runs listing, cancellation/retry and event/SSE endpoints remain planned. The API now has **15 operations across 12 paths**. No model, schema, dependency or configuration change was needed; migration head remains **0003**.

Every POST creates a new run. Idempotency-Key is explicitly rejected with 422 until Phase 5D implements its semantics. Do not silently retry a lost/failed POST. A storage error after a known committed creation includes Location for inspection; an initial commit/response loss can still be ambiguous. Durable command recovery and duplicate suppression are not implemented yet.

## Execution semantics

- manual copies the run input into its output. Its config remains {}.
- transform with operation identity copies its resolved input. pick_fields selects exactly the configured top-level keys; dots in a field name are literal and case matters. A missing field fails the attempt/run with EXECUTION_FAILED. Present null values are valid.
- end copies its resolved input; that output becomes the workflow run's final output. The end attempt result and succeeded run transition commit together.

Without input_mapping, a node receives the immediately preceding output. A nonempty input_mapping **replaces** that incoming object with the explicitly named keys. Values are resolved only from already completed upstream outputs through dictionary keys, using compiler-produced bindings. $.start.output refers to the whole output object; $.start.output.invoice.Amount traverses dictionary keys. There is no array indexing, attribute access, string interpolation, expression evaluator or numeric coercion. Literal target keys containing dots remain literal.

Missing output/field, traversal through a scalar/list/null or a resolved mapping exceeding payload bounds produces INPUT_MAPPING_FAILED. That failed attempt stores input {} rather than a partially resolved mapping, has no started_at and has duration 0. A pick_fields execution failure has its actual resolved input and start/completion times. Unexpected executor exceptions use INTERNAL_FAILURE without recording raw exception messages. Downstream nodes are never invoked after failure and have no attempt rows; they are not falsely labeled as executed or skipped.

The shared registry now advertises execution_ready true and capabilities [validate_config, execute] only for manual, transform and end. condition/calculator/merge retain validation-only contracts and false readiness. Validation reports readiness true only when a graph compiles and all its nodes have current executors. This expresses capability, not saved-version existence, authorization, runtime input validity or permission to start an archived workflow. Candidates/archived snapshots remain inspectable; run creation independently enforces its own rules.

## Request, functions and transaction flow

1. api/v1/runs.py resolves active-user Bearer identity and the shared Database, validates RunCreateRequest, rejects unsupported idempotency headers and calls ExecutionService.create_and_execute in a worker thread. No mutable Session crosses threads.
2. service.py reads the exact owner-scoped workflow version, copies definition_json and closes the read Session. compile_workflow validates the saved snapshot outside storage. Unsupported/invalid graphs stop here with no run/event writes. Changing the workflow's current pointer cannot substitute another version.
3. A short unit of work calls ExecutionRepository.create_run. It locks the workflow and rechecks archive/ownership/version membership before committing queued state and run.created. The service retains the committed UUID.
4. LinearRunner.run changes queued revision 0 to running revision 1 in a separate short transaction. Compilation plus the three-type allowlist guarantees a single reachable linear route, so the compiled topological order is the executed order. Branch scheduling is not implemented by iterating both arms.
5. For each node, resolve_input copies the previous output or resolves explicit dictionary bindings outside a transaction. A short unit of work then commits a pending attempt/node.created and running attempt/node.status_changed. A mapping failure instead commits a pending-to-failed attempt and failed run together.
6. execute_node runs ordinary pure code **without a checked-out operation Session/transaction**. It cannot call tools, the filesystem, a model or the network. The result is copied and bounded before persistence.
7. Another short unit of work records succeeded output/event. On end, it also completes the run/output/event atomically. A domain or unexpected executor failure uses LinearRunner._fail to commit failed attempt + failed run/events together. No automatic retry occurs.
8. ExecutionService.get acquires a short owner-scoped run-row lock, then reads the exact immutable version and attempts. This keeps its response coherent with cooperating writers at READ COMMITTED isolation. It builds explicit DTOs before closing the Session; JSON keys/UTC times serialize through schemas.py. Reading does not change timestamps, revisions, counters or history.

All repository mutations still use expected revisions and run-first locking. Events contain static lifecycle metadata, never raw input/output/exception text. Inputs, outputs and version snapshots are returned only to the owner and may themselves contain sensitive business data; the API does not guess how to redact arbitrary JSON. Capture/retention policy remains later hardening.

A PostgreSQL/pool failure rolls back the current unit of work and returns safe 503. Earlier committed lifecycle history remains readable. For example, a failed result write leaves the already committed attempt running with no output or result event. It is not falsely marked successful or automatically replayed. Process termination/client disconnect can also leave queued/running history; claim/lease/checkpoint recovery belongs to Phase 6. Archive blocks new starts but does not cancel an already committed run.

## Actual checks — 3 November 2026

The complete PostgreSQL checker passed **756 tests**; ordinary checks passed **530**, skipping **226** explicit PostgreSQL cases. Ruff lint/format passed 115 Python files and Pyright reported zero errors/warnings. Locked offline synchronization and documentation formatting/relative links passed. Added 30 ordinary and 18 integration cases; earlier migrations/auth/ownership/compiler/state/concurrency tests remain green.

Unit/API checks cover pure copying, exact field selection, nulls, mapping replacement/whole-output/nested lookup, missing/non-dictionary paths, bounded strict request input, auth-before-storage, secret-free errors, unsupported idempotency headers, and exact OpenAPI paths/statuses/DTO names. Readiness tests now assert actual executor support rather than the earlier static false contract.

Real PostgreSQL HTTPX tests verify computed output and attempts/events, no downstream execution on failure, owner/version scope, inactive accounts, historical versions, pointer-change/archive rechecks, independent concurrent POSTs, fresh-app history reads, worker-thread execution without checked-out operation sessions, safe storage errors/recovery and rollback after flushed creation/result events. Conditional/calculator graphs can validate successfully while run creation correctly refuses them. There are no fake provider calls or seeded development results.

A temporary real Uvicorn server registered/logged in, saved a workflow and produced actual field-selection output plus a persisted failed run. After server shutdown/restart, GET returned identical run/attempt/version history for both. Checks also covered 401/owner 404, catalog readiness, 15-operation/12-path OpenAPI, private correlated logs and two graceful application shutdowns. Only Database was overridden to a disposable migrated test schema; a process-local signing key and explicit local HTTP cookie mode were used. The smoke harness accepts normal SIGTERM exit only alongside application-shutdown log verification. No private .env or development account/workflow/run data was read or changed.

The development database remains at 0003 head with no drift. Disposable schemas/test tables, temporary server/factory/scripts and the owned test container were cleaned up; development PostgreSQL remains running.

## Review and next increment

Next is **Phase 5C: condition/calculator execution and exclusive-branch routing/merge**, including real selected-path execution and explicit skipped-node semantics. Phase 5D follows with command idempotency, bounded pure-node retry and cancellation/failure hardening. Workers/recovery, Groq, approvals, SSE and frontend integration remain in their owning phases.

Exercise (no solution supplied): save a manual → identity transform → pick_fields transform → end graph. Map the second transform from the original manual output rather than the immediately previous output; predict and verify persisted inputs/outputs. Then remove one mapped field and inspect the failed run/attempt history without changing an older run. Use your own test data, not credentials.

Review questions, one at a time:

1. Why does the runner commit an attempt's start before computing its result, and close the transaction during computation?
2. Why can a graph be valid but execution_ready false?
3. What does 201 mean when the returned run has status failed?
4. Why must a storage failure after a committed start preserve running history instead of claiming completion or silently replaying the node?
