# Logout and ownership dependencies — Phase 3D

Implemented on **2 November 2026**. This closes the planned authentication increment for the current entities: current-family logout plus reusable authenticated workflow/version ownership checks. It builds on [refresh sessions](refresh-sessions.md), adds no dependency or migration, and leaves revision 0002 unchanged. Workflow CRUD remains Phase 4A; these checks do not claim authorization for runs/connections/approvals that do not yet exist.

Phase 4A now adds [public workflow metadata CRUD/archive](workflow-metadata.md). The notes below record the 3D increment; workflow routes are no longer limited to private probes.

## Contract decided before implementation

The previously proposed addition, **POST /api/v1/auth/logout**, revokes the family represented by a refresh cookie. It clears the matching browser cookie pair only after a successful transaction, with 204 and no body. Repeated requests are safe. This is one additional endpoint beyond the original 25-route baseline, not an undocumented logout-all operation.

Logout uses the existing exact Origin and X-AgentFlow-Client: web requirement. A well-formed refresh cookie also requires the matching CSRF cookie/header and its stored binding. It does not require an access JWT or signing key: an expired access token should not prevent revoking a refresh family. JSON/query owner IDs, all_sessions flags and Bearer values do not identify the family.

No usable refresh cookie means there is no server family to identify: absent/malformed credentials return 204 and clear browser cookies without database work. A well-formed unknown token returns 204 after lookup with syntactically matching proof. Known expired, inactive, deleted or revoked state is also a successful logout outcome. Wrong Origin/client/CSRF proof remains 403 without clearing/revoking. Storage failure returns safe 503 without falsely reporting success or discarding retry credentials. Unexpected transaction failure remains a safe 500.

Clearing cookies alone is not server revocation; this design persists the family state. It follows the separation described in [OWASP session management guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html). Existing access JWTs still use their own expiry and current-account checks: this increment adds no access-token denylist. Clients must drop their in-memory access token on sign-out. Other login families remain usable.

Ownership means every resource query is scoped to an authenticated active user. The UUID comes from the validated JWT subject and current-account lookup, never from a caller's owner_id field. Missing and not-owned resources intentionally have the same safe 404, avoiding an existence disclosure. Permission checks need to remain part of each request and operation; see [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).

## Logout transaction and races

```text
POST /api/v1/auth/logout
  → Origin/client check
  → absent/malformed cookie: no database needed → clear pair → 204
  → present cookie: validate CSRF cookie/header syntax/equality
      → require configured database resource
      → unit_of_work:
          locate digest → lock family → reread token after waiting
          unknown: finish without mutation
          known: compare stored CSRF binding → mark family revoked → flush
      → normal context exit COMMIT
      → clear both cookies → no-store/no-cache → empty 204
```

A consumed ancestor still identifies its family. Logout therefore revokes descendants even if another request already rotated the browser token. Logout and refresh take the same family row lock. If logout gets it first, refresh rejects; if refresh gets it first, its replacement is subsequently unusable after logout commits. This also holds when logout presents an ancestor and refresh presents the current token.

RefreshRepository.lock_token centralizes locate/lock/reread so both operations refresh cached token state after waiting. revoke_session preserves the first revoked_at timestamp and flushes without committing; the service still owns the transaction. A failure after that flush rolls back. The endpoint must not clear cookies until the service returns normally.

This is database atomicity, not atomic delivery of an HTTP response. After a committed logout, retry is safe even if the original response was lost. Existing strict refresh response-loss/replay rules remain unchanged.

## Ownership dependencies and boundaries

get_owned_workflow and get_owned_workflow_version both resolve get_current_user, which verifies the access token and requires a current active account. A synchronous service opens its own read Session and uses existing owner-scoped repository queries. Version lookup requires version ID, containing workflow ID, and workflow owner together. A version from another workflow is never accepted merely because both workflows belong to the caller.

Results are frozen identifier references (workflow_id, owner_id, and version_id where applicable), not ORM objects, live Sessions, workflow definitions or persistent permission tokens. They can cross worker boundaries safely. Database work runs in worker threads; the shared engine owner can be reused but its Sessions cannot.

**Future writes must still scope their own SQL queries by the authenticated owner inside their transaction.** A successful earlier dependency check does not eliminate race conditions or authorize a later unscoped update. Phase 4 services must use the owner-filtered repository methods, expected-version checks and transaction boundaries already established. No public workflow API is mounted by this increment.

