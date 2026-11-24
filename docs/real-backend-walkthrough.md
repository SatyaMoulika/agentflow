# View your real workspace and remaining work

The **Tool Agent** node is available for bounded Groq loops using the local calculator and explicitly selected HTTP GET connections. Follow the [HTTP agent sample and review checklist](learning-notes/http-agent.md), or the [calculator-only example](learning-notes/calculator-agent.md). It runs synchronously and can explicitly continue from saved post-tool pauses; see [checkpoint setup and limits](learning-notes/agent-checkpoints.md). Unknown in-flight external calls are not automatically recovered.

AI generation now supports explicitly selected owned HTTP connections. Edits also
authorize existing bindings. Groq requests expose provider-specific failures, safe
quota guidance and actual usage metadata in execution history. Apply migration
**0010**; see [provider/integration setup and verification](learning-notes/provider-integration-hardening.md).

Phase 7E adds **HTTP connections** in Integrations and an **HTTP GET** editor node.
Apply the current migration head before running the updated API. Authenticated connections
need the new private encryption setting; no-auth connections do not. See
[setup and limits](learning-notes/secure-http-connections.md). Existing private
configuration and development data were preserved.

The **Classify text with Groq** node chooses one of its configured labels and
outputs `model` and `label`. The **Extract fields with Groq** node returns `model`
and `fields`, with each requested field containing text or null. Both send the
selected input text to Groq, run synchronously and are excluded from automatic
retry and background recovery. Their output shape is checked, but model answers
can be inaccurate; review them for your use case.

The **Parse JSON text** node parses one selected input field as a JSON object and
passes the resulting object to the next node. It accepts at most 64 KiB of text,
rejects duplicate keys, non-object results and invalid JSON, and keeps business
keys unchanged. It is a deterministic node and can run in background workflows.
It does not extract structured information from free-form text.

Execution events can be read through the authenticated
`GET /api/v1/runs/{run_id}/events` API or streamed from
`GET /api/v1/runs/{run_id}/events/stream`. The paginated API returns up to 100
events per request and a `next_after_sequence` cursor. The stream emits event IDs
and supports replay using `Last-Event-ID`; connections periodically close for
reauthentication. Runs belonging to another user return the same 404 as missing
runs. The execution-details page uses the stream for active runs and falls back to
polling. Streaming only reports persisted events; trace export remains future work.

Phase 6D adds [scheduled retries](learning-notes/scheduled-retries.md) for transient
pure-node failures. Apply the current migration head and restart API/worker/dispatcher. Default
retry waits are 5 then 10 seconds within the saved 1–3 attempt budget; no new `.env`
values are required. Execution details show the pending retry time and retained
attempt history. Deterministic input/arithmetic failures are not retried.

**Queued execution is now available for pure graphs.** Follow the [background
execution browser walkthrough](learning-notes/background-execution.md) to migrate to
head and start the API, Redis, worker, dispatcher and frontend. Background mode is
opt-in; execution details refresh while active. Groq graphs remain synchronous.
The earlier runner-only progress notices below are historical.

## Generate a workflow from a prompt

Restart the backend and frontend, sign in, open **Workflows → Create workflow**,
and enter a request under **Generate with AI**, for example:

> Create a workflow that receives a customer support message and drafts a helpful response.

Select **Generate proposal**. Your request is sent to Groq. Review the proposed
nodes, connections, definition, and suggested test input. Validation checks that
the graph is executable using supported node types; it cannot guarantee the result
matches your intent. Copy the suggested input if you want to use it later. Select
**Create from proposal** to save the draft and open the editor; then validate and
run it yourself. Generation alone does not save or run a workflow. Unsupported
capabilities such as sending email are not implemented; the model is instructed
to report those requests, but you should review every proposal for omissions.

The generator requires `GROQ_API_KEY` and uses the configured `AGENTFLOW_GROQ_MODEL`.
The provider may refuse, time out, or return a malformed graph; no example or demo
workflow is substituted. When a proposal fails validation, the original request and
static diagnostic codes may be sent to Groq once more for a new proposal. Provider
errors and rate limits are not retried. To propose changes to an existing saved
workflow, open its editor, save any outstanding edits and use **Propose changes
with AI**. The saved definition and request are sent to Groq. Review the summary of
added, removed and changed nodes and connections alongside the full proposed
definition, apply it to the editor, and save it separately. Only the definition
is applied; the workflow name and description stay unchanged. The save checks the
original version and rejects a conflicting newer save. The calculator supports addition,
subtraction, multiplication and division; its operands can refer to upstream outputs.
Generation/edit requests allow up to 4,096 completion tokens; a large graph can still
exceed this budget. If that happens, try a smaller change or make the edit directly.
For the optional synthetic evaluation suite, see [workflow generation evaluation](workflow-generation-evaluation.md).

