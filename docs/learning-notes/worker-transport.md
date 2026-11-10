# Phase 6A — Redis/Celery transport foundation

Implemented 4 November 2026. Celery 5.6.3 and Redis support are installed and locked. This increment verifies a separate worker process and a payload-free probe through Redis. Workflow execution remains synchronous; the API does not dispatch workflow jobs yet. No database migration, workflow state change, Groq request or public endpoint is added.

## Files and responsibilities

| File                                               | Responsibility                                                                             |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `app/core/config.py`                               | Optional secret Redis URL, namespaced worker queue, local/production validation            |
| `app/workers/celery_app.py`                        | Explicit Celery application, JSON-only task content, bounded publisher and data-free probe |
| `app/workers/__main__.py`                          | Separate Celery worker controller, logging and accurate process exit status                |
| `app/workers/probe.py`                             | Optional command-line producer for a random-ID probe                                       |
| `compose.yaml`                                     | Loopback-only local development/test Redis services, optional profiles and health checks   |
| `tests/unit/test_worker_transport.py`              | Configuration, task safety and bounded error tests                                         |
| `tests/integration/test_redis_worker_transport.py` | Real Redis, separate worker process, probe delivery and failure/shutdown checks            |
| `tests/api/test_broker_isolation.py`               | API startup/health with an unreachable optional worker broker                              |

## How it works

The API loads Redis configuration if supplied but does not connect to it during startup or health checks. The worker is a separate process; it requires an explicit Redis URL and fails without one. A producer submits `agentflow.transport.probe` with no arguments or business payload and a random UUID as the task ID. The worker logs a validated probe ID on consumption and stores no Celery task result. A successful producer response confirms publishing, not worker consumption; check the worker's `Transport probe consumed` log for the matching ID.

The queue name defaults to `agentflow.transport` and must remain in the `agentflow.` namespace. Celery broker/read/write URL, result backend, loader and config-module environment overrides are rejected rather than silently bypassing validated AgentFlow settings. Serializer and accepted content are JSON only. The worker uses a solo pool with one process, one prefetched task, no remote control/gossip/mingle and no worker events. Publisher retries are disabled and connection timeouts are bounded; failed publishing raises a static error without the broker password or driver details. Broker startup failure yields a nonzero worker process status. API errors/health are independent of an unreachable broker.

The probe is intentionally harmless and has no result backend or access to stored workflows. The broker and publishers remain trusted infrastructure: restricting serializers does not authenticate publishers. Configure access controls and network isolation for real deployment.

## Local usage

From the project root:

```bash
uv sync --directory backend --locked
docker compose --profile worker up -d --wait redis
```

Run the worker in one terminal:

```bash
AGENTFLOW_REDIS_URL=redis://127.0.0.1:16379/0 \
uv run --directory backend --locked python -m app.workers
```

In another terminal:

```bash
AGENTFLOW_REDIS_URL=redis://127.0.0.1:16379/0 \
uv run --directory backend --locked python -m app.workers.probe
```

The second terminal prints the probe UUID. The worker logs `Transport probe consumed` with the same `probe_id`. Stop the worker with Ctrl+C. The local Redis service binds only to localhost and is unauthenticated, nonpersistent and intended only for development. Stop that service explicitly when no longer needed; do not use `docker compose down --volumes` if retaining PostgreSQL data.

`AGENTFLOW_REDIS_URL` can instead be added to the private backend `.env`. The example file only documents the variable. Do not put secrets in frontend variables or task arguments. `redis://host:port/0` through `/15` and `rediss://` URLs are supported, without query strings or fragments. Production configuration requires `rediss://` plus a password and requests certificate verification; deployment-specific TLS, permissions and operations still need end-to-end validation. No default broker URL is inferred.

## Verification

Ordinary backend checks: 665 passed, 270 integration cases skipped; Ruff lint/format checks 131 files and Pyright reports zero errors/warnings. With isolated real PostgreSQL and Redis, all 935 tests pass. Frontend remains green: 120 tests, lint, TypeScript and build. Tests include malformed URLs/queues, missing configuration, unvalidated Celery override rejection, secret-safe failure, JSON-only task policy, no result backend, no workflow task registered, API startup with unavailable Redis, real worker/probe delivery, graceful shutdown, bounded producer failure and worker startup failure without exposing the password. A worker controller is used because the Celery Python CLI wrapper did not reliably propagate its exit status in our test.

To repeat real integration checks using disposable local services:

```bash
docker compose --profile test up -d --wait postgres_test redis_test
TEST_DATABASE_URL=postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test \
TEST_REDIS_URL=redis://127.0.0.1:16380/15 \
uv run --directory backend --locked python scripts/check.py --integration --redis-integration
```

Redis integration is independently selectable with `--redis-integration`; PostgreSQL integration retains its existing `--integration` switch. The Redis tests require the dedicated localhost port/database, use random queue names, and remove only their own queue keys; they never issue FLUSHDB. No private `.env` is read by the test worker subprocess.

## Limits and next steps

The local Redis service is ephemeral. Publishing and Redis acknowledgements do not establish durable workflow execution, exactly-once processing or crash recovery. Celery documents that Redis messages can be redelivered after visibility timeout and that long delays require special care: [Celery Redis transport documentation](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html). Configuration behavior is described in the [Celery configuration documentation](https://docs.celeryq.dev/en/stable/userguide/configuration.html).

6B will add a PostgreSQL transactional outbox and dispatcher. 6C adds worker claims, leases and crash recovery; 6D adds durable retry scheduling. Only after those are tested will Phase 7 integrate the Groq free-plan provider: capability/model discovery, timeout and rate-limit handling, then an LLM node and reviewed workflow generation. The available free models and limits must be checked for the actual account at that time; no model key is needed for 6A.

Exercise: start the worker, publish a probe, and match the UUID in its log. Stop Redis, retry the probe and observe the static failure; then restart Redis and the worker. Explain why a successful publish alone does not prove that a workflow ran.

1. Why does the worker require an explicit broker URL?
2. Why are task arguments empty and Celery results disabled for this probe?
3. Why should the API remain usable when an optional broker is down?
4. What failure between a database commit and broker publication requires an outbox?
5. Why is one delivered message not proof of exactly-once execution?
