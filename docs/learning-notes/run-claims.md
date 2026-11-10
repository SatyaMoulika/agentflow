# View your real workspace and remaining work

The 6 November 2026 [pure worker recovery increment](pure-worker-runner.md) now
integrates claims with actual pure-node execution and interrupted-attempt recovery.
Previously claimed running work can be taken over after lease expiry; the default
claim operation remains queued-only. Workflow outbox/worker wiring is still pending.
The phase snapshots below describe earlier increments.

Phase 6C groundwork adds queued-run claim leases and fencing primitives. Workflow execution remains synchronous; persisted progress, worker recovery, workflow outbox integration and asynchronous dispatch are not yet implemented. See [claim notes](learning-notes/run-claims.md). Prior phase descriptions below are historical.

Phase 6B foundation: migration 0005 adds a durable outbox and leased dispatcher for transport probes. Workflow runs remain synchronous; worker claims/recovery and workflow dispatch remain next. See [outbox notes](learning-notes/transactional-outbox.md). Earlier phase descriptions below are historical.

Current increment: Phase 6A worker transport foundation, 4 November 2026. The default React app uses actual authentication, workflows, validation and execution history in PostgreSQL. A new account starts empty. No demo seed or Groq key is needed. Migration head is 0006; synchronous run POST returns 201.

## Start from the project root

```bash
cd /home/moulika/Desktop/Personal/agentflow
docker compose up -d --wait postgres
uv sync --directory backend --locked
uv run --directory backend --locked alembic upgrade head
http://localhost:5173/login
```

The final command keeps the API running in that terminal. If your shell is already in backend/, omit --directory backend. Do not cd into a second backend directory.

The database/auth settings must be present in your existing private backend/.env before migrations/server startup. The documented local Compose database uses this public development URL:

```dotenv
AGENTFLOW_DATABASE_URL=postgresql+psycopg://agentflow:agentflow_local@127.0.0.1:15432/agentflow
AGENTFLOW_REFRESH_COOKIE_SECURE=false
AGENTFLOW_AUTH_ALLOWED_ORIGINS=["http://127.0.0.1:8000","http://localhost:8000","http://127.0.0.1:5173","http://localhost:5173"]
```

Also configure AGENTFLOW_JWT_SECRET_KEY with your own random local value. Preserve an existing valid key; a new key invalidates previously issued access tokens. If it is not configured, generate a value in your own terminal and save it privately:

```bash
uv run --directory backend --locked python -c 'import secrets; print(secrets.token_hex(32))'
```

No change to your private .env was made for this increment. The local HTTP cookie setting above is for development; production settings require HTTPS. No Groq key is required for these features. A running local PostgreSQL container does not by itself configure the API's database URL. With no database URL, health still works but database-backed endpoints return 503.

## Open the frontend

In a second terminal at the project root:

```bash
npm ci
npm run dev
```

Open http://localhost:5173. Register, then sign in (minimum password length 8; spaces/case are preserved). Create a workflow, edit its canvas/config JSON, save and validate, enter manual JSON input and run. Start with the data-free manual → end graph, or copy the branching definition linked below. Executions shows actual persisted results and skipped attempts. Dashboard counts come from your owned server pages. The frontend supplies the client/CSRF headers automatically.

Use one hostname consistently so cookies stay on the same origin. Vite proxies /api to port 8000 without rewriting browser Origin. The process overrides above apply even if private .env has an older origin list. Production requires HTTPS/Secure cookies, an exact allowed origin, same-origin reverse proxy and index.html fallback. Browser Web Locks are required for automatic session restoration; otherwise sign in again. No CORS permission is needed with this same-origin proxy.

Stale saves retain the draft after 409; download it before explicitly loading latest. Network failures do not automatically resubmit mutations. Repeating the same failed run command in the open editor reuses its idempotency key; after reload inspect history before creating another command. Groq generation/tools, connections, approvals, live events and workers remain unavailable. Earlier browser demo storage is not imported.

### Login returns 200 but the frontend reports a cookie error

HTTP 200 confirms that the backend accepted the credentials; the frontend also needs the matching readable CSRF cookie. For local HTTP, stop the old API process and restart it with the process overrides above, including `AGENTFLOW_REFRESH_COOKIE_SECURE=false`. Keep the frontend at http://localhost:5173 and reload after updating the client.

