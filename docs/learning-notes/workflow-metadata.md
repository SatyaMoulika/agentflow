# Workflow metadata CRUD and archive — Phase 4A

Current contract: [Phase 4B workflow versions](workflow-versions.md) adds initial definitions, immutable expected-version saves and historical reads. This note records the earlier 4A increment and its verification.

Implemented on **2 November 2026**, after [logout/ownership](logout-ownership.md). Five Bearer-authenticated operations now create/list/get/update/archive owned metadata. There are 11 implemented operations across eight paths. No dependency/model/migration/private .env/frontend/dist/legacy-draft changes are needed; Alembic head stays 0002.

## Contract and staged scope

This increment deliberately starts a workflow as a **versionless draft**. POST accepts name/description, status is draft, and current_version_id is null. It does not manufacture an empty graph or claim that a definition has been saved/compiled. The target initial-version creation and expected-version save contract belongs to 4B. Registry/configuration and authoritative graph validation arrive in 4C/4D; real execution remains Phase 5 onward.

Metadata responses expose only id, owner_id, name, description, status, current_version_id and aware UTC timestamps. No ORM relationships, private version definitions or auth secrets are serialized. Existing saved-version pointers remain readable in metadata and survive edit/archive, even though the public saved-definition API is not implemented yet.

| Operation                              | Behavior                                                       |
| -------------------------------------- | -------------------------------------------------------------- |
| POST /api/v1/workflows                 | Create authenticated owner's draft; 201 and Location header    |
| GET /api/v1/workflows                  | Owned filtered/page-bounded metadata plus total/page/page_size |
| GET /api/v1/workflows/{workflow_id}    | Owned metadata, including archived rows                        |
| PATCH /api/v1/workflows/{workflow_id}  | Partial name/description update; archived is 409               |
| DELETE /api/v1/workflows/{workflow_id} | Archive only; empty 204, repeat is safe, history preserved     |

All require Authorization: Bearer from login/refresh. The cookie-operation Origin/client/CSRF headers are not required because these routes do not authenticate from cookies. In /docs, choose Authorize and paste the access JWT. Ownership always comes from the validated active user. A client cannot choose owner/status/current pointer or pass a graph in the metadata body.

## Input, pagination and response rules

Create requires a strict string name, trimmed to 1–200 characters. Description is a strict string, trimmed to at most 5000, default empty. PATCH permits either/both fields, requires at least one, preserves omitted values, rejects explicit null, and lets an empty description clear it. Empty/blank names, coerced numbers, unexpected fields and graph/privilege fields are rejected with safe 422/null details.

Patch uses None internally only to represent omitted fields; provided null fails the before-validator. The small JSON-schema helper removes the nullable/default branch so OpenAPI also permits omission without advertising null as accepted input. minProperties: 1 documents empty-object rejection. These rules are checked both as Python schemas and actual HTTP/OpenAPI contracts.

List query fields:

| Field     | Rule                                                                       |
| --------- | -------------------------------------------------------------------------- |
| page      | 1–1000000, default 1                                                       |
| page_size | 1–100, default 25                                                          |
| status    | Optional draft/active/paused/archived filter; no filter excludes archived  |
| q         | Optional trimmed literal case-insensitive name substring, 1–200 characters |

Unknown query fields, including owner_id, are forbidden. Page items and total use the same owner/status/search conditions. Ordering is updated_at DESC then UUID DESC for deterministic ties. A page beyond the last returns empty items with the filtered total. Status filters can read existing stored statuses but do not activate/pause workflows through this API.