## Files and functions

Paths below are relative to backend/.

| File                                         | Change and important calls                                                                                                                                                                                                                                                                                                                                                                       |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| app/modules/auth/refresh_repository.py       | lock_token finds the hash, locks its family and rereads with refreshed ORM state. revoke_session retains the first timestamp and flushes; neither commits. Existing refresh now uses these shared operations too.                                                                                                                                                                                |
| app/modules/auth/service.py                  | logout opens unit_of_work, safely ignores unknown credentials, verifies the stored CSRF digest and revokes the known family before normal commit. Storage errors become the existing safe module outcome. refresh reuses shared locking/revocation without changing replay behavior.                                                                                                             |
| app/api/dependencies.py                      | get_database_resource is now the single optional engine-owner injection point. get_database requires it for data operations. _read_cookie_credentials shares parsing/proof checks; get_logout_credentials allows no usable cookie, while refresh remains strict. get_logout_database requires storage only for a present credential. Existing Origin/current-user/access checks remain in force. |
| app/api/v1/auth.py                           | logout_session delegates to the service, creates an explicit empty 204 Response, sets no-store/no-cache, and clears cookies after commit. Declares its Origin/client/CSRF contract, no body/Bearer requirement and 403/503 outcomes. Existing cookie helper provides identical deletion flags.                                                                                                   |
| app/modules/workflows/access.py              | WorkflowAccessService.require_workflow/require_version open read Sessions and use scoped repository queries. OwnedWorkflow/OwnedWorkflowVersion are frozen identifier references. Missing/not-owned raises the existing plain WorkflowNotFoundError; operational/pool failures become WorkflowStorageUnavailableError.                                                                           |
| app/modules/workflows/exceptions.py          | Adds the storage-unavailable outcome, independent of HTTP/SQLAlchemy. Existing missing/stale outcomes remain unchanged.                                                                                                                                                                                                                                                                          |
| app/api/workflow_dependencies.py             | Resolves the active UserResponse, derives owner_id, calls the access service and returns references. Registers static generic 404/503 module handlers. No router or CRUD route is added.                                                                                                                                                                                                         |
| app/main.py                                  | Installs the ownership module error handlers during factory construction.                                                                                                                                                                                                                                                                                                                        |
| tests/api/test_logout_contract.py            | No-cookie/malformed idempotence without key/DB, truly empty 204, flags/no-store, CSRF rejection without cookie deletion, safe missing-storage error and six-route OpenAPI contract.                                                                                                                                                                                                              |
| tests/api/test_refresh_contract.py           | Extends existing Origin/client rejection cases to logout.                                                                                                                                                                                                                                                                                                                                        |
| tests/integration/test_logout.py             | Real credential family revocation, preserved first timestamp, stale ancestor, independent-family isolation, server-bound proof, unusable/unknown state, failure rollback/retry, private logs and signing-key/access-token independence. Confirms existing JWT behavior explicitly.                                                                                                               |
| tests/integration/test_logout_concurrency.py | Separate PostgreSQL connections race logout with rotation using current or consumed-ancestor credentials. Bounded barriers/query deadlines; no usable descendant survives the completed logout.                                                                                                                                                                                                  |
| tests/integration/test_workflow_ownership.py | Test-only HTTP probes use the production dependencies, authentication, service and scoped SQL. Two users, spoofed owner query, missing/unowned/mismatched versions, auth-first checks, worker execution and storage recovery.                                                                                                                                                                    |
| Existing health/registration tests           | Exact production inventory now has six routes, without workflow/probe routes.                                                                                                                                                                                                                                                                                                                    |
| Existing API/integration database overrides  | Bind get_database_resource rather than the old required-resource function, so ordinary data operations and optional-resource logout use the same isolated database.                                                                                                                                                                                                                              |

No model/configuration/migration/manifest/lock, private .env, frontend/dist or legacy-draft changes were needed. Documentation/status/API inventory were updated with this implemented addition and next increment.

## Injection issue found by tests

The first optional logout database helper called get_database directly. That bypassed FastAPI's resource override, so the isolated HTTP harness saw no database while other auth routes used the fixture. The fix introduces one optional get_database_resource dependency underneath both required data access and optional logout. Tests now substitute only that shared resource, keeping all route/service/transaction/SQL code real. The production lifespan still owns app.state.database; no test-only switch or application override inspection was added.