Switching cookie settings can leave both `agentflow_csrf` and `__Host-agentflow_csrf` on the same host. The client now selects the cookie matching the successful login response and remembers its name for refresh/logout. If both modes are present on a fresh page, it requests a fresh login instead of guessing a refresh credential. Conflicting values for the same cookie name still require clearing the stale cookies.

If the error persists, use DevTools → Application/Storage → Cookies to remove only the AgentFlow refresh/CSRF cookies for localhost, then sign in again. This signs the browser out but does not remove saved database workflows. In Network → login → Cookies, inspect any blocked-cookie reason and cookie attributes (Secure, HttpOnly, Path), without sharing values. Local cookies should be named `agentflow_refresh` (HttpOnly) and `agentflow_csrf` (readable), both with Path `/` and Secure disabled. Production continues to require HTTPS/Secure cookies. Changing access-token TTL does not fix cookie delivery.

## Use your own data through Swagger

Open **http://127.0.0.1:8000/docs** in your browser. Keep the same hostname throughout login and cookie operations. Health at /api/v1/health checks process liveness only.

1. Expand POST /api/v1/auth/register, choose Try it out, enter your own email/display name and a new password of 8–128 characters, then Execute. The 201 response is the account stored in PostgreSQL. Registration does not sign you in. If the account already exists, use login.
2. Expand POST /api/v1/auth/login. Enter that email/password and set X-AgentFlow-Client to web. Swagger runs on the allowed API origin; the browser supplies Origin. Execute and copy access_token from the 200 response.
3. Choose Authorize near the top of the page. Paste the access token itself into AccessBearer, without adding a second Bearer prefix. Call GET /api/v1/auth/me to confirm the current account. Tokens expire after 15 minutes by default; login again when needed.
4. Call GET /api/v1/node-types. It returns six real configuration contracts: manual, transform, condition, calculator, merge and end. All six now report execution_ready true and validate_config/execute capabilities. This catalog read only describes contracts; running requires the explicit command below.
5. Call POST /api/v1/workflows with your own name/description and optional definition. The following is an editable example, not preloaded demo data:

```json
{
  "name": "My first stored workflow",
  "description": "Created through the real API",
  "definition": {
    "schema_version": "1.0",
    "nodes": [
      { "id": "start", "type": "manual", "config": {} },
      {
        "id": "select",
        "type": "transform",
        "config": { "operation": "pick_fields", "fields": ["CustomerID"] }
      },
      { "id": "finish", "type": "end", "config": {} }
    ],
    "edges": [
      { "id": "e1", "source": "start", "target": "select", "source_handle": "default" },
      { "id": "e2", "source": "select", "target": "finish", "source_handle": "default" }
    ]
  }
}
```

6. The 201 response contains workflow id, owner_id, current_version_id, current_version_number and version.definition. Use the returned workflow UUID with GET /api/v1/workflows/{workflow_id}; GET /api/v1/workflows lists your nonarchived workflows. An empty listing means you have no matching stored workflows, not an invitation to seed simulated values.
7. PATCH the workflow with a changed definition and expected_version equal to the current_version_number returned by the server. Save together with name/description if desired. A stale number returns 409 and rolls back the entire edit. Use version_id with the item GET to inspect a previous snapshot. Metadata-only PATCH does not require expected_version.
8. Call POST /api/v1/workflows/{workflow_id}/validate with {} to validate the current saved definition. Use {"version_id":"<saved-uuid>"} for history, or {"definition":{...}} for an unsaved candidate. A supported graph returns valid true and a plan summary; semantic problems return valid false with static diagnostics. The supported example returns execution_ready true. Valid condition/calculator/merge graphs are now executable too; readiness still does not guarantee runtime input fields/types. The example graph above is supported; this check does not run or save it.
9. Call POST /api/v1/workflows/{workflow_id}/runs with `{"workflow_version_id":"<current_version_id from the save>","input":{"CustomerID":42,"omit":"test-only value"}}`. Replace the UUID placeholder. Optionally set Idempotency-Key to a fresh UUID and reuse it only for the same intended command. The synchronous 201 returns status succeeded and output `{"CustomerID":42}` for the pick_fields example above. Its node_runs contain actual manual/transform/end inputs/results/times; version pins the exact saved snapshot. Unkeyed POST creates a distinct run. A matching keyed command retrieves the original history without starting execution again.
10. Follow Location or call GET /api/v1/runs/{run_id}. It returns the owned persisted run, exact version and attempt history with no-store. To inspect a real failure, create another run with input {}: the transform cannot find CustomerID, so 201 has status failed/error_code EXECUTION_FAILED, no end attempt and no run output. A created run is not necessarily successful execution. Storage failure can return 503 with Location for a known committed run; earlier start history can remain queued/running pending future recovery.
11. Restart the API and read the same workflow and run IDs again after login/authorization as needed. The Compose development volume retains its saved metadata/history. DELETE archives it; include status=archived when listing archived workflows. Archive preserves versions and prevents further edits.

