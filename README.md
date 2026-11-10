# AgentFlow

A workflow editor connected to FastAPI and PostgreSQL. Register, sign in, save immutable workflow versions, validate a graph, run it and inspect actual persisted results. The default app uses the API and starts empty for a new account.

Pure workflows can now run in the background through a durable outbox and a separate
Celery worker, with lease heartbeats and automatic recovery discovery. Background
mode is opt-in; Groq workflows remain synchronous. Eligible background failures now
wait on persisted exponential retry deadlines, releasing the worker between
attempts. See [browser testing and process startup](docs/learning-notes/background-execution.md)
and [scheduled retries](docs/learning-notes/scheduled-retries.md).

## Run locally

Requires Node.js 22.12+, npm, uv and Docker. From the project root:

```bash
npm ci
uv sync --directory backend --locked
docker compose up -d --wait postgres
uv run --directory backend --locked alembic upgrade head
```

Your private `backend/.env` must contain the database URL and a random `AGENTFLOW_JWT_SECRET_KEY`. See the [startup walkthrough](docs/real-backend-walkthrough.md). Preserve existing values; do not overwrite the file with the example.

Start the API in one terminal. These process overrides enable local HTTP cookies and frontend origins, including when an existing `.env` has older settings:

```bash
AGENTFLOW_AUTH_ALLOWED_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173","http://localhost:8000","http://127.0.0.1:8000"]' \
AGENTFLOW_REFRESH_COOKIE_SECURE=false \
uv run --directory backend --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

In another terminal:

```bash
npm run dev
```

Open **http://localhost:5173** and use that hostname consistently. Register, then sign in with your exact password (registration minimum: 8 characters). The frontend supplies `X-AgentFlow-Client: web` and session/CSRF headers.

## Try your own workflow

1. Create a named workflow. Its initial graph is a data-free manual-input → end pipeline.
2. Edit the canvas and node JSON using the server configuration catalog. Executable types: manual, transform, condition, calculator, Groq, JSON parser, classify, extract, HTTP GET, Calculator Agent, merge and end. Groq requires its backend key and provider access. HTTP GET uses a connection created in Integrations.
3. Save, then validate. Invalid drafts can be saved; only executable graphs can run.
4. Enter a JSON input object and run the saved version. Inspect actual input/output, node attempts and skipped branches.
5. Choose 1–3 maximum attempts per pure node for transient failures. On execution details, failed/cancelled pure-node runs offer **Retry full workflow**; active runs offer **Cancel execution**. Earlier attempts and retry parents remain visible. Groq calls are not automatically retried.
6. Browse Executions. Refresh restores the cookie session; saved data remains in PostgreSQL across API restarts.

For branching arithmetic, copy the graph from [branch execution](docs/learning-notes/branch-execution.md) into the editor's definition JSON view. No seed or model key is needed. A stale save returns 409 and retains your draft; download it or explicitly load latest before resolving the conflict. Historical versions are read-only. Failed network requests never automatically resubmit saves or run creation.

## Current scope

Dashboard totals, recent runs, authentication, account identity, workflow search/archive, graph saves, validation and execution history use server data. Appearance is local. Access tokens stay in memory; refresh cookies restore sessions with serialized rotation. Browser Web Locks are required for automatic restoration; unsupported browsers require signing in again.

Groq testing, reviewed workflow generation/edit proposals, JSON parsing, classification/extraction and SSE event replay are available. Integrations manages owned fixed-endpoint HTTP GET connections with optional encrypted credentials. AI proposals can use explicitly selected owned connections; the review shows authorized endpoints. Groq calls now expose specific errors, quota wait guidance and actual reported usage without changing workflow business outputs. See [provider hardening and authorized generation](docs/learning-notes/provider-integration-hardening.md) and [HTTP setup](docs/learning-notes/secure-http-connections.md). A bounded synchronous Calculator Agent is available; see [agent usage and limits](docs/learning-notes/calculator-agent.md). HTTP agent tools, persistent checkpoints, approvals, tracing, profile editing and richer analytics remain to be developed. Opt-in background mode executes pure graphs; external calls stay synchronous without automatic replay/recovery. Run creation uses a command key; after a reload, inspect history before issuing another run.

Earlier prototype pages, fixtures, store and simulator remain as unrouted reference code. The active app does not import them or migrate `agentflow-prototype-v1` storage. Earlier `backend/agentflow/` is also an unintegrated draft.

## Verification and architecture

```bash
npm test
npm run lint
npm run build
uv run --directory backend --locked python scripts/check.py
```

Latest verification: the complete backend checker passed **1301 tests with isolated PostgreSQL and Redis**, Ruff lint/format and Pyright. This includes provider failure/usage history, authorized generation, revocation, migration preservation, worker recovery and command replay. Frontend verification passed **135 tests**, lint, TypeScript and production build. Automated tests stub external responses; separate synthetic live checks verified public HTTP, Groq and the complete API generate/save/run/replay/revoke flow. Browser QA remains unavailable because its access host is disconnected.

Migration head is **0010**. Apply it before restarting the updated API, worker and dispatcher. Phase 6 connects workflow outbox creation, task dispatch, worker execution, heartbeat, recovery discovery and scheduled pure-node retries. External-call graphs require a separate recovery policy before joining automatic worker execution.

Vite proxies relative `/api` requests to `http://127.0.0.1:8000`; set server-side `AGENTFLOW_API_PROXY_TARGET` for a different API port. Preview also proxies. Deployed `dist/` needs a same-origin API reverse proxy, HTTPS cookies and `index.html` fallback; no deployment is configured.

- [Startup and real-data walkthrough](docs/real-backend-walkthrough.md)
- [Queued execution and browser test steps](docs/learning-notes/background-execution.md)
- [Frontend API architecture and learning notes](docs/learning-notes/frontend-api.md)
- [Execution command contracts and learning notes](docs/learning-notes/execution-commands.md)
- [Worker transport and Groq roadmap](docs/learning-notes/worker-transport.md)
- [Backend guide](backend/README.md)
- [Implementation plan](docs/backend-implementation-plan.md)
- [API contracts](docs/api/endpoints.md)
- [Design system](docs/design-system.md)
