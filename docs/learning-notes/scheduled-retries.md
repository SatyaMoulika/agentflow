# Scheduled pure-node retries

Phase 6D adds durable exponential backoff to background pure workflows. A transient
failure no longer loops immediately inside a worker. The failure, retry deadline,
audit event and claim release commit together, and the worker returns to its queue.
The dispatcher sends work again after the saved deadline. No worker or database
transaction sleeps while waiting.

## Run policy and timing

The existing maximum-attempt setting remains 1–3 **per node**, including the original
attempt. Default 1 means no automatic retry. Only `INTERNAL_FAILURE` and
`DEADLINE_EXCEEDED` on the six explicitly pure node types are eligible. Invalid
input/mapping, unsupported types and arithmetic failures still fail immediately.
Groq graphs remain synchronous and are excluded from scheduled recovery.

The API copies two settings into each new background run's dispatch record:

```dotenv
AGENTFLOW_WORKER_RETRY_BASE_SECONDS=5
AGENTFLOW_WORKER_RETRY_MAX_SECONDS=60
```

These are optional defaults; there is no required `.env` change. Base delay accepts
1–300 seconds, maximum accepts base–3600 seconds. Both are immutable for that run,
so restarting processes with different settings does not rewrite its policy.
Migration 0008 gives existing dispatch records the defaults above.

Delay is `min(base × 2^(failed_attempt_number − 1), maximum)`. With maximum attempts
3 and default policy, attempt 1 failure schedules attempt 2 after 5 seconds; attempt
2 failure schedules attempt 3 after 10 seconds. Attempt 3 failure ends the run.
Actual start time can be later because of dispatcher polling, queue backlog or an
unavailable broker/worker. There is no jitter or elapsed execution deadline in this
increment.

Synchronous pure workflows keep immediate bounded retries. This changes the
background path, not the request body or idempotency fingerprint.

## State and transaction boundaries

Migration 0008 adds immutable retry-policy columns on `workflow_dispatches` and
retained `node_retries` rows. Each row identifies the failed attempt and run, creation
time and immutable due time. It later records either resume or cancellation.
Composite foreign keys keep the attempt in the same run; a partial unique index
permits only one pending retry per run. SQL guards require an eligible failed
attempt within its saved budget, preserve deadlines and resolution history, and
reject retry deletion/truncation. Downgrade refuses retained retry rows/events.

Under the owned run lock and a current claim fence, the worker commits:

1. The actual failed attempt and status event.
2. A retry row and `node.retry_scheduled` event if retryable and within budget.
3. The dispatch wake time and release of the claim.

Budget exhaustion/deterministic failure instead commits terminal run failure with
the attempt. Failed attempts keep their original identities and outputs remain
null. An interrupted attempt consumes its saved budget slot and is reconciled to
`INTERNAL_FAILURE` before scheduling. If recovery finds an old committed failed
attempt with no schedule, it creates one once using the stored policy.

The dispatcher checks the due time before adding another delivery. Claim
acquisition independently checks it under the run lock, so an old/duplicate Redis
message cannot bypass the wait. After it becomes due, a worker reconstructs the
same saved version/selected path, reuses successful upstream outputs and commits a
new running attempt together with the previous retry's resume timestamp. A crash
before that transaction commits leaves the retry pending. A crash afterward leaves
a new interrupted attempt that consumes its own budget slot.

Cancellation takes the same run lock, atomically cancels open attempts/run and
resolves any pending retry as cancelled. Late messages cannot revive the run.
Claim release also invalidates late writes and heartbeat renewal from the worker
that scheduled the wait. Storage/commit uncertainty never triggers a blind replay;
the next claim holder must inspect retained history.

No external effect is automatically resumed, and duplicate delivery/pure computation
remain possible. This does not provide exactly-once execution.

## Browser behavior and setup

Apply the migration before restarting the API, worker and dispatcher:

```bash
uv run --directory backend --locked alembic upgrade head
```

Use the [background process startup guide](background-execution.md) for Redis and
the separate processes. Keep the private file's existing values. For an eligible
run, choose 2 or 3 maximum attempts before running it.

Execution details continue to show the run as running while its retry is pending,
and now explain **Waiting to retry … (attempt …) at …**. Failed attempt details show
the scheduled due time and later resume/cancellation time. The existing active-run
polling updates the page; cancellation remains available during the wait. API run
details expose `next_retry_at`, `retry_node_id`, `next_retry_attempt`, and per-attempt
`retry` metadata; these are null when no retry is pending.

A normal successful workflow will not show a retry. Missing input/division by zero
also cannot demonstrate backoff because those failures are deterministic. Do not
modify application code or development leases to manufacture failures. Controlled
transient failures, process interruption and restart are tested only against the
guarded disposable services.

## Verification and next work

Unit tests check policy validation, bounded delay and configuration. PostgreSQL
checks cover immutable deadlines/policy, no early duplicate delivery or claim,
retained attempts/outputs, exponential delay, budget exhaustion, deterministic
non-retry, cancellation races, atomic rollback on event-write failure, and populated
upgrade/empty-history downgrade/re-upgrade. A real solo Celery worker schedules a
retry, executes another workflow while the first waits, then stops; a fresh worker
and dispatcher resume the original after its unchanged deadline. Existing real
worker-kill recovery now also verifies the durable retry step.

Frontend rendering checks verify pending-retry text and retained failure details.
The full checker passed **1100 backend tests** with isolated PostgreSQL/Redis,
Ruff lint/format and Pyright. Frontend checks passed **122 tests**, lint, TypeScript
and production build. The guarded local development database is upgraded to 0008
with unchanged existing row counts and no metadata drift. No provider call, private
configuration edit or development test fixture was used. Browser automation was
attempted but the browser access host is unavailable; visual/E2E behavior is not
established by rendering and HTTP tests. SSE,
provider/external-side-effect reconciliation, jitter, elapsed deadlines and production
supervision/load testing remain separate increments.