The ordinary no-database check also exercises a synchronous successful logout handler. This environment's sandbox prevented its worker-thread wakeup, so the owned stalled run was stopped and the checks rerun with permitted worker/socket access. No production threading behavior or test assertion was weakened. A normal local terminal still uses the same commands in the [backend guide](../../backend/README.md).

## API usage

After login or refresh, call /api/v1/auth/logout using its cookie jar, current CSRF proof, allowed Origin and X-AgentFlow-Client: web. In /docs, use the two header fields; the browser supplies Origin/cookies. No request body or Authorization header is required. HTTP 204 has no JSON body to parse.

Default secure names and explicit local HTTP names are unchanged from Phase 3C. Successful deletion uses the matching Path=/, Secure/HttpOnly choices and SameSite=Strict. Absent/malformed credentials need no DB/key. A present well-formed cookie still needs matching proof and database availability; the endpoint cannot claim durable revocation when storage is unavailable. No all-sessions or arbitrary-family selector exists.

Workflow access helpers are preparation for Phase 4. They are verified through routes declared only in the test module under /_test/workflows. These paths never appear in a fresh production create_app OpenAPI inventory. A production API client still cannot create/get workflows over HTTP until the next increment implements that contract.

## Actual verification

On 2 November 2026, the full checker passed **289 tests** with real PostgreSQL. Ordinary checks passed **175**, skipped **114** marked integration cases. Ruff lint/format passed 78 Python files; Pyright reported zero errors/warnings; locked offline synchronization passed. This adds 11 ordinary and 25 PostgreSQL cases. Existing migration/refresh/JWT/repository checks remain green; revision stays 0002.

Logout cases prove committed state from a fresh Session, no-body/cookie deletion, repeat behavior, ancestor/other-family isolation, CSRF preservation, missing/invalid/inactive/revoked/expired/deleted credentials, rollback after a flushed revocation, storage recovery, secret-safe logs, and no access-key dependency. Two concurrency scenarios record distinct PostgreSQL backend PIDs and assert the family is revoked and any replacement is rejected after both requests finish.

Ownership probes prove each user can access only their workflow/version, caller owner IDs cannot override authentication, missing and unowned resources have identical 404 error objects, mismatched versions fail, missing/invalid/inactive credentials prevent ownership lookup, and storage errors recover safely. A worker-thread observation checks owner propagation. No real frontend or public workflow endpoint is claimed.

A temporary real Uvicorn smoke logged in, rotated, rejected a missing-marker logout, logged out through a consumed ancestor with 204/cookie deletion, stopped the server, restarted and rejected the descendant refresh. Empty logout returned 204 and the existing access JWT retained its documented validity. Six production paths, absence of test/workflow routes, private-value omission, matching request/log IDs and graceful shutdown passed. It used only a random migrated test schema and process-local key, with explicit local HTTP mode. Temporary server/schema/container were cleaned up; development PostgreSQL remained running and its data/configuration were untouched.

## Limits and next increment

Current-family logout does not log out every device/family or denylist issued JWTs. An old active-account access token may work until expiry; clients must discard it. No logout-all, password-reset revocation, session management UI, rate limits, retention job, production lock deadlines, browser UI/CORS/frontend integration or new resource authorization is implied.

Ownership references are snapshots and cannot substitute for owner-scoped mutation SQL. Workflow state/status/graph validity is not authorization; owner identity does not grant permission to arbitrary external tools. Runs/connections/approvals will need their own scopes when those tables/services arrive. No schema/dependency change is needed now.

Next: **Phase 4A — workflow CRUD/archive**, with explicit public DTOs, owner-scoped services, safe archive/history behavior and HTTP checks. Saved-definition API concurrency, node registry/configuration and graph compilation follow separately.

## Independent exercise

Using isolated fixtures, let user B append a version to B's workflow. Verify user A still receives the same 404 for B's workflow and new version while B can access both. Do not use development data; leave the solution for your attempt.

## Review questions

Discuss these one at a time:

1. Why must a future workflow write keep its owner filter inside the transaction after the ownership dependency has succeeded?
2. Why must logout revoke server state before deleting the browser cookie pair?
3. Why can logout work without a valid access JWT, while still requiring bound CSRF proof?
4. Why must missing and unowned workflows return the same public error?
5. What prevents a refresh racing logout from leaving a usable descendant?
