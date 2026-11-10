# Phase 5D — execution commands and bounded retries

Implemented 4 November 2026. Pure-node execution now supports durable command deduplication, whole-workflow retry, cooperative cancellation and bounded automatic attempts. API: 18 operations across 15 paths. Alembic 0004 adds frozen `workflow_runs.max_attempts` and owner-scoped immutable `run_commands` receipts; earlier migrations are unchanged.

## Modules and flow

| File                                           | Responsibility                                                                                    |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| app/modules/executions/commands.py             | Bounded key validation and canonical request hashing                                              |
| app/modules/executions/models.py               | Retry budget and command receipt mappings                                                         |
| migrations/versions/0004_execution_commands.py | Additive migration, budget bounds/immutability and receipt ownership/history guards               |
| app/modules/executions/service.py              | Receipt lookup/create transaction, full retry lineage, atomic cancellation                        |
| app/modules/executions/runner.py               | Retry attempts and cancellation checks at each state-writing boundary                             |
| app/api/v1/runs.py                             | Header/body contracts, authenticated commands and safe errors                                     |
| src/api/client.ts, Editor.tsx, pages.tsx       | Command keys, selectable attempt budget, cancel/retry actions, lineage and actual attempt history |

Run creation pins and compiles an owned immutable version outside a write transaction. A short transaction locks the owner's user row, rechecks the receipt, and creates the run, first event and receipt together. The per-owner lock covers keys reused across different workflows; no lock is held during node computation. The database composite primary key is a final uniqueness guard. The receipt ownership trigger refuses a run owned by another user.

Only the request that creates the run invokes the runner. A duplicate can return queued/running history while the original request is still computing. It never starts a second runner or resumes a stranded run. After commit, all node computation happens outside database transactions. State/results and corresponding events commit atomically.

## Idempotent run creation

POST /api/v1/workflows/{workflow_id}/runs accepts:

```json
{
  "workflow_version_id": "<saved-version-uuid>",
  "input": { "quantity": 3, "unit_price": 200 },
  "max_attempts": 2
}
```

`max_attempts` is a strict integer from 1–3, defaults to 1, and applies per visited node. An optional `Idempotency-Key` header accepts 1–128 ASCII letters/digits and `. _ : -`, with no spaces. Duplicate header fields are rejected. Keys are scoped across all create/retry commands for one authenticated owner. Use a fresh random UUID per intentional command; never put credentials or business data in a key.

Without a key, every valid POST creates a distinct run. With a key, the service stores SHA-256 digests of key and canonical request, plus run identity. Canonical identity includes workflow/version, original input, attempt budget and optional retry parent; dictionary ordering is ignored while JSON numeric representation, string casing and types remain significant. Hashes are not encryption and low-entropy payloads are not secret just because they are hashed. Raw keys are not stored or logged by AgentFlow.

An identical key/command returns the current original run with 201, the same Location and no-store. It is not a frozen byte-for-byte HTTP response: status/history may have advanced. Changed input/version/budget/workflow/parent returns safe 409. Replays remain readable after archive; archive prevents new execution. Validation failures and rolled-back creation do not retain receipts. Receipts currently have no expiry/cleanup; keys cannot be recycled during retention.

A 503 after known committed creation carries Location. Loss during initial commit can be ambiguous; resend exactly the same command/key to discover any committed receipt. Do not generate a fresh key for that recovery. A retained queued/running run is not automatically resumed; inspect it and cancel/retry if appropriate. This is deduplication at the persistence boundary, not exactly-once execution or crash recovery.

## Automatic attempts

The explicit retry-safe list is manual, transform, condition, calculator, merge and end. Future provider/tool readiness does not automatically make those nodes retry-safe. Each failed attempt remains immutable history; another attempt gets a new ID and incremented attempt number. A recovered node's latest attempt is successful while earlier failure events remain visible.

Only INTERNAL_FAILURE and DEADLINE_EXCEEDED qualify, with at most the saved budget. Missing mappings, invalid types, arithmetic errors and other EXECUTION_FAILED outcomes stop immediately. Retries are immediate, with no backoff, sleeps, worker or scheduler. Current pure executors do not impose elapsed execution deadlines; the deadline code is handled if an executor explicitly produces it. Transient faults are injected in tests; no artificial failures are generated in normal runs. Exhaustion persists the failed attempt and failed run atomically. Unexpected pure executor exceptions become static INTERNAL_FAILURE without storing exception text. Database failures are never retried as node failures.