## Groq connection

Set `GROQ_API_KEY` in the existing private `backend/.env`. The default model is
`openai/gpt-oss-120b`; optionally set `AGENTFLOW_GROQ_MODEL` to another model available
to your Groq account. Restart the backend after changing settings. Sign in, open
**Integrations**, enter a prompt, and select **Send to Groq**. The prompt is sent to
Groq and the API key stays on the server. Check your account's free-plan model
availability and limits. You can also add the Groq LLM node to a workflow as described
below. Provider failures are shown as errors; there is no automatic provider retry or fallback.

### Try a Groq workflow

Create a workflow, select **Definition JSON**, and replace its definition with:

```json
{
  "schema_version": "1.0",
  "nodes": [
    { "id": "start", "type": "manual", "config": {} },
    {
      "id": "answer",
      "type": "groq",
      "config": {
        "instruction": "Draft a helpful, concise customer support response to this message.",
        "input_field": "message"
      }
    },
    { "id": "finish", "type": "end", "config": {} }
  ],
  "edges": [
    { "id": "e1", "source": "start", "target": "answer", "source_handle": "default" },
    { "id": "e2", "source": "answer", "target": "finish", "source_handle": "default" }
  ]
}
```

Save, validate, and run the saved version with:

```json
{ "message": "My order arrived damaged. How can I request a replacement?" }
```

The node sends the instruction and selected string field to Groq and returns
`{"model": "...", "content": "..."}`. Both inputs and results are retained in
run history. The combined prompt is limited to 4,000 characters. A missing/non-string
field stops the run with `EXECUTION_FAILED`; provider failures use the specific codes documented in [provider hardening](learning-notes/provider-integration-hardening.md); the run does not
automatically retry the provider, and full-workflow retry is disabled for graphs with
Groq or HTTP nodes. You can explicitly start a new run, which can make another provider call.
Cancellation cannot undo a request already sent, and a crash after the provider call
may leave an incomplete run. No automatic recovery of provider calls is implemented.

The outbox uses PostgreSQL and Redis. It dispatches workflow runs and probes; pure workflow recovery and scheduled retries are implemented. The default React app uses actual authentication, workflows, validation, integrations and execution history. A new account starts empty. Source migration head is **0014**; apply it before running the updated backend. Checkpoint storage was set up locally on 12 November 2026. Run the [checkpoint setup command](learning-notes/agent-checkpoints.md) for other databases before using agent nodes. [Gmail connection setup and manual message reading](learning-notes/gmail-connection.md) require separate Google OAuth configuration; automatic triggers and email actions remain in progress.

## Start from the project root

