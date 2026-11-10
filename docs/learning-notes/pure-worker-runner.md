# Pure worker execution and recovery

The subsequent [background execution increment](background-execution.md) connects
this runner to workflow outbox delivery, heartbeat and automatic recovery discovery.
The note below records the earlier internal-runner increment and its checks.

The Phase 6C increment on 6 November 2026 adds an internal `PureWorkerRunner`.
It executes a saved workflow with a database lease, reconstructs its selected route
from committed history, and can recover a previously claimed running run after its
lease expires. The public API still executes synchronously. Celery currently
consumes transport probes; workflow tasks, dispatch and recovery scheduling remain
to be connected.

## Execution boundary

The runner requires both the run ID and owner ID. It checks ownership and compiles
the run's immutable saved version before acquiring a claim. Every node in that
version must be explicitly retry-safe: manual, transform, condition, calculator,
merge or end. A Groq node anywhere in the graph, including an unselected branch,
prevents execution through this runner. It does not load provider settings or call
Groq.

`ClaimRepository.acquire` retains its queued-only behavior. The separate internal
`acquire_for_recovery` primitive also permits running runs with an existing expired
or released claim slot. A running synchronous run without a claim slot is refused.
The primitive does not authorize a user, validate a graph or execute a node; the
runner supplies those boundaries. Internal callers must not dispatch arbitrary
queued rows from the synchronous API: the future workflow outbox must establish
which runs belong to workers before dispatch is enabled.

## Transactions and progress

1. Copy the owned immutable definition, close the read transaction, then compile it.
2. Acquire a claim under the owned run-row lock. A live competing lease prevents
   execution; a takeover gets a new token and monotonically increasing generation.
3. Renew the claim and read a coherent owner-scoped snapshot of saved history.
4. Transition a queued run to running, or reconstruct an existing running route.
   Successful node outputs and condition choices are reused without executing
   those nodes again.
5. Resolve input/configuration outside a transaction, then commit a new running
   attempt under the claim fence. Compute outside all database transactions.
6. Commit the actual result under the same fence. End-node success, unvisited
   branch skips, run output and their events commit atomically.

Every mutation rechecks ownership and the current token, generation and lease
under the run lock. Snapshot data alone never grants permission to write. A stale
worker can finish computing, but its late result cannot change history after
expiry, takeover or cancellation. Cancellation retains completed history and
closes open attempts atomically through the existing command service.

## Interrupted attempts and bounded retries

An unfinished pending/running pure attempt is retained and changed to failed with
`INTERNAL_FAILURE`; it is never restarted in place. Its original attempt number
consumes one slot of the run's saved 1–3 attempt budget. A retry creates a new
attempt and recomputes only the unfinished node using the selected route's
committed upstream outputs.

Only `INTERNAL_FAILURE` and `DEADLINE_EXCEEDED` are retryable. Existing deterministic
failures do not become retryable during recovery. If the saved budget is exhausted,
the attempt failure and run failure commit together. A crash between committing a
retryable failure and creating its replacement is recoverable from that failed
attempt's persisted status, code and number. History outside the selected route or
otherwise inconsistent with the exact saved version is rejected before execution.

Storage exceptions propagate without a compensating or blind repeated write.
If a commit outcome is uncertain, the next claim holder must inspect committed
history. Claim loss also stops further writes. Terminal runs and live competing
claims return without starting work. Claim slots and attempts remain in history.

## Limits and next steps

Leases renew between node computations. There is no background heartbeat during a
long computation; if it outlives its lease, its result is rejected. Pure computation
may run again after takeover. This is not exactly-once processing, and no external
provider or other side effect is resumed.

Recovery currently requires an explicit internal runner call. There is no workflow
task consumer, scanner, automatic redelivery or scheduled retry/backoff. API run
creation still returns synchronous 201 responses and does not enqueue workflow
intents. The next increment must connect atomic run/outbox creation to an opaque-ID
workflow task, lease renewal, safe expired-work discovery and broker failure tests
before switching the API to queued 202 responses. Groq execution needs a separate
policy for ambiguous provider outcomes before joining that path.

## Verification

`backend/tests/integration/test_worker_runner.py` uses only the guarded disposable
PostgreSQL database and a random migrated schema. It covers both actual arithmetic
branches, case-sensitive input keys, original-version selection, ownership, complete
history, bounded retries, cancellation, duplicate execution, lease takeover and
reconciliation rollback. A subprocess is killed with SIGKILL during a selected
calculator attempt; a fresh runner reuses committed entry/condition outputs and
records a new calculator attempt after the lease is expired in the test database.
No provider request is made.

Run the complete isolated checks from the project root:

```bash
docker compose --profile test up -d --wait postgres_test redis_test
TEST_DATABASE_URL=postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test \
TEST_REDIS_URL=redis://127.0.0.1:16380/15 \
uv run --directory backend --locked python scripts/check.py --integration --redis-integration
```

Do not insert runs into the development database for these checks. Stop only the
test services started for the task.

Exercise: with a disposable run budget of one, interrupt its first attempt and
verify that recovery records failure without silently allocating a second attempt.
Why must interruption consume the original budget, and why must a late result be
fenced even though the operation is pure?