You will see actual server-assigned IDs/timestamps, saved definitions and real pure-node run results/history. Run history stays pinned after another definition save or workflow archive. Run listing, basic totals and frontend API adapters are implemented. Token usage, approvals, traces and Groq generation remain pending. Draft storage remains permissive; validation checks topology/config/reference availability, and run creation independently recompiles the exact saved version before executing. Validity/readiness does not prove runtime fields exist or guarantee success. Failed writes/crashes can leave retained queued/running history; automatic recovery is a later module.

For refresh/logout cookie details, errors and configuration, see the [backend guide](../backend/README.md). For graph rules and diagnostics, see [workflow validation](learning-notes/workflow-validation.md). For version-save JSON examples, see [workflow versions](learning-notes/workflow-versions.md). The API's current contract is in [endpoints](api/endpoints.md).

## Try a real conditional calculation

Create another workflow using the full definition in [the Phase 5C branching example](learning-notes/branch-execution.md#a-runnable-graph). Validate it, then use its exact saved version UUID with the same run POST:

- input {"amount":11} runs the true branch and returns {"result":22}; plus is recorded skipped.
- input {"amount":4} runs the false branch and returns {"result":5}; double is recorded skipped.
- input {"amount":"11"} creates a failed run with EXECUTION_FAILED at the condition; numeric strings are not silently converted.

GET the run to inspect the chosen route, actual calculator/merge results and the unchosen skipped attempt (no output/start, duration 0). Restart and read the same ID; later graph saves do not rewrite old history. Completion skips commit only with a successful end; failures stop with actual failed attempt history and no completion skips. No Groq key, demo seed, frontend simulator or extra endpoint is involved. See the linked notes for exact scalar/arithmetic bounds, missing-field behavior, nested/early-end rules and tests.

## What remains

| Stage                               | Remaining work and visible result                                                                                                                                                                                                           |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 5 — deterministic execution         | 5A storage, 5B initial execution and 5C condition/calculator/exclusive-merge execution/skips are complete. 5D command idempotency, bounded pure retries, cancellation and full-workflow retry lineage are also complete.                    |
| 6 — background work                 | Redis/Celery, transactional outbox, dispatch, run claims/leases, crash recovery and scheduled retries.                                                                                                                                      |
| 7 — Groq and controlled tools       | Groq Free Plan adapter, verified account model/capabilities, actual LLM results, reviewed generation/edit proposals, protected connections and SSRF-safe HTTP; explicitly supported classify/extract/parser capabilities. No paid fallback. |
| 8 — agents                          | Bounded LangGraph tools, authorized capability selection and persistent agent checkpoints.                                                                                                                                                  |
| 9 — live observability              | Correlated spans, optional Phoenix, authorized SSE event replay/reconnect, real available usage telemetry.                                                                                                                                  |
| 10 — approvals                      | Durable waiting, authorized approve/reject/expiry and safe resume/recovery after restart.                                                                                                                                                   |
| 11 — frontend integration/hardening | Initial auth/workflow saves/conflicts and run history are implemented. Remaining: events/approvals UI, scoped richer aggregates/profile editing, browser QA and deployment hardening.                                                       |

Foundation, PostgreSQL/migrations, authentication, workflow metadata/versioning, typed contracts, validation/compiler, execution storage and synchronous six-type pure execution with exclusive routing/skips are implemented. Phase 5D is complete. Phase 6A now verifies a separate Redis/Celery transport probe. Next is 6B outbox/dispatch, then claims/leases and crash recovery. Groq starts in Phase 7 after those components are tested. See [execution command notes](learning-notes/execution-commands.md) for functions, flow, exact rules and actual checks. Dashboard uses actual workflow/run totals; richer aggregates and persistent editable profile/preferences still need contracts. The [implementation plan](backend-implementation-plan.md) contains the full sequence.

## Use the new execution commands

After updating an existing checkout, run `uv run --directory backend --locked alembic upgrade head` before restarting the backend. This increment adds migration 0004; your existing workflows/history are retained. The development database used during implementation is already upgraded.

In the editor, select Maximum attempts per node (1–3). Only internal/deadline failures are eligible; input/type/arithmetic errors stop immediately. The frontend generates command keys automatically and preserves an unresolved key in that open editor. Do not reload and blindly resubmit after a lost response.

On Executions → an active execution, Cancel execution atomically cancels open attempts and retains completed history. Short synchronous runs may finish before cancellation is submitted; use another tab to inspect an in-flight run. Failed/cancelled runs offer Retry full workflow. This creates a new child run using the original input/version from the beginning, with one automatic attempt per node, and leaves parent history unchanged. Newer graph saves do not affect it. Archived workflows cannot start a fresh retry.

For Swagger run creation, optionally set Idempotency-Key to a fresh UUID and include `"max_attempts":2` in the existing run body. Resubmit exactly the same key/body to retrieve the same run; changed input/version/budget returns 409. Both new and replayed commands return 201 and Location; a replay may be queued/running without dispatching again. POST /runs/{run_id}/retry accepts `{}` or `{"max_attempts":2}` with its own optional key. POST /runs/{run_id}/cancel takes no body; repeated cancellation returns 200, other terminal states 409. All operations require your Bearer token and ownership.

See [Phase 5D learning notes](learning-notes/execution-commands.md) for concurrency rules, failure limits, tested behavior and an exercise. Workers, automatic crash recovery, provider calls and live events remain future work.

## Optional worker transport probe

Phase 6A adds a separate Redis/Celery probe process; workflows still execute synchronously in the API. To try it, start local Redis with `docker compose --profile worker up -d --wait redis`, then follow the worker and probe commands in [worker transport notes](learning-notes/worker-transport.md). The probe carries no workflow data. Publishing does not by itself prove worker consumption; match its UUID with the worker log.

The API can continue operating if Redis is unavailable. Durable workflow dispatch/outbox, worker claims, crash recovery and scheduled retries remain 6B–6D. Groq free-plan integration begins in Phase 7; the actual model must be checked against the account's available free models then.

## Keys and local settings

The working registration/login and deterministic workflow features require a private backend `AGENTFLOW_JWT_SECRET_KEY` and configured `AGENTFLOW_DATABASE_URL`. The JWT key is a locally generated signing secret, not an external provider API key. Preserve your existing key; replacing it invalidates previously issued access tokens. If you have not configured one, generate it locally with `uv run --directory backend --locked python -c 'import secrets; print(secrets.token_hex(32))'` and add it privately to `backend/.env` as `AGENTFLOW_JWT_SECRET_KEY=<value>`. Do not share its value.

`AGENTFLOW_REDIS_URL` is optional for the worker transport probe and is a connection URL, not an AI API key. The current synchronous API does not need Redis. No frontend `.env` or provider key is needed for the current features.

Groq is planned for Phase 7. You can create a GroqCloud API key at [Groq API Keys](https://console.groq.com/keys) and keep it private; this project does not yet load or use a Groq key. The user has chosen `GROQ_API_KEY` and `openai/gpt-oss-120b`; the adapter will load the private key and keep the model configurable when implemented. Check free-plan model availability and limits in your own Groq account; no paid provider fallback is planned.

## Claim-fenced worker state foundation

`app/modules/executions/worker_state.py` exposes internal run transitions, atomic attempt creation/start, and attempt result/failure writes. Each operation opens a unit of work, checks owner and live claim while holding the run-row lock, and performs the state/event write before commit. Terminal attempt failure can atomically fail the run. A cancellation, expired lease or replacement claim blocks subsequent writes; a transaction that already holds the lock commits before a competing cancellation. Database/event failures roll back all writes in that transaction. No computation or network call occurs inside these transactions.

This is not wired to the current synchronous runner or Celery worker. It does not yet implement fenced completion with branch skips, interrupted-attempt reconciliation, running-run takeover, heartbeat, process-kill recovery or workflow outbox dispatch. Those remain prerequisites before asynchronous workflow execution can be enabled. Real PostgreSQL integration tests cover owner isolation, stale claims, cancellation, atomic terminal failure, rollback and lock ordering. No schema migration or provider call was added.
