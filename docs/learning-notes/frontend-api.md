# Frontend API integration

Subsequent Phase 5D now adds keyed run commands, bounded attempts and real cancel/retry actions, with migration 0004. See [execution command notes](execution-commands.md) for current behavior; the original integration results below are historical.

Implemented 4 November 2026. Initial authentication/workflow/run integration from Phase 11 is brought forward after backend Phase 5C. Backend 5D remains next. No migration: head stays 0003. The API has 16 operations across 13 paths, including owned GET /api/v1/runs.

## Files and responsibilities

| File                                      | Responsibility                                                                                     |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| src/App.tsx                               | API routes, session guard, Query provider and account-scoped cache                                 |
| src/api/client.ts                         | Relative requests, safe errors, memory token, cookie proof, auth serialization and account fencing |
| src/api/session.ts and types.ts           | Observable session, cache scope and explicit snake_case DTOs                                       |
| src/api/AuthPage.tsx and Shell.tsx        | Real registration/login/logout and current-user navigation                                         |
| src/api/Editor.tsx, Canvas.tsx, graph.ts  | Catalog editing, JSON parsing, dirty state, saves/conflicts, validation and runs                   |
| src/api/pages.tsx and common.tsx          | Owned lists, actual totals/results, profile, loading/errors and unavailable features               |
| backend/app/modules/executions/service.py | Owner-filtered paginated run summaries                                                             |
| vite.config.ts                            | Same-origin development/preview proxy preserving browser Origin                                    |

Old prototype modules remain unrouted reference code. No local auth flag or seeded business data is read. Only appearance persists locally.

## Request and session flow

Registration creates a user without issuing a session. Login sends the exact password, browser Origin and fixed X-AgentFlow-Client: web marker. The marker is a client identifier, not a secret. Login sets HttpOnly refresh and readable CSRF cookies. The client checks the accepted proof cookie before reporting success.

ApiClient.initialize restores from cookies. Access tokens remain in memory. Refresh is single-flight in one client; Web Locks serialize login/refresh/logout across tabs. Proof is read after lock acquisition, so a waiting tab uses the rotated cookie. Without Web Locks automatic refresh/restoration is refused; sign in again. Browser secure contexts are needed (localhost or HTTPS).

Protected requests retry once after 401 using a refreshed token. Network/storage failures never trigger mutation replay. Session generation fences stale responses and blocks replay under a different account. Query keys include account/generation. BroadcastChannel sends nonsecret session-change notices only. This does not recover lost committed rotation responses; strict replay detection can require signing in again.

Logout clears identity only after server 204; a 503 preserves the session for explicit retry. Issued access JWTs retain their backend expiry. No credentials enter localStorage. These mechanisms do not protect against XSS.

## Save, validate and execute

The editor fetches an owned workflow and server catalog. Save commits an immutable version with expected_version. A 409 retains the draft and offers download or explicit load-latest. Refetches do not silently overwrite edits. Dirty navigation is guarded. Explicit version URLs and archived workflows are read-only.

Definitions preserve schema_version, source_handle, typed config, input mappings and arbitrary business key casing. Finite object JSON is bounded before sending. Backend validation remains authoritative for config/topology/references. Invalid semantic drafts may be saved and then validated; no expression evaluation is performed.

Run sends a saved version UUID and manual input only when edits are saved. Results use the frozen graph and actual attempts, skipped nodes and null outputs. No invented logs, traces, tokens or model usage. A retained-run Location on storage failure links to inspection. A network failure may follow commit; inspect history before another submission.

## Run listing

GET /api/v1/runs requires active-user Bearer authentication and returns no-store summaries. Query: page 1–1,000,000; page_size 1–100 (default 25); optional legal status and workflow_id UUID. Unknown fields are rejected. Ordering is created_at DESC, id DESC. Filters/counts are owner-scoped; archived workflows retain history. Rows contain current workflow name, frozen version number, identity/status/error/timestamps, without inputs/outputs/graph/attempts. Owner-scoped detail GET supplies those. Separate READ COMMITTED count/page queries can shift under concurrent writes.

## Configuration and verification

Follow the [walkthrough](../real-backend-walkthrough.md). Browser URLs are relative /api/v1; Vite preserves Origin through its proxy. Same-origin requests need no cross-origin CORS permission, but the backend must allow the frontend Origin. Local HTTP explicitly uses development cookies. Deployment needs HTTPS/Secure cookies, an exact allowed origin, same-origin API routing and client-route fallback. Private .env was not read or changed.

114 frontend tests pass: 71 retained prototype tests plus 43 client/graph/rendering tests. Cases cover cookies, memory authentication, refresh locking/account changes, uncertain writes, logout failure, bounded JSON/casing, empty states, actual values and read-only snapshots. Lint, TypeScript and production build pass.

Backend checks pass 858 tests with PostgreSQL; ordinary mode passes 607/skips 251. Ruff checks 119 files; Pyright reports zero errors/warnings. Listing tests cover ownership, bounds, payload omission, archive history and SQL failure/recovery. Real HTTP checks used the compiled frontend client through Vite preview and temporary Uvicorn against a disposable migrated schema: registration/login, empty account, save/409, validation, opposite branch results/skips, listing, restored/serialized refresh, logout, second-account isolation and identical history after API restart. Built assets omit prototype workspace markers. Correlated logs, privacy and shutdown are checked.

Browser E2E and visual QA remain outstanding: the browser access host was unavailable. Cookie enforcement, canvas interaction, responsive layout and navigation need real-browser review. Groq/tools/approvals/workers/live events/retry/cancel/idempotency remain unavailable.

## Exercise and review

Exercise: edit one workflow in two tabs, save the first, then save the stale second draft. Explain the conflict and manually reconcile without automatic retry.

1. Why read proof inside the Web Lock?
2. Why block replay when refresh identifies another account?
3. What does a retained run Location establish, and what remains ambiguous after network failure?
4. Why can totals/pages shift despite deterministic ordering?
5. Which claims need browser verification beyond HTTP checks?

## Cookie-mode coexistence fix — 4 November 2026

A successful backend login can coexist with a client cookie error if old Secure and current development cookie names are both present. The earlier client chose the first readable CSRF cookie, which could be stale. It now matches the login/refresh response proof to a readable cookie and remembers that cookie name. Refresh/logout read the current value of that name inside the auth lock, preserving rotation. Bootstrap refuses to guess between conflicting modes and asks for login; conflicting same-name values remain rejected. Missing/mismatched proof still cannot authenticate the UI.

Six regression cases cover both active modes in both cookie orders, safe mixed-mode bootstrap and rejection of conflicting same-name values. All 114 frontend tests, lint, TypeScript and production build pass. Backend code/configuration are unchanged. The reported browser cause still needs confirmation by retry or cookie attributes; HTTP 200 alone cannot establish cookie acceptance. See the walkthrough's cookie troubleshooting steps.
