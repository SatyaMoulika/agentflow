# Queued workflow execution

Phase 6C connects authenticated run creation, a transactional outbox, Redis,
Celery, the pure worker runner and recovery discovery. Background execution is an
explicit opt-in. Existing synchronous runs remain synchronous, and Groq graphs
always use the synchronous path in this increment.

## Start and test from the browser

Run commands from the project root. Preserve the database and JWT settings in the
existing private `backend/.env`; do not replace it with the example. This increment
requires migration head 0008, which must be applied before restarting the updated API.
Phase 6D now adds [scheduled retries](scheduled-retries.md) for eligible pure failures.

Prepare the local services and migrate:

```bash
docker compose --profile worker up -d --wait postgres redis
uv run --directory backend --locked alembic upgrade head
```

Start the API in one terminal. These process settings opt into background runs and
enable cookies on local HTTP without editing the private file:

```bash
AGENTFLOW_BACKGROUND_EXECUTION_ENABLED=true \
AGENTFLOW_REDIS_URL=redis://127.0.0.1:16379/0 \
AGENTFLOW_REFRESH_COOKIE_SECURE=false \
AGENTFLOW_AUTH_ALLOWED_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173","http://localhost:8000","http://127.0.0.1:8000"]' \
uv run --directory backend --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

Start the frontend in another terminal:

```bash
npm run dev
```

Before starting the worker, open **http://localhost:5173**, sign in, create a
workflow using the default manual → end graph, save and validate it. Run it with:

```json
{ "CustomerID": 42, "message": "Background browser check" }
```

The request returns 202 with `execution_mode: "background"`. Execution details show
queued status and update automatically every 1.5 seconds while active. With no
worker/dispatcher running, the run waits durably; no fake result is produced. You
can cancel this queued run and verify it stays cancelled after workers start.

In a third terminal, start the separate worker:

```bash
AGENTFLOW_REDIS_URL=redis://127.0.0.1:16379/0 \
uv run --directory backend --locked python -m app.workers
```

In a fourth terminal, start the dispatcher and recovery loop:

```bash
AGENTFLOW_REDIS_URL=redis://127.0.0.1:16379/0 \
uv run --directory backend --locked python -m app.workers.outbox run
```

The worker and dispatcher use the PostgreSQL URL from the existing backend file.
An uncancelled queued run should become succeeded and retain the input object as
its output. Its manual and end attempts should be visible. Refreshing the page
retains the same run and history. Very fast jobs can already be running/completed
when the first detail request arrives. Use the [branching graph](branch-execution.md#a-runnable-graph)
to check actual calculations and skipped branches too.

Stop these foreground processes with Ctrl+C when finished. Do not remove the
development PostgreSQL volume. Recovery interruption/kill tests belong to the
disposable test services, not injected fixtures or lease edits in development.

## Creation, dispatch and ownership

When background mode is enabled and every node in the compiled exact saved version
is retry-safe, one transaction commits the queued run, creation event, optional
idempotency receipt, `workflow_dispatches` provenance and first workflow outbox row.
The API never contacts Redis. Broker failure therefore cannot roll back a committed
run or cause an automatic second run. Matching command replay returns the existing
run and its original execution mode even after configuration changes.

The dispatcher leases outbox rows in short transactions, publishes outside the
database transaction, and marks publication under the matching lease. Redis
messages contain only a fixed task name and the outbox UUID. They contain no owner,
workflow graph, input/output or provider credential. The consumer resolves the
stored target and active owner in PostgreSQL and requires durable dispatch
provenance before claiming the exact run. Synchronous queued rows are never scanned
or accepted as arbitrary task targets. Archive prevents new runs; already accepted
background runs can finish using their original saved version.

The dispatcher can also be run once with `python -m app.workers.outbox dispatch-once`.
Both modes handle workflow intents and the existing transport probes. The default
loop interval is one second; `--interval` accepts 0.1–30 seconds.

## Leases, recovery and retained history

The production task enables a heartbeat using separate short database sessions.
It renews every one-third of the lease duration while pure computation executes;
the compute call retains no database transaction. Renewal uses bounded PostgreSQL
statement timeouts. Storage uncertainty or claim loss stops subsequent result
writes. Every state mutation still rechecks owner, token, generation and expiry
under the run lock; a heartbeat is not a substitute for fencing.

The dispatcher loop rediscovers only provenance-backed queued/running runs whose
redispatch time is due, with no live claim and no unpublished workflow intent. It
locks the run before rechecking the claim. Concurrent scanners skip locked rows;
a partial unique index also prevents two pending workflow intents for one run.
Each redispatch inserts a new outbox row; published rows are never reset or erased.
The original run ID, command receipt and immutable version remain the same.

Default run leases and redispatch delays are 30 seconds. Set
`AGENTFLOW_WORKER_LEASE_SECONDS` and `AGENTFLOW_WORKER_REDELIVERY_SECONDS` consistently
for worker/dispatcher processes; each accepts 5–3600 seconds. Redispatch can take a
lease expiry plus the scheduling/polling delay. These settings control transport
redelivery. Eligible background node retries now have their own persisted
exponential delay, bounded by the saved 1–3 attempt budget; see [scheduled retries](scheduled-retries.md).

Recovery reuses committed selected-route outputs. Interrupted attempts become
retained failures and consume their original budget slot; a retry gets a new
attempt number. Budget exhaustion fails the run. Cancellation prevents late
results from reviving it. Terminal runs are not redispatched. Duplicate delivery
and duplicate pure computation remain possible; no exactly-once guarantee is made.

## Groq and configuration boundaries

`AGENTFLOW_BACKGROUND_EXECUTION_ENABLED` defaults to false and controls new run
admission only. Enabling it requires explicit database and Redis configuration,
but does not contact the broker at API startup. Existing queued background runs
continue to belong to workers if admission is later disabled. Run details/listing
report `execution_mode` as `background` or `synchronous`; create and full-retry
responses use 202 for retained background commands and 201 for synchronous commands.

A Groq node anywhere in a graph keeps the whole run synchronous, including when
that node is on an unselected branch. Groq calls are not automatically retried or
resumed, and whole-workflow retry remains unavailable for those graphs. An
ambiguous external/provider outcome needs a separate reconciliation policy.

## Verification and remaining scope

The full backend checker passed 1100 tests with isolated PostgreSQL and Redis,
Ruff lint/format and Pyright. Frontend checks passed 122 tests, lint and production
build. Isolated tests cover atomic command/run/outbox rollback, 202 and idempotent
replay across configuration changes, owner boundaries, cancellation, full-workflow
retry lineage, broker failure, concurrent scans, retained delivery history, lease
renewal during computation longer than its original lease, and Groq staying
synchronous with a local stub. A real API → Redis → Celery check verifies the
opaque message body and duplicate delivery. Another test kills a real worker
during a transform, then starts a new worker and dispatcher: normal lease expiry
triggers recovery without test edits to leases or clocks.

Migration 0007 preserves old run/probe rows. It retains delivery history and refuses
downgrade while workflow dispatch records exist rather than silently deleting them.
The schema, FK/target/pending uniqueness guards, populated upgrade and empty-history
downgrade/re-upgrade are checked only in disposable schemas.

Browser automation is unavailable because the browser access host is not connected.
Frontend rendering/tests and HTTP/real-process checks do not establish actual
browser interaction behavior. SSE, external-side-effect
reconciliation, production supervision/deployment and a multi-process worker load
test remain later work. Inconsistent stored history is rejected; repeated recovery
warnings require investigation rather than inventing progress.
