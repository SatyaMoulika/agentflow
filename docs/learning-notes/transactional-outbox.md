# Phase 6B — transactional outbox foundation

The outbox now durably stores and dispatches **transport-probe intents**. It is not yet connected to workflow creation: runs continue to execute synchronously. The next increment must add safe worker claims and recovery before workflow jobs can use this mechanism. Groq integration remains Phase 7.

Migration `0005` creates `outbox_messages`. A row contains an opaque UUID, fixed `transport_probe` kind, creation/publication times, attempt count and a temporary lease token/deadline. It contains no user input or secret. Published rows are retained and immutable. The database rejects deletion, changed identity and invalid lease combinations.

`OutboxRepository.enqueue_probe()` inserts using the caller's transaction. If the caller rolls back, the intent rolls back with the rest of its work. `claim()` uses PostgreSQL `FOR UPDATE SKIP LOCKED` and database time, then commits a bounded lease. A dispatcher publishes outside the transaction; on success it marks published only when the lease token still matches and has not expired. On broker failure it releases its own valid lease. A process crash leaves the row claimable after the lease expires; a stale dispatcher cannot mark or release another dispatcher's lease.

The broker can accept a message immediately before the dispatcher crashes or loses its acknowledgement. A later attempt can therefore publish the same message again. Publication is **at least once**, and `published_at` records broker acceptance, not worker completion. The consumer must eventually be idempotent and fenced by worker claims; a task ID alone does not provide deduplication. No exactly-once or workflow recovery guarantee is claimed. A batch lease also runs while earlier batch items publish; a slow batch may expire and be reclaimed. Stale marking is rejected and a duplicate is possible. There is no polling loop, timed backoff, dead-letter handling or cleanup policy yet.

## Try the probe locally

Start PostgreSQL and Redis, apply migrations, and start the worker as described in [worker transport](worker-transport.md). From the repository root in another terminal, with your configured database URL and local Redis available:

```bash
uv run --directory backend --locked python -m app.workers.outbox enqueue-probe
AGENTFLOW_REDIS_URL=redis://127.0.0.1:16379/0 \
uv run --directory backend --locked python -m app.workers.outbox dispatch-once
```

The first command commits one probe intent and prints its UUID. The second claims and attempts to publish pending probes; the worker logs `Outbox probe consumed` with that UUID. It does not run a workflow. Failed publication returns a nonzero exit and releases its lease when possible; repeat `dispatch-once` after the broker returns. `enqueue-probe` intentionally writes a retained row, so use it when you want to create a test intent.

## Verification and limits

The full backend checker passed 947 tests with isolated PostgreSQL and Redis; Ruff checked 140 files and Pyright reported zero errors. The ordinary check passed 665 tests and skipped 281 integration cases before the final migration test was added. The unchanged frontend was last verified at 120 passing tests.

Real PostgreSQL tests cover atomic rollback, safe retry after publish failure, concurrent `SKIP LOCKED` claimers, expired-lease fencing, and duplicate publication after simulated failure between publish and mark. An integration test connects PostgreSQL, Redis and a separate Celery worker, confirms delivery of a payload-free UUID and verifies the database publication record. Schema upgrade/downgrade and metadata checks run in disposable schemas. No provider call, worker crash recovery, external side effect, production deployment or browser E2E is claimed.

The current implementation has no workflow ID, workflow payload or production job consumer. Adding such an intent must happen in the same transaction as its queued run and idempotency receipt. Worker claims and lease fencing must then prevent duplicate or stale execution before synchronous execution is replaced.

Exercise: enqueue a probe, stop Redis, run the dispatcher, restart Redis and dispatch again. Explain why the intent survives broker failure and why publication can still occur more than once.

1. Why must creating a run and its outbox intent share one commit?
2. Why is the broker call outside the database transaction?
3. What protects a newer claim from a dispatcher whose lease expired?
4. What can happen when a broker accepts a message but the publisher cannot mark it?
5. Why is a published outbox row not proof that a workflow completed?