q uses SQLAlchemy icontains(autoescape=True) with bound values. Percent, underscore and the escape character match literally rather than expanding a LIKE pattern; see [SQLAlchemy string operators](https://docs.sqlalchemy.org/en/20/core/sqlelement.html#sqlalchemy.sql.expression.ColumnOperators.icontains). This is a name substring search, not graph/full-text/regex search.

Count and page queries are two statements under default READ COMMITTED. They do not provide a frozen snapshot during concurrent inserts/updates; offset pages can shift. No cursor/snapshot guarantee or performance benchmark is claimed. Matching/sorting relies on the database's text behavior and configured indexes.

## Transactions, archive and concurrency

Create owns one unit of work: insert/flush, build public DTO, commit, then return 201/Location. Update and archive obtain an owner-scoped SELECT FOR UPDATE in the same transaction as the mutation. They never rely on a prior ownership dependency as permission to update a row by ID alone.

lock_owned flushes pending same-UoW work before a lock and uses populate_existing to refresh cached attributes after a wait. This shared helper is also used by existing append_version; its earlier preservation/rollback tests remain active. SQLAlchemy documents that [populate_existing refreshes cached ORM state](https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#populate-existing). Without that refresh, a cached draft could incorrectly permit editing a row another transaction had already archived.

```text
PATCH /workflows/{id}
  → validate JWT/current active user and body
  → worker: begin unit_of_work
      → owner-filtered row lock + refreshed metadata
      → missing/unowned: raise → rollback → generic 404
      → archived: raise → rollback → WORKFLOW_ARCHIVED 409
      → apply only provided fields → flush → construct public DTO
  → commit/close → 200 + no-store

DELETE /workflows/{id}
  → authenticate → owner-scoped row lock
  → set archived only if needed → commit
  → empty 204 + no-store
```

Partial updates preserve omitted fields. Concurrent edits to distinct fields both survive. Same-field requests serialize and the final write wins; this increment does not detect stale-client metadata overwrites. Saved-definition optimistic concurrency remains 4B.

If archive commits before an update gets its refreshed lock, that update returns 409 without changing metadata. If update commits first, archive preserves its metadata and then marks archived. Repeated archive does not update the row again. GET still returns owned archived metadata, while default listing hides it; status=archived retrieves it explicitly.

Archive is not physical deletion: the workflow row, current-version pointer and immutable history remain. The current API does not restore, activate or edit archived metadata. Future definition/status services must apply their own lifecycle rules inside the transaction; this is not an assertion that every trusted low-level repository operation is itself a complete business-policy boundary.

## Files and functions

Paths below are relative to backend/.

| File                                                | Responsibility and important calls                                                                                                                                                                                                                                                                                                                                                                                     |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| app/modules/workflows/schemas.py                    | WorkflowCreateRequest trims/bounds strict strings; WorkflowUpdateRequest distinguishes omission, rejects null/empty patch and emits accurate OpenAPI. WorkflowListParams validates bounded/filter-only query input. WorkflowResponse uses explicit ORM fields and UTC-aware timestamps. WorkflowPage defines items/total/page/page_size.                                                                               |
| app/modules/workflows/repository.py                 | lock_owned centralizes the owner-filtered row lock and cached-state refresh. page_owned shares filters for count/page and escapes literal name search. update_metadata changes only non-None supplied values and flushes; archive sets status only when needed. Neither commits. append_version now reuses the same lock while preserving prior semantics. Existing list_owned keeps its earlier lower-level contract. |
| app/modules/workflows/service.py                    | create/get/list/update/archive orchestrate Sessions/UoWs with owner IDs from the HTTP boundary. Mutation DTOs are built before commit; archived checks occur after refreshed locks. Storage/pool failures become plain WorkflowStorageUnavailableError.                                                                                                                                                                |
| app/modules/workflows/exceptions.py                 | Adds WorkflowArchivedError for a defined lifecycle conflict. Missing/storage/stale-version exceptions remain independent of HTTP/SQLAlchemy.                                                                                                                                                                                                                                                                           |
| app/api/workflow_dependencies.py                    | Registers WORKFLOW_ARCHIVED safe 409 in addition to existing generic missing/unowned 404 and safe storage 503. Earlier ownership dependencies remain available, but mutation services scope their own queries rather than relying on earlier reference snapshots.                                                                                                                                                      |
| app/api/v1/workflows.py                             | Mounts five synchronous metadata handlers, Bearer/current-user dependencies, typed query/body/output schemas, no-store, Location on create and explicit empty 204 archive. No graph execution, activation, restore or saved-definition handler is added.                                                                                                                                                               |
| app/api/router.py, app/main.py                      | Include the workflow router under /api/v1 and describe the implemented API scope.                                                                                                                                                                                                                                                                                                                                      |
| tests/unit/test_workflow_schemas.py                 | Strict bounds/trim/defaults, partial omission/clearing, null/empty/extra/privilege/graph rejection and list bounds.                                                                                                                                                                                                                                                                                                    |
| tests/api/test_workflow_contract.py                 | All-operation Bearer requirement; safe invalid body/path/query 422 without SQL; public fields, nonnullable partial-patch OpenAPI, security scheme and no-body archive contract.                                                                                                                                                                                                                                        |
| tests/integration/test_workflow_crud.py             | Real complete metadata journey, owner isolation, stable pagination/counts, literal search including wildcards/SQL-looking strings, preserved saved history, mutation rollback/storage recovery and invalid-response rollback.                                                                                                                                                                                          |
| tests/integration/test_workflow_crud_concurrency.py | Independent connections verify disjoint updates and both controlled update/archive orders with cached draft state, backend PIDs and bounded barriers/SQL deadlines.                                                                                                                                                                                                                                                    |
| Existing health/registration/logout API tests       | Production inventory becomes eight paths/11 operations; test-only routes remain absent, and earlier auth contracts remain active.                                                                                                                                                                                                                                                                                      |

## Observable API examples

After login/Authorize, create with:

```json
{ "name": "Invoice Processing", "description": "Metadata draft" }
```

HTTP 201 returns the public metadata with status draft/current_version_id null and Location /api/v1/workflows/{uuid}. GET that location retrieves it. PATCH with only `{ "name": "Invoice Review" }` preserves the description; `{ "description": "" }` clears it. DELETE returns 204 and keeps the row/history. GET /workflows hides it by default; GET /workflows?status=archived lists it. PATCH after archive returns 409.

| Outcome                                | Public response                                                |
| -------------------------------------- | -------------------------------------------------------------- |
| Invalid/missing access credential      | 401 UNAUTHENTICATED with Bearer challenge                      |
| Missing or not-owned row               | Same 404 NOT_FOUND envelope                                    |
| Edit archived metadata                 | 409 WORKFLOW_ARCHIVED                                          |
| Invalid schema/query/path/extra fields | 422 VALIDATION_ERROR, details null                             |
| Connection/pool failure                | Safe 503 SERVICE_UNAVAILABLE                                   |
| Unexpected insert/mapping failure      | Safe 500; mutation rolls back if transaction has not committed |

Every error includes request_id matching X-Request-ID. Success metadata/list/archive responses are no-store. No raw SQL/driver/input details are returned. Definitions are excluded even when the stored workflow already points to a saved snapshot.

## Actual verification

On 2 November 2026, full checks passed **347 tests** against real PostgreSQL; ordinary checks passed **215, skipped 132** marked integration cases. Ruff lint/format passed 85 Python files; Pyright reported zero errors/warnings; locked offline sync passed. This adds 40 ordinary and 18 integration cases. Earlier migration/auth/ownership/version repository tests remain green. A timestamp comparison was made robust by parsing UTC timestamps; its journey test was rerun successfully.

Real API tests prove owner-only create/list/get/patch/archive, same missing/unowned 404s, correct empty-page totals, UUID ordering ties, literal percent/underscore/slash/quote search, no fabricated saved version on create, preserved current pointer/history on edit/archive, no graph leakage, idempotent archive, archived edit 409 and rollback/retry after flushed create/update/archive failures. An invalid public timestamp after INSERT rolls back before success/Location is returned.

Concurrent service checks use distinct PostgreSQL connections. Two partial updates preserve disjoint fields. Controlled archive/update orders cache draft objects before the first commit, then verify refreshed lifecycle checks reject a post-archive update or preserve a pre-archive edit. No stale-client metadata precondition or lock-timeout retry policy is inferred from those tests.

A temporary real Uvicorn smoke used actual register/login and workflow routes: draft create 201, owned get/patch 200, stranger 404/empty list, archive 204, explicit archived filter, restart persistence and archived patch 409. It checked 11 operations/eight paths, no test routes, private values absent from logs, request/log correlation and graceful shutdown. Only Database was mapped to a disposable migrated schema with a process-local key. A temporary script initially reused its schema variable for OpenAPI, so cleanup failed after application checks; the uniquely identified test schema was removed and the corrected smoke rerun with successful cleanup. No development accounts/configuration or browser UI were involved.

## Limits and next increment

This is metadata CRUD, not a complete workflow builder/executor backend. Saved graph read/write/version APIs, initial definitions, expected-version saves, activation/restore, registry/config schemas and authoritative graph compilation are still pending. Metadata edits have no client revision/ETag precondition. List count/pages are not a concurrent snapshot. No frontend wiring, worker/provider call, performance benchmark, production query deadlines or browser visual acceptance is claimed.

No new migration is needed: these operations use existing 0001 workflow columns and preserve 0002 auth tables. No private .env, dependency lock, frontend assets or legacy SQLite drafts were edited. Test schemas/server/container are cleaned up and development PostgreSQL left running.

Next: **Phase 4B — immutable saved-definition APIs and optimistic concurrency**, including initial saved versions and historical reads. Registry/configuration and graph compilation follow in 4C/4D.

## Independent exercise

Using isolated two-user API fixtures, create and archive a workflow for each owner. Verify each user's status=archived listing and total includes only their own workflow. Do not use development data; leave the solution for your attempt.

## Review questions

Discuss these one at a time:

1. Why does archive preserve the workflow row and its immutable versions instead of deleting them?
2. Why must the row be refreshed after acquiring its lock before checking archived status?
3. Why does PATCH distinguish omitted fields from an explicit null or empty string?
4. Why must the total-count query use the same owner/search/status filters as the page query?
5. What does row locking protect here, and what stale-client overwrite problem remains for future versioned saves?
