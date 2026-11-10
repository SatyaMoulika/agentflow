# Phase 4B — immutable workflow draft versions

Newer increment: [Phase 4C node registry](node-registry.md) adds strict configuration contracts and discovery. This note retains the Phase 4B contract/verification; draft saves still permit incomplete configs.

Verified 2 November 2026. This increment extends the five workflow operations from [Phase 4A](workflow-metadata.md). Initial definitions, expected-version saves and historical reads now work. Graph semantics, node configuration, activation and execution are still future increments. A saved draft is not an executable workflow.

## Contract and request flow

An immutable snapshot lets a later run refer to an exact saved definition without an editor changing it underneath the run. A workflow row holds mutable metadata and its current-version pointer. Each definition save inserts a new workflow_versions row; it never updates a prior snapshot.

All operations use an active-user Bearer JWT. The service derives owner_id from that identity and repeats the owner filter inside its transaction. No new dependency, environment setting, table or migration is needed; revision stays 0002. Private backend/.env and frontend/mock/dist files were not changed.

| Operation                                           | Current behavior                                                                                                                                                                             |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| POST /api/v1/workflows                              | Name/optional description; optional definition creates version 1 atomically with metadata/pointer. Without definition, create a versionless draft. Returns 201 and Location.                 |
| PATCH /api/v1/workflows/{workflow_id}               | Metadata edits and/or a new definition. A definition requires expected_version; that field requires a definition. Metadata, snapshot and pointer commit together.                            |
| GET /api/v1/workflows/{workflow_id}                 | Metadata and the snapshot referenced by the current pointer.                                                                                                                                 |
| GET /api/v1/workflows/{workflow_id}?version_id=UUID | Metadata and the specified snapshot, provided it belongs to this owned workflow. Metadata and current-version fields still describe the workflow as read, not the old metadata at save time. |
| GET /api/v1/workflows                               | Existing bounded metadata pagination/search. List items contain no definition or version payload.                                                                                            |
| DELETE /api/v1/workflows/{workflow_id}              | Existing non-destructive archive. Archived workflows/history remain readable; edits/saves return 409 WORKFLOW_ARCHIVED.                                                                      |

POST, item GET and PATCH return WorkflowDetailResponse: the eight existing metadata fields plus current_version_number and version. The number is 0 and version is null for a versionless draft. A snapshot contains id, workflow_id, version_number, definition, created_by and UTC created_at. The public field is definition, not the ORM's definition_json. The selected version may differ from current_version_id during a historical read; current_version_number is always the number belonging to that current pointer. Historical reads do not rewind anything. There is no history-list endpoint yet; retain snapshot UUIDs from successful saves.

Create an initial version:

```json
{
  "name": "Invoice draft",
  "definition": {
    "schema_version": "1.0",
    "nodes": [],
    "edges": [],
    "EditorState": { "zoomLevel": 1 }
  }
}
```

Then save again with the current version number returned by the server:

```json
{
  "name": "Revised invoice draft",
  "expected_version": 1,
  "definition": {
    "schema_version": "1.0",
    "nodes": [{ "id": "start", "type": "manual", "config": {} }],
    "edges": []
  }
}
```

Use expected_version 0 for the first definition on an existing versionless workflow. It must be a strict integer from 0 to 2147483647; booleans, strings, floats and null are rejected. An omitted field and explicit null are different: optional create definition can be omitted but cannot be null. PATCH still rejects an empty body and null metadata, preserves omitted metadata and permits an empty description to clear it. Owner/status/pointer fields remain forbidden.

A valid stale request returns safe 409 WORKFLOW_VERSION_CONFLICT with “The workflow version changed. Reload before saving.” Its metadata edits also roll back. The client should retain its unsaved draft, reload and explicitly resolve changes; blind retries are not a merge. Metadata-only PATCH has no version precondition and retains the existing serialized last-write behavior. Every successful definition save appends, even for identical JSON; no content deduplication or idempotent replay is claimed. A lost save response can therefore require reconciliation.

## Bounded definition envelope

WorkflowDefinition requires schema_version exactly "1.0", nodes and edges arrays of JSON objects. It allows at most 500 nodes and 2000 edges. Top-level extension keys and nested business keys/values are preserved verbatim, including their case; no adapter renames CustomerID or guesses number types.

Before typed validation, an iterative walk requires native JSON values, string keys, finite numbers and nesting no deeper than 32 levels (root at depth 0, including leaves). The compact serialization using ensure_ascii=False and comma/colon separators must encode to at most 262144 UTF-8 bytes, including envelope/extension keys. Invalid Unicode, non-JSON values and unsupported schema versions are rejected with the existing sanitized 422 envelope. These are definition storage limits after body parsing, not a transport-level request body/rate limit. OpenAPI declares array limits, non-null optional fields and the paired PATCH requirement; custom byte/depth/finite checks are enforced by validators and documented here.

Empty/incomplete node configurations and arbitrary node types can be saved as draft candidates. Duplicate IDs, edge endpoints, cycles, mappings, permissions and executable node schemas are not checked by this increment. No compiler/activation/execution path is exposed. Arbitrary business JSON can itself be sensitive; the API does not detect/redact every possible secret inside a definition. Do not store credentials there. Logs continue to omit request bodies and snapshots.

## Files and functions