```bash
cd /home/moulika/Desktop/Personal/agentflow
docker compose up -d --wait postgres
uv sync --directory backend --locked
uv run --directory backend --locked alembic upgrade head
uv run --directory backend --locked python scripts/setup_agent_checkpoints.py
AGENTFLOW_REFRESH_COOKIE_SECURE=false \
AGENTFLOW_AUTH_ALLOWED_ORIGINS='["http://localhost:5173","http://127.0.0.1:5173","http://localhost:8000","http://127.0.0.1:8000"]' \
uv run --directory backend --locked uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --reload
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

Stale saves retain the draft after 409; download it before explicitly loading latest. Network failures do not automatically resubmit mutations. Repeating the same failed run command in the open editor reuses its idempotency key; after reload inspect history before creating another command. Protected HTTP GET connections are available in Integrations; [owner approvals](learning-notes/approvals.md) are available for pure background workflows. Earlier browser demo storage is not imported.

### Login returns 200 but the frontend reports a cookie error

HTTP 200 confirms that the backend accepted the credentials; the frontend also needs the matching readable CSRF cookie. For local HTTP, stop the old API process and restart it with the process overrides above, including `AGENTFLOW_REFRESH_COOKIE_SECURE=false`. Keep the frontend at http://localhost:5173 and reload after updating the client.

Switching cookie settings can leave both `agentflow_csrf` and `__Host-agentflow_csrf` on the same host. The client now selects the cookie matching the successful login response and remembers its name for refresh/logout. If both modes are present on a fresh page, it requests a fresh login instead of guessing a refresh credential. Conflicting values for the same cookie name still require clearing the stale cookies.

If the error persists, use DevTools → Application/Storage → Cookies to remove only the AgentFlow refresh/CSRF cookies for localhost, then sign in again. This signs the browser out but does not remove saved database workflows. In Network → login → Cookies, inspect any blocked-cookie reason and cookie attributes (Secure, HttpOnly, Path), without sharing values. Local cookies should be named `agentflow_refresh` (HttpOnly) and `agentflow_csrf` (readable), both with Path `/` and Secure disabled. Production continues to require HTTPS/Secure cookies. Changing access-token TTL does not fix cookie delivery.

## Use your own data through Swagger

Open **http://127.0.0.1:8000/docs** in your browser. Keep the same hostname throughout login and cookie operations. Health at /api/v1/health checks process liveness only.

1. Expand POST /api/v1/auth/register, choose Try it out, enter your own email/display name and a new password of 8–128 characters, then Execute. The 201 response is the account stored in PostgreSQL. Registration does not sign you in. If the account already exists, use login.
2. Expand POST /api/v1/auth/login. Enter that email/password and set X-AgentFlow-Client to web. Swagger runs on the allowed API origin; the browser supplies Origin. Execute and copy access_token from the 200 response.
3. Choose Authorize near the top of the page. Paste the access token itself into AccessBearer, without adding a second Bearer prefix. Call GET /api/v1/auth/me to confirm the current account. Tokens expire after 15 minutes by default; login again when needed.
4. Call GET /api/v1/node-types. It returns the current registered configuration contracts, including pure nodes, Groq, classify/extract, JSON parsing and HTTP GET. Each reports execution readiness; a Groq run additionally requires its key and provider access. This catalog read only describes contracts; running requires the explicit command below.
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

You will see actual server-assigned IDs/timestamps, saved definitions and real run results/history. Run history stays pinned after another definition save or workflow archive. Run listing, basic totals, AI edit proposals and frontend API adapters are implemented. Reported provider usage is available; owner approvals are implemented for pure background workflows; live trace acceptance remains pending. Draft storage remains permissive; validation checks topology/config/reference availability, and run creation independently recompiles the exact saved version before executing. Validity/readiness does not prove runtime fields exist or guarantee success.

For refresh/logout cookie details, errors and configuration, see the [backend guide](../backend/README.md). For graph rules and diagnostics, see [workflow validation](learning-notes/workflow-validation.md). For version-save JSON examples, see [workflow versions](learning-notes/workflow-versions.md). The API's current contract is in [endpoints](api/endpoints.md).

## Try a real conditional calculation

Create another workflow using the full definition in [the Phase 5C branching example](learning-notes/branch-execution.md#a-runnable-graph). Validate it, then use its exact saved version UUID with the same run POST:

- input {"amount":11} runs the true branch and returns {"result":22}; plus is recorded skipped.
- input {"amount":4} runs the false branch and returns {"result":5}; double is recorded skipped.
- input {"amount":"11"} creates a failed run with EXECUTION_FAILED at the condition; numeric strings are not silently converted.

GET the run to inspect the chosen route, actual calculator/merge results and the unchosen skipped attempt (no output/start, duration 0). Restart and read the same ID; later graph saves do not rewrite old history. Completion skips commit only with a successful end; failures stop with actual failed attempt history and no completion skips. No Groq key, demo seed, frontend simulator or extra endpoint is involved. See the linked notes for exact scalar/arithmetic bounds, missing-field behavior, nested/early-end rules and tests.

## What remains

| Stage                               | Remaining work and visible result                                                                                                                                                                                                                                                                                 |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 5 — deterministic execution         | 5A storage, 5B initial execution and 5C condition/calculator/exclusive-merge execution/skips are complete. 5D command idempotency, bounded pure retries, cancellation and full-workflow retry lineage are also complete.                                                                                          |
| 6 — background work                 | Workflow intents, task dispatch/consumption, pure worker recovery, expired-work discovery and heartbeat are implemented in opt-in mode. Scheduled node retries are now implemented. Remaining: further load/deployment checks and external-effect reconciliation.                                                 |
| 7 — Groq and controlled tools       | Groq generation/edits, JSON parsing, classification/extraction, protected HTTP GET, provider error/usage hardening and authorized connection selection are implemented. Browser QA remains unavailable. OAuth/credential rotation and broader HTTP methods/reconciliation are future expansion. No paid fallback. |
| 8 — agents                          | Bounded calculator and authorized HTTP tools support persisted checkpoints and explicit continuation after tool results. Unknown in-flight requests are not automatically recovered.                                                                                                                              |
| 9 — live observability              | SSE replay/reconnect/heartbeat, provider usage, background trace context correlation and opt-in local Phoenix export are implemented. Real collector and cross-process acceptance remain to be verified. See [tracing notes](learning-notes/trace-instrumentation.md).                                            |
| 10 — approvals                      | Owner-only waiting, approve/reject, expiry/cancellation and durable worker continuation are implemented for pure background workflows. External-call approval and reconciliation remain future work. See [approvals](learning-notes/approvals.md).                                                                |
| 11 — frontend integration/hardening | Initial auth/workflow saves/conflicts, run history and a streamed events timeline with polling fallback are implemented. Remaining: scoped richer aggregates/profile editing, browser QA and deployment hardening.                                                                                                |

Foundation, PostgreSQL/migrations, authentication, workflow metadata/versioning, typed contracts, validation/compiler, execution storage and synchronous execution of pure nodes and the Groq node are implemented. AI can propose new workflows and version-bound edits for review. Redis/Celery transport probes, an outbox dispatcher for probes, run claims and internal pure-run recovery exist; opt-in workflow dispatch and automatic recovery scheduling are now connected; scheduled node backoff is now implemented. See [execution command notes](learning-notes/execution-commands.md) for execution rules. Dashboard uses actual workflow/run totals; richer aggregates and persistent editable profile/preferences still need contracts. The [implementation plan](backend-implementation-plan.md) contains the full sequence.

## Use the new execution commands

After updating an existing checkout, run `uv run --directory backend --locked alembic upgrade head` before restarting the backend. This increment adds migration 0004; your existing workflows/history are retained. The development database used during implementation is already upgraded.

In the editor, select Maximum attempts per node (1–3). Only internal/deadline failures are eligible; input/type/arithmetic errors stop immediately. The frontend generates command keys automatically and preserves an unresolved key in that open editor. Do not reload and blindly resubmit after a lost response.

On Executions → an active execution, Cancel execution atomically cancels open attempts and retains completed history. Short synchronous runs may finish before cancellation is submitted; use another tab to inspect an in-flight run. Failed/cancelled runs offer Retry full workflow. This creates a new child run using the original input/version from the beginning, with one automatic attempt per node, and leaves parent history unchanged. Newer graph saves do not affect it. Archived workflows cannot start a fresh retry.

For Swagger run creation, optionally set Idempotency-Key to a fresh UUID and include `"max_attempts":2` in the existing run body. Resubmit exactly the same key/body to retrieve the same run; changed input/version/budget returns 409. Both new and replayed commands return 201 and Location; a replay may be queued/running without dispatching again. POST /runs/{run_id}/retry accepts `{}` or `{"max_attempts":2}` with its own optional key. POST /runs/{run_id}/cancel takes no body; repeated cancellation returns 200, other terminal states 409. All operations require your Bearer token and ownership.

See [Phase 5D learning notes](learning-notes/execution-commands.md) for concurrency rules, failure limits, tested behavior and an exercise. Opt-in pure workflow workers and recovery are available; live events are available through authenticated SSE with polling fallback.

## Optional worker transport probe

A separate Redis/Celery probe process is available alongside opt-in background pure workflow execution. To try it, start local Redis with `docker compose --profile worker up -d --wait redis`, then follow the worker and probe commands in [worker transport notes](learning-notes/worker-transport.md). The probe carries no workflow data. Publishing does not by itself prove worker consumption; match its UUID with the worker log.

The API can continue operating if Redis is unavailable. Opt-in workflow dispatch and pure worker recovery are implemented; scheduled node backoff is now implemented. Groq model availability and free-plan limits depend on your account.

## Keys and local settings

The working registration/login and deterministic workflow features require a private backend `AGENTFLOW_JWT_SECRET_KEY` and configured `AGENTFLOW_DATABASE_URL`. The JWT key is a locally generated signing secret, not an external provider API key. Preserve your existing key; replacing it invalidates previously issued access tokens. If you have not configured one, generate it locally with `uv run --directory backend --locked python -c 'import secrets; print(secrets.token_hex(32))'` and add it privately to `backend/.env` as `AGENTFLOW_JWT_SECRET_KEY=<value>`. Do not share its value.

`AGENTFLOW_REDIS_URL` is optional for the worker transport probe and is a connection URL, not an AI API key. Synchronous API execution does not need Redis; opt-in background execution needs Redis, a worker and the dispatcher. No frontend provider key is used; Groq features need the backend key.

The Groq connection, workflow node and generator load `GROQ_API_KEY` on the backend. Check free-plan model availability and limits in your own Groq account; no paid provider fallback is planned.
