# Verification

## Saved workflow run forms — 19 November 2026

The run section lists saved workflows and opens the current saved version with user-defined text, number and boolean input fields. Definitions are stored inside existing version metadata. Direct manual-to-tool input fields can be suggested; missing or malformed metadata retains the advanced JSON path. Tests cover suggestions, typed inputs, defaults, key preservation, malformed definitions and the rendered run form. The form is client-side guidance rather than an API validation policy. Browser acceptance remains pending because the browser access host was unavailable.

## Execution output presentation — 19 November 2026

Execution details render a successful Groq or Tool Agent result as Markdown when the stored run output matches that node's actual output. The full stored JSON remains available in a collapsed disclosure; other business JSON remains in its original viewer. Rendering ignores raw HTML and remote images, and filters unsafe links. The approvals navigation icon is distinct from integrations. Frontend checks passed **152 tests**, ESLint and the production build. Tests cover Markdown output, raw data access, ordinary business JSON and unsafe content. Browser visual acceptance was unavailable because the browser access host could not be reached.

## Agent HTTP response bound — 19 November 2026

Raised the per-result agent HTTP bound from 16 KiB to 32 KiB while retaining the 60,000-byte conversation limit. A live unauthenticated read of the reported public GitHub pull-request endpoint returned 17,119 bytes, exceeding the former bound; the controlled executor then fetched it successfully with the new limit. No credentials, payload output or database writes were used. Backend tests passed **950** with **448 opt-in integration tests skipped**; Ruff lint, Pyright and formatting of the changed Python files passed. The standard checker stopped at Ruff formatting because of a pre-existing whitespace change in migration 0013, which was preserved. The automated agent test verifies a medium result reaches the provider and an oversized result is rejected. No live Groq or browser end-to-end run was performed.

## GitHub connection form — 18 November 2026

The active Integrations page now offers a GitHub form that creates owner-scoped existing HTTP connections for a repository's issues or pull requests. Frontend checks passed **149 tests**, ESLint, TypeScript and the production build. Tests cover safe endpoint construction and the rendered connection form. No backend, database or migration change was made. Browser acceptance was unavailable because the browser access host could not be reached; no authenticated live GitHub request was made. Collection size and pagination limitations remain as described in the [GitHub guide](learning-notes/github-read-connection.md).

## Background tracing — 17 November 2026

The full backend checker passed **1,395 tests** with guarded PostgreSQL and Redis. Afterward, a focused **13-test** PostgreSQL/tracing run verified persisted context, worker propagation, immutable trace history and guarded downgrade. Following final exporter header filtering, the ordinary backend checker passed **949 tests**, Ruff lint/format and Pyright, with **448 opt-in integration cases skipped**. The exporter test uses a simulated collector to inspect serialized OTLP spans and confirms environment headers are removed. No live Phoenix collector, separate-process trace acceptance or browser test was performed. The existing test services were left running; the development database was not migrated.

## GitHub HTTP compatibility — 16 November 2026

The HTTP executor now sends the fixed application header `User-Agent: AgentFlow/0.1`, required by GitHub's REST API. The standard backend checker passed **944 tests**, Ruff lint/format and Pyright, with **446 opt-in integrations skipped**. One unauthenticated request to GitHub's public `octocat/Hello-World` repository passed through the controlled executor without credentials, database writes or response-payload output. No frontend or schema change was made, so frontend and full database/Redis integration checks were not repeated. Authenticated private-repository reads and browser acceptance remain pending. See the [setup and limits](learning-notes/github-read-connection.md).

## Tool agents and Gmail connection snapshot — 16 November 2026

The complete backend checker passed **1,390 tests** with guarded disposable PostgreSQL and Redis, Ruff lint/format and Pyright. Frontend verification passed **146 tests**, ESLint, TypeScript and the production build. The initial backend run identified an outdated node-catalog assertion; adding the implemented `gmail_read` type made the complete rerun pass. The saved-node container check in the Gmail AI-edit guard was also narrowed explicitly to resolve four Pyright errors.

This snapshot includes authorized HTTP agent tools, persistent checkpoints and explicit continuation, in-process trace hooks, provider transport/proposal-budget fixes, owned Gmail OAuth connections and manual message reading. Automated provider responses are fixtures; no live Google/Groq call or browser acceptance check was performed. Gmail triggers, approvals and email actions remain unavailable.

Both isolated test services were already running and were left running. Tests used disposable schemas/queues; development migrations, volumes and data were not changed. Candidate files and the earlier outgoing commit were scanned for configured private values and recognizable credential patterns, with no findings. The private `backend/.env` remains ignored and unchanged.