- app/modules/workflows/schemas.py adds WorkflowDefinition.bounded_json, optional create definition and paired PATCH definition/expected_version validation. WorkflowVersionResponse maps the stored JSON field to the public name. WorkflowDetailResponse separates current-pointer information from the selected immutable snapshot. _non_null_patch_schema keeps omitted optional fields distinct from forbidden null in OpenAPI; dependentRequired describes the save pair.
- app/modules/workflows/service.py extends create to append version 1 inside its unit of work. update locks and checks ownership/archive state, applies metadata and uses the existing append_version operation in that same transaction. get accepts an optional historical UUID. _detail builds detached public DTOs before the mutation commits, reads snapshots using both owner and workflow membership, and pins the current snapshot to the pointer already read. A concurrent later save can make the response older than the newest commit, but does not mix a new snapshot with the old pointer.
- app/modules/workflows/repository.py already implements append_version and get_version_owned; no repository/schema change was needed. The append operation reacquires the same transaction's owner-scoped lock, refreshes cached state, compares the current number, allocates from maximum saved history, deep-copies JSON, inserts, advances the pointer and expires cached navigation/timestamps. The repository never commits.
- app/api/v1/workflows.py exposes the extended requests/detail responses and version_id query. Existing route count remains 11 operations across eight paths for the whole API. app/api/workflow_dependencies.py maps WorkflowVersionConflictError to a static 409. app/main.py updates the API description.
- tests/unit/test_workflow_schemas.py checks envelope boundaries, JSON preservation and paired integer requirements. tests/api/test_workflow_contract.py checks safe HTTP validation/OpenAPI. tests/integration/test_workflow_crud.py verifies real HTTP persistence, immutable history, ownership, rollback, independent-connection saves and a read interleaved with a committing writer. test_workflow_crud_concurrency.py extends cached-state archive races to definition saves. Earlier low-level trigger/constraint/version tests remain active.

For a save, the flow is: Bearer/current-user check → strict request validation → unit of work → owner-scoped row lock and refreshed lifecycle check → metadata changes → expected-number check → snapshot INSERT → pointer update → detail DTO construction → commit → HTTP response. An exception escaping the unit of work rolls back all flushed changes. No provider/network call runs inside this transaction.

SELECT FOR UPDATE makes a competing writer wait; after the winner commits the losing writer sees the updated row. SQLAlchemy's populate_existing refreshes a previously cached object. The test barrier is entered once per Session because update and append_version both take that same lock. Reentering the lock within one transaction does not release it. The database trigger independently rejects snapshot UPDATE/DELETE/TRUNCATE. See [PostgreSQL row locking](https://www.postgresql.org/docs/16/explicit-locking.html), [SQLAlchemy populate_existing](https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#populate-existing), and [Pydantic model configuration](https://docs.pydantic.dev/latest/concepts/models/#extra-data).

## Actual verification

Full backend checker: **390 passed** against real isolated PostgreSQL. Ordinary checker: **247 passed, 143 skipped**. This adds 32 ordinary and 11 integration cases. Ruff lint/format passes 85 Python files; Pyright reports zero errors/warnings; locked offline synchronization passes. The focused workflow run passed 101 tests. No frontend test/build result is implied.

The tests prove initial/versionless saves, business-key preservation, old snapshots after later saves/archive, identical missing/unowned/mismatched 404s, unchanged rows/pointer/history after a stale combined save, rollback/recovery after flushed version/pointer storage failure, rollback on invalid response DTO, and current-read coherence during a separate committed save. Real concurrent HTTP saves with distinct backend PIDs yield one 200 and one 409 both from version 0 and version 1. Both archive-first and save-first orders use cached draft state and preserve lifecycle/history policy. The pre-existing immutable-trigger and migration drift/round-trip tests remain green.

A live Uvicorn smoke with real registration/login verified initial save, version 2, stale 409, owner denial, historical UUID reads, restart persistence of current/history, archive refusal, metadata-only listing, OpenAPI inventory, private-value omission from logs, response/log request IDs and graceful shutdown. Only the shared Database resource was mapped to a disposable migrated test schema; the signing key was process-local. The first smoke harness incorrectly required exit code 0 after SIGTERM; installed Uvicorn re-raises that signal after graceful cleanup. The harness now accepts the signal exit while checking shutdown logs, and uses an independent finally block for schema cleanup. The uniquely verified owned leftover schema was removed and the corrected smoke passed. No production application fix or test weakening was involved.

Temporary test schemas/server/factory/container were removed; cleanup found zero random schemas and zero public test tables. Development PostgreSQL remains running, with no development data/configuration/migration changes.

## Limits and next increment

Phase 4C adds the node registry and typed configuration contracts. Phase 4D then performs authoritative graph validation/compilation; Phase 5 begins execution. Groq integration remains its later provider phase, with a configured Free Plan model and no paid fallback. This increment does not call Groq or require its key. Production query deadlines, transport/rate limits, history pagination, frontend API adapters and browser integration remain pending.

Exercise, without a supplied solution: using isolated API fixtures, save a workflow twice, archive it, read the first version by UUID, then attempt a save with the archived workflow's current number. Assert that metadata, both snapshots and current pointer remain unchanged after rejection. Do not use development data.

Review questions (discuss one at a time):

1. Why must a stale save roll back its metadata changes as well as its version insertion?
2. In a historical response, how do version.id and current_version_id differ?
3. Why can a successfully saved draft still be unsuitable for execution?
4. Why does a row lock alone fail to detect that an editor started from an old saved version?