## Whole-workflow retry

POST /api/v1/runs/{run_id}/retry requires JSON `{}` or `{"max_attempts":2}` and optionally an Idempotency-Key. Only an owned failed/cancelled run is eligible; active/succeeded sources return 409, missing/unowned return 404. It creates a new run with `parent_run_id`, the exact original version and original input. It reruns the full graph from the beginning, without changing the parent's history. Newer workflow saves are irrelevant. Caller input/version overrides are rejected. Archived workflows reject fresh retry commands; an already committed retry receipt still replays. The whole frozen graph must be pure/retry-safe; partial external-effect replay is refused.

## Cancellation

POST /api/v1/runs/{run_id}/cancel takes no body. It locks the owned run, cancels all open attempts, then transitions the run to cancelled with its events in one transaction. Queued/running/waiting-approval storage states are supported; this does not implement approval processing. Already-cancelled returns the same current history with 200, other terminal states return 409. Missing/unowned is 404. Completed attempt history remains unchanged; unvisited nodes are not invented as skipped.

The runner checks cancellation under the same run-row lock before each state write. A cancellation that commits first discards any pending result/error, starts no next attempt, and cannot be overwritten by success/retry/completion skips. If completion commits first, cancellation returns 409. Pure computation already in progress may finish in memory; no thread/process interruption or external-effect rollback is claimed. Cancellation can target an in-flight run from a second tab using execution history; short synchronous runs may finish first.

## Frontend behavior

The editor exposes a 1–3 attempt selector and supplies a random command key. Explicit resubmission of the same failed command in that editor reuses the key; changing input/version/budget or completing a submission allocates a new command. Keys are memory-only. Reloading loses an unresolved key, so inspect history before issuing another run. No network/503 mutation replay happens automatically. The existing 401-refresh replay preserves the command key and account fencing.

Execution details show saved budget, retry parent, all attempts and appropriate Cancel/Retry full workflow buttons. These require confirmation in the app. Retry from this page uses one automatic attempt per node; choose a larger budget in the editor for a new manual command. Cancellation retains completed history. Errors include request IDs and known retained-run links. Live traces/events and background recovery remain unavailable.

## Verification and review

Backend verification: 905 passed with real PostgreSQL; ordinary mode 638 passed/267 skipped. Ruff checks 124 files and Pyright reports zero errors/warnings. Added 47 cases covering strict budgets/keys, canonical identity, ownership, concurrent first writes, replay during computation, conflicts, atomic receipt failure, original-version lineage, transient recovery/exhaustion, deterministic non-retry, cancellation success/failure races, rollback, SQL ownership/immutability, populated migration downgrade/re-upgrade and metadata parity.

Frontend verification: 120 tests, ESLint, TypeScript and production build. New rendering cases cover the action availability for six run states; earlier client tests cover no ambiguous automatic replay and account fencing. Real Uvicorn HTTP checks verify create/replay/conflict, full retry, cancellation of an explicitly seeded queued storage fixture, auth session and receipt/history persistence across restart, OpenAPI inventory, private correlated logs and graceful shutdown. Concurrent running cancellation is tested using the real PostgreSQL-backed ASGI routes, not a timed production executor. Browser visual/E2E remains outstanding; no provider or worker was exercised.

Exercise: create a run with a key, then resend it with reordered input keys, a changed numeric value and a different attempt budget. Predict which requests reuse history and which conflict. Repeat the original command after archive and explain the result.

1. Why must the receipt and initial run event commit together?
2. Why can replay return running rather than execute the graph again?
3. Why does cancellation need the same run lock as result persistence?
4. Why must a failed attempt remain terminal when another attempt starts?
5. What failure remains unresolved when a process stops between creation and execution?

Next: Phase 6 — transactional outbox, Redis/Celery dispatch, claims/leases and crash recovery. Groq remains Phase 7 with no paid fallback.