## Gmail provider foundation — 13 November 2026

The ordinary backend checker passed **944 tests**, with **438 opt-in integration tests skipped**, plus Ruff lint/format and Pyright. Gmail tests use synthetic HTTP responses for read-only authorization, PKCE, bounded Gmail reads, safe errors and plain-text extraction. No real Google account or network call was used; no OAuth connection, Gmail workflow node, trigger, approval or action is exposed by this increment. See the [implementation plan](gmail-implementation-plan.md).

## Workflow proposal output budget — 12 November 2026

The standard backend checker passed **932 tests**, with **438 opt-in integration tests skipped**, plus Ruff lint/format and Pyright. A focused guarded PostgreSQL run passed **49 run and connection integration tests**. Provider fixtures verify the proposal-specific completion budget and that truncated output is rejected without an automatic retry; no live Groq call or browser acceptance test was performed.

## Phase 9A instrumentation foundation — 11 November 2026

The standard backend checker passed **930 tests**, with **438 opt-in integration tests skipped**, plus Ruff lint/format and Pyright. A separate focused run against guarded disposable PostgreSQL passed **49 agent and worker integration tests**. New tracing tests use a recording test double to verify parent context across the FastAPI threadpool, fixed names, exception privacy and fail-open instrumentation. No SDK/exporter, live collector, cross-process trace propagation or browser check was exercised. Frontend source did not change in this increment; the Phase 8C frontend results below are the previous baseline. See [tracing notes](learning-notes/trace-instrumentation.md).

## Phase 8C — 11 November 2026

The complete backend checker passed **1,364 tests** with guarded disposable PostgreSQL and Redis, Ruff lint/format and Pyright. The focused agent integration suite passed **26 tests**, covering saved continuation after a fresh application/database connection, owner and stale-checkpoint rejection, cancellation, concurrent continuation and HTTP non-replay. Frontend checks passed **141 tests**, ESLint, TypeScript and the production build. These checks use provider fixtures; no new live Groq or browser acceptance test was run.

The source migration head is **0011**. This run did not migrate the development database or set up its checkpoint schema. The pre-existing PostgreSQL test service was retained; the Redis test service started for this run was stopped. See [checkpoint setup and limits](learning-notes/agent-checkpoints.md).

## Phase 8B — 10 November 2026

The latest full backend checker passed **1,351 tests** against guarded disposable PostgreSQL/Redis, Ruff lint/format (**208 Python files**) and Pyright with zero errors/warnings. Frontend checks passed **137 tests across 11 files**, ESLint, TypeScript and the production build. No migration or dependency was added; head remains **0010**. The pre-existing PostgreSQL test service was retained; only the Redis test service started for this increment was stopped/removed afterward.

New deterministic tests exercise the real LangGraph tool conversation, explicit empty/default capabilities, owner-bound allowlists, extra-argument rejection, endpoint alias deduplication, revocation before/after model/tool calls, cancellation, HTTP error summaries, response/conversation bounds, old config/history compatibility and agent-aware proposal authorization. Isolated API tests prove credentials stay out of provider messages/history, storage transactions close before external I/O, metadata/result atomicity and command replay without further calls. Controlled transport tests prove all DNS answers are validated before IPv4 preference/TCP fallback, only one HTTP GET is sent, and fallback stops at the shared deadline.

The first synthetic live HTTP agent exercise failed before receiving endpoint data because the local IPv6 route stalled. The controlled HTTP executor now prefers validated IPv4 answers and may try another validated address only during TCP setup, before TLS/HTTP; requests are never replayed. After this correction, the sample API create/validate/run/history/replay/revoke flow passed in **18.81 seconds**, making **one actual HTTP GET and three Groq requests**. The fetched slideshow had two slides and the actual calculator returned **20**. Replaying the same command returned identical history without another external call; revocation refused a fresh command without HTTP/Groq. The exercise used synthetic input/public JSON and a random schema in the guarded test database; that schema was removed. It did not insert fixtures into development. This is one model execution, not a reliability estimate.

Follow the [sample guide](learning-notes/http-agent.md), [workflow JSON](examples/http-agent.workflow.json) and [input JSON](examples/http-agent.input.json) to review. Browser discovery was retried and again returned `The browser access host is unavailable`; interactive UI acceptance remains pending. Persistent checkpoints and recovery correlation are **8C**, not part of this increment.

