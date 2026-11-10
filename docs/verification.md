# Verification

## Current baseline — 10 November 2026

The active application is `src/api/` with `src/App.tsx`, backed by `backend/app/`. Older frontend simulator tests remain useful reference coverage; they do not establish implemented backend agents or approvals.

The latest full run passed **1,301 backend tests** with isolated PostgreSQL/Redis, Ruff lint/format (205 Python files) and Pyright with zero errors/warnings. Ordinary backend checks skip opt-in PostgreSQL/Redis integration cases; the full run used both integration flags. Frontend checks passed **135 tests across 11 files**, ESLint, TypeScript and the production build.

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
7. Confirm approvals are honestly marked unavailable, and inspect keyboard navigation, focus, contrast, dialogs and canvas at desktop/tablet/mobile widths.

See the [implementation plan](backend-implementation-plan.md) for current phase scope; historical increment results remain in the [development log](development-log.md).