## Groq connectivity follow-up — 10 November 2026

A live local failure was traced to stalled IPv6 connectivity: unauthenticated IPv4 Groq access returned HTTP 401 in about 0.3 seconds, while IPv6 connection setup timed out. The previous client applied the entire 45-second request budget to connection setup. The adapter now caps connect timeouts at five seconds (or the smaller remaining budget), preserving configured read/write/pool timeouts and the single-request policy.

Standard backend checks passed **888 tests**, with **416** opt-in integration cases skipped; Ruff lint/format and Pyright passed. A synthetic live Groq completion passed, and a synthetic live calculator agent completed one actual tool call and two provider requests in **11.17 seconds**. These checks sent no workflow data and wrote nothing to the database. The full PostgreSQL/Redis run below is the preceding Phase 8A baseline; it was not repeated for this transport-only change. Frontend files were unchanged.

## Phase 8A baseline — 10 November 2026

The active application is `src/api/` with `src/App.tsx`, backed by `backend/app/`. Older frontend simulator tests remain useful reference coverage; they do not establish implemented backend agents or approvals.

The Phase 8A full run passed **1,301 backend tests** with isolated PostgreSQL/Redis, Ruff lint/format (205 Python files) and Pyright with zero errors/warnings. Ordinary backend checks skip opt-in PostgreSQL/Redis integration cases; the full run used both integration flags. Frontend checks passed **135 tests across 11 files**, ESLint, TypeScript and the production build.

Development was upgraded additively to **0010**; `alembic current` reports head and `alembic check` reports no new upgrade operations. Development was never used for fixture insertion, destructive tests or migration downgrades.

## Repeatable checks

Run from the project root:

```bash
npm test
npm run lint
npm run build
uv run --directory backend --locked python scripts/check.py

docker compose --profile test up -d --wait postgres_test redis_test
TEST_DATABASE_URL=postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test \
TEST_REDIS_URL=redis://127.0.0.1:16380/15 \
uv run --directory backend --locked python scripts/check.py --integration --redis-integration
```

Tests disable private dotenv loading. PostgreSQL fixtures require the guarded local test database and random disposable schemas; Redis tests require the isolated port/database and randomly named queues. Stop/remove only test services started for your task, preserving pre-existing services and development volumes.

Backend coverage includes authentication/owner isolation, immutable snapshots, concurrency, state/event atomicity, command replay, outbox delivery, worker recovery, scheduled retries, connection authorization/SSRF restrictions, provider failures/usage and migration preservation. Provider responses are deterministic fixtures by default. Frontend coverage includes API/session behavior, business-key preservation, proposals, event reconnect and server-rendered screens, plus legacy simulator cases.

## Live checks and browser limit

Prior synthetic live HTTP/Groq/API checks are recorded in [provider integration hardening](learning-notes/provider-integration-hardening.md). They are separate from the automated suite and consume provider quota only when explicitly enabled. No model-quality success rate or production deployment is claimed.

Browser discovery was retried on 10 November 2026 and returned `The browser access host is unavailable`. Browser hydration, click-through, layout, mobile viewports and accessibility acceptance remain unverified. HTTP/ASGI and server-rendered checks do not replace these checks.

When browser access is available, use the [startup walkthrough](real-backend-walkthrough.md) and verify:

1. Register/sign in, refresh the session and sign out using one consistent hostname.
2. Create/save/validate a workflow; edit and reconnect nodes; retain a draft on a stale-save conflict; inspect an older immutable version.
3. Run a pure branching calculation; inspect outputs, skipped attempts, cancellation, retry lineage and streamed events after reconnect.
4. With worker/dispatcher enabled, queue a pure run and verify progress/recovery and scheduled retry presentation.
5. Review generation/edit proposals and explicit HTTP connection selection before applying/saving. Use synthetic input for optional live Groq checks.
6. Create a no-auth public HTTPS JSON connection, run it explicitly, revoke it and confirm a fresh run is refused. Never use private business data for acceptance fixtures.
7. Follow the [HTTP agent sample](learning-notes/http-agent.md): explicitly select a connection, save/validate, inspect actual HTTP/calculator results and usage, then verify revocation blocks a fresh run while prior history stays readable. Check removing missing/revoked selections in the inspector.
8. Confirm approvals are honestly marked unavailable, and inspect keyboard navigation, focus, contrast, dialogs and canvas at desktop/tablet/mobile widths.

See the [implementation plan](backend-implementation-plan.md) for current phase scope; historical increment results remain in the [development log](development-log.md).
