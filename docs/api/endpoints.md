# Proposed API inventory and contract alignment

Gmail connection setup adds owner-authenticated `POST /gmail/authorize`, `POST /gmail/complete`, `GET /gmail/connections`, `GET /gmail/connections/{connection_id}/messages` and `DELETE /gmail/connections/{connection_id}`. The callback consumes owner-bound state once; connection responses exclude credentials. The message list returns up to ten inbox IDs; a manual workflow node reads selected plain text. Automatic triggers and actions are not yet available. See [Gmail setup](../learning-notes/gmail-connection.md). The current API has 36 operations on 31 paths; source migration head is 0014.

Phase 8C adds `POST /runs/{run_id}/agent-resume` for an owned run, accepting the current `node_run_id` and `checkpoint_id` from run details. It consumes only an explicitly paused post-tool checkpoint; stale or concurrent requests return 409. Run details expose invocation checkpoint status and continuation count, and events record checkpointing and continuation. See [checkpoint setup and limits](../learning-notes/agent-checkpoints.md).

Provider/generation continuation (head **0010**): generate/edit requests accept up
to ten unique `connection_ids`. Server-authorized catalog metadata and provider-call
metadata return with review-only proposals. Completion responses add `metadata`;
run attempts add optional `provider` derived from immutable status events, while
business outputs stay unchanged. Explicit provider failures and safe `Retry-After`
guidance distinguish upstream authentication from AgentFlow authentication. See
[the current contract](../learning-notes/provider-integration-hardening.md).

Phase 7E implements all four `/connections` operations below: authenticated
create/list/get/revoke, metadata-only responses, write-only optional bearer/API-key
credentials and encrypted storage. The `http` node config is only
`{"connection_id":"<uuid>"}` and authorizes a fixed public HTTPS GET endpoint at
execution time. No automatic retry/recovery or full-workflow retry is offered for
HTTP graphs. At that phase, head was 0009 and the API had 27 operations on 22 paths. See
[connection contracts and limits](../learning-notes/secure-http-connections.md).

Phase 6D extends owned run details with nullable `next_retry_at`, `retry_node_id`
and `next_retry_attempt`, plus per-attempt `retry` metadata (`scheduled_at`, `due_at`,
`resumed_at`, `cancelled_at`). A run remains running while waiting; cancellation is
available. Transient background retries now use the run's persisted exponential
delay. Request bodies, command keys and 201/202 delivery rules are unchanged. See
[scheduled retries](../learning-notes/scheduled-retries.md).

Current Phase 6C contract: opt-in pure workflow create/retry commands return 202 and
commit a durable workflow intent without contacting Redis. Groq graphs and default
mode remain synchronous (201). Run detail/list DTOs include `execution_mode`;
idempotent replay preserves the original mode. Ownership is checked both by the API
and through persisted delivery provenance at the worker. See [background execution](../learning-notes/background-execution.md).
The phase-specific sections below retain their historical contracts.

Phase 0 target inventory, updated through Phase 5D (4 November 2026). **Auth/health/logout, node contracts, workflow CRUD/immutable history, read-only validation/compiler and synchronous six-type pure-node execution with exclusive routing and run creation/history are implemented**; the other routes remain proposals. The additional authenticated `POST /api/v1/ai/completions` sends an explicit prompt to the configured Groq model; it does not create or execute a workflow. All listed paths have the prefix **`/api/v1`**, including health, to remove the brief's potential health-prefix ambiguity.

## Baseline: 25 endpoints

| #   | Method and path                          | Phase | Main behavior                                                                              |
| --- | ---------------------------------------- | ----- | ------------------------------------------------------------------------------------------ |
| 1   | `GET /health`                            | 1     | Liveness; no credentials or secret configuration in output                                 |
| 2   | `POST /auth/register`                    | 3     | Create user; 201; Argon2 hashing                                                           |
| 3   | `POST /auth/login`                       | 3     | Authenticate; access JWT plus refresh/CSRF cookies                                         |
| 4   | `POST /auth/refresh`                     | 3     | Rotate refresh session and access JWT                                                      |
| 5   | `GET /auth/me`                           | 3     | Current authenticated user                                                                 |
| 6   | `GET /node-types`                        | 4     | Actual registered types/config schemas/capabilities                                        |
| 7   | `POST /workflows`                        | 4     | Create owned draft; optional initial immutable saved definition                            |
| 8   | `GET /workflows`                         | 4     | Owned, paginated, filtered workflows                                                       |
| 9   | `GET /workflows/{workflow_id}`           | 4     | Owned metadata + current version; optional historical version query                        |
| 10  | `PATCH /workflows/{workflow_id}`         | 4     | Metadata/status update and/or append definition version; expected-version check            |
| 11  | `DELETE /workflows/{workflow_id}`        | 4     | Archive; preserve versions/run history; 204                                                |
| 12  | `POST /workflows/{workflow_id}/validate` | 4     | Validate saved or supplied candidate definition without saving it                          |
| 13  | `POST /workflows/{workflow_id}/runs`     | 5/6   | Exact-version execution; synchronous 201 or opt-in pure background 202; scoped idempotency |
| 14  | `GET /runs`                              | 5     | Owned run summaries with workflow/status filtering; date filtering remains planned         |
| 15  | `GET /runs/{run_id}`                     | 5     | Authorized version snapshot, outputs and actual node-attempt history                       |
| 16  | `POST /runs/{run_id}/cancel`             | 5/6   | Persist cancellation request; best effort for already-issued external effects              |
| 17  | `POST /runs/{run_id}/retry`              | 5/6   | Explicit new run of the original version/input; idempotency and side-effect safety checks  |
| 18  | `POST /workflows/generate`               | 7     | Reviewed generation with authorized selected connections; no auto-save or execution        |
| 19  | `GET /connections`                       | 7     | Owned metadata, never usable credentials                                                   |
| 20  | `POST /connections`                      | 7     | Validate provider/config and create protected secret reference; 201                        |
| 21  | `GET /connections/{connection_id}`       | 7     | Authorized connection metadata                                                             |
| 22  | `DELETE /connections/{connection_id}`    | 7     | Revoke/disable connection; 204                                                             |
| 23  | `GET /runs/{run_id}/events`              | 9     | Authorized paginated durable event history                                                 |
| 24  | `GET /approvals`                         | 10    | Requests the user can legitimately review; status/run/request-ID filters                   |
| 25  | `POST /approvals/{approval_id}/decision` | 10    | Authorized approve/reject, optional note, one winning decision                             |

Declare the static `/workflows/generate` route before a dynamic workflow-ID route, or otherwise ensure routing distinguishes them. All data endpoints require authentication; auth/health routes have their documented exceptions.

**Implemented additions:** `POST /auth/logout` revokes the represented refresh family and clears its cookies. `POST /ai/completions` provides the Groq connection test. The API also includes new-workflow generation, edit proposals, run event listing and streaming, and agent continuation. Logout does not revoke all login families or already issued access JWTs. Registration still issues no cookies/tokens. Also propose a DB-aware readiness endpoint when deployment health checks require it; liveness and readiness are distinct.

Dashboard aggregates, persistent profile/preferences and connection testing/updating are not covered fully by the baseline. New-workflow generation is available for review in the active frontend; version-bound AI editing of saved workflows remains planned.

## Shared conventions

- JSON uses snake_case DTO fields and lowercase status values. UUID entity IDs are strings; editor node IDs remain stable definition-local strings. Timestamps are UTC ISO 8601, durations integer milliseconds.
- MVP list response: `items`, `total`, `page`, `page_size`; default 25, max 100. Whitelist sort/filter fields and use a deterministic ID tie-breaker. Offset pagination can shift under new inserts; SSE uses its separate durable sequence cursor.
- Errors: `{ "error": { "code": "WORKFLOW_NOT_FOUND", "message": "The requested workflow does not exist.", "details": null }, "request_id": "req_..." }`.
- 401 unauthenticated; 403 when permission denial may be disclosed; 404 for missing/not-owned resources to avoid existence leaks; 409 stale version/idempotency conflict/already-decided approval/illegal state; 422 invalid schema or nonexecutable run request; 429 bounded rate limits; sanitized 5xx for dependency/internal failures.
- Workflow validation endpoint can return 200 with `valid: false` for well-formed but semantically invalid candidates; malformed request bodies remain 422. Never return a successful run/generation on provider or validation failure.
- Archive/revoke behavior is explicit; DELETE never erases historical definitions/results implicitly.

## Implemented foundation HTTP behavior — Phase 1C

All current HTTP responses include a fresh server-generated `X-Request-ID` (`req_` plus 32 lowercase hexadecimal characters). Caller IDs are ignored. Success health JSON is unchanged. Error bodies now follow the shared envelope above, with the same ID as the response header. Common codes include `NOT_FOUND` (404), `METHOD_NOT_ALLOWED` (405), `VALIDATION_ERROR` (422), and `INTERNAL_ERROR` (500). Validation details are null; raw exceptions, validator messages, and input values are not returned. Auth/rate-limit errors can be mapped and tested without those features being implemented.

`Allow`, `WWW-Authenticate`, and `Retry-After` are preserved where applicable. Other exception headers are withheld. Errors before response start remain safe JSON even with local debug enabled; after headers are committed, stream/background failures cannot replace the response. OpenAPI documents the shared default error schema and request-ID response header. No additional production endpoint was added. Request IDs are not authentication credentials or tracing span IDs.

## Implemented registration contract — Phase 3A

`POST /api/v1/auth/register` is public and accepts exactly `email`, `display_name`, and `password` as strings. Email is trimmed, syntax-validated with EmailStr and lowercased; display_name is trimmed and bounded to 1–100 characters. Password length is 8–128 Unicode characters, with at least one non-whitespace character. Its original spaces and case are preserved; no composition rules or silent truncation apply. Extra fields are forbidden. No DNS lookup, account verification or breached-password check is performed.

HTTP 201 returns `{ "id": "<uuid>", "email": "owner@example.com", "display_name": "Owner", "is_active": true, "created_at": "<UTC timestamp>", "updated_at": "<UTC timestamp>" }` and `Cache-Control: no-store`. No password/hash/token/cookie is returned. A successful registration does not authenticate later requests.

| Status | Error code               | Meaning                                                                      |
| ------ | ------------------------ | ---------------------------------------------------------------------------- |
| 409    | EMAIL_ALREADY_REGISTERED | Normalized email already exists; includes concurrent signup races            |
| 422    | VALIDATION_ERROR         | Invalid/missing fields or unexpected input; details remain null              |
| 503    | SERVICE_UNAVAILABLE      | Database not configured, connection unavailable, or pool acquisition timeout |
| 500    | INTERNAL_ERROR           | Unexpected failures, including unrelated integrity violations                |

Errors use the shared envelope and matching X-Request-ID. When storage is not configured, dependency resolution may return 503 before invalid body input is evaluated. Duplicate detection intentionally reveals email registration status. Hashing precedes the transaction; only the named uq_users_email/SQLSTATE 23505 violation is classified as an email conflict. The service commits before returning success; output validation failure rolls back. Rate limiting and refresh/session protection are later work. See [registration learning notes](../learning-notes/authentication.md).

## Implemented login and identity — Phases 3B/3C

`POST /api/v1/auth/login` requires an allowed Origin and `X-AgentFlow-Client: web`, without prior authentication. Its body is JSON `{ "email": "owner@example.com", "password": "<exact password>" }`. Email follows registration normalization; password is a strict string of 1–128 Unicode characters with no trimming/normalization. Extra fields are forbidden. HTTP 200 returns `{ "access_token": "<jwt>", "csrf_token": "<opaque proof>", "token_type": "bearer", "expires_in": 900, "user": { "<public user fields>": "..." } }`. Default lifetime is configurable from 60–3600 seconds. Success includes Cache-Control: no-store and Pragma: no-cache. Phase 3C now sets HttpOnly refresh and readable CSRF cookies; raw refresh is excluded from JSON.

`GET /api/v1/auth/me` accepts only `Authorization: Bearer <access_token>` and returns UserResponse, Cache-Control: no-store. It derives the user ID from the validated token, then verifies the account still exists/is active. It never accepts a client user ID as authority. OpenAPI describes HTTP Bearer security on this route; login/register/health remain public.

Tokens use fixed HS256, typ at+jwt, and required sub/iss/aud/iat/nbf/exp/jti/token_type claims. The signature, exact issuer/single audience, UUID identities, access purpose, integer dates, bounded lifetime and expiry are validated; no algorithm is selected from untrusted headers. JWT claims contain no email/password/hash/role. A private random signing key is required, with no built-in key. Signing is not encryption, and jti is not a replay/revocation mechanism.

Wrong password, unknown email, inactive user, invalid/expired token and deleted/missing subject return the same **401 UNAUTHENTICATED**, null details and **WWW-Authenticate: Bearer** challenge. Login invalid body returns 422. Missing key or unavailable storage returns 503; dependency configuration may be resolved before body validation. Missing Bearer credentials on /me return 401 before DB/key lookup. Unexpected failures remain safe 500. All use the shared error envelope and matching X-Request-ID.

Password verification runs outside a DB transaction, including a real dummy check for unknown email. Login rechecks account/hash before issuing; /me consults current state on every call. Refresh rotation/reuse detection are now implemented below. Logout and initial frontend integration are implemented; rate limiting remains later work. See [login/token notes](../learning-notes/login-access-tokens.md) for tested behavior and limits.

## Implemented refresh contract — Phase 3C

`POST /api/v1/auth/refresh` uses cookie credentials, not a body/Bearer/query refresh token. It requires one exact allowed Origin, X-AgentFlow-Client: web, and X-AgentFlow-CSRF matching the readable CSRF cookie and its server-stored digest bound to that refresh token. Login also enforces Origin/client checks to prevent login CSRF. Missing/null/foreign/duplicate Origin or a missing marker yields safe 403. No CORS middleware is introduced by this allowlist.

Default cookies are __Host-agentflow_refresh (HttpOnly) and __Host-agentflow_csrf (readable), both Secure, SameSite=Strict, Path=/, no Domain. Their absolute expiry is the family's deadline. Explicit non-production HTTP mode uses agentflow_refresh/agentflow_csrf without Secure; production refuses that mode and requires HTTPS auth origins when a signing key is configured.

Success 200 returns the same body as login, including new access_token and csrf_token/current user, with no-store/no-cache; both cookies rotate. PostgreSQL stores only refresh/CSRF SHA-256 digests. RefreshSession is the family; RefreshToken rows retain consumed history. Seven-day default expiry is absolute, configurable 300–2592000 seconds, not extended by rotation. Family row locking and a partial unique index allow only one unconsumed token per family.

Missing/invalid/expired/revoked credentials return 401 UNAUTHENTICATED and delete the pair; CSRF failures return 403 FORBIDDEN without consuming/revoking/clearing; storage failures return safe 503 without clearing. Errors use the shared envelope with matching request IDs. An authenticated replay of a consumed token commits whole-family revocation before 401, rejecting its descendants while preserving other login families. Existing access JWTs are not revoked by refresh-family state.

Strict reuse detection includes simultaneous or retried requests: clients must serialize refresh across tabs. At most one simultaneous use gets a replacement, then reuse revokes the family; response loss after commit requires re-login if the old credential is retried. Logout is now implemented below; grace-window recovery and automatic expiry cleanup are not implemented; initial frontend integration is implemented. See [refresh-session notes](../learning-notes/refresh-sessions.md).

## Implemented logout and ownership preparation — Phase 3D

`POST /api/v1/auth/logout` requires allowed Origin and X-AgentFlow-Client: web. With a well-formed refresh cookie, it also requires the matching CSRF cookie/header and stored binding. No body, Bearer credential or signing key is required. An old consumed token can identify/revoke its family, including current descendants. Other login families remain unchanged. Logout/refresh serialize on that same family lock.

Success is **204, empty body**, no-store/no-cache and both cookies deleted with their configured names/path/security flags. Repeated logout, missing/malformed cookies, unknown credentials and already revoked/expired/inactive/deleted families are safe 204 outcomes. Missing/malformed cookies need no database; present well-formed credentials need storage. Invalid Origin/client/CSRF yields safe 403 without mutation/clearing; storage failure yields safe 503 without claiming logout success or discarding the retry pair. All responses include the server request ID. Existing access JWTs retain their expiry; clients must drop their in-memory token on logout. No logout-all route or access-JWT denylist is introduced.

Workflow/version ownership dependencies now use the validated active user, never a caller owner_id. Owner-scoped repository queries require both workflow ownership and version membership. Missing/unowned/mismatched resources all map to the same 404 NOT_FOUND; unavailable storage maps to safe 503. Tests mount private probes to verify this boundary. Phase 4A now mounts metadata CRUD below; mutation services keep owner filters inside each operation's transaction. See [logout/ownership notes](../learning-notes/logout-ownership.md).

## Implemented node catalog — Phase 4C

GET /node-types requires an active-user Bearer JWT and returns no-store NodeTypeCatalog (schema_version "1.0", items). Registered pure types are manual, transform, condition, calculator, merge and end. Each declares type/name/category/description, output_handles, self-contained config_schema, capabilities ["validate_config", "execute"] and execution_ready true. All six now have current executors. No provider/model availability or future connector is invented. Auth errors use existing safe 401/503 envelopes.

The internal validate_node_config operation uses the same typed contracts as generated schemas. Configs forbid extra fields/coercion, enforce discriminated predefined operations, bounded scalar literals and dictionary output-reference syntax. Phase 4D now checks graph topology and upstream node availability through the validation route below. Actual output field/type checks remain runtime work; no standalone config-validation POST is added. Incomplete/unsupported graph candidates still save as drafts under Phase 4B. See [node registry notes](../learning-notes/node-registry.md) and the [real backend walkthrough](../real-backend-walkthrough.md).

## Implemented workflow validation — Phase 4D

POST /workflows/{workflow_id}/validate requires active-user Bearer auth and an explicit body: {} selects current saved version, version_id selects exact owned history, or definition selects an unsaved candidate. Both selectors/provided null/extra fields or malformed bounded definition envelopes are 422. Missing/unowned/mismatched versions share generic 404; versionless current returns 200 valid false/NO_SAVED_DEFINITION. Archived versions can be inspected read-only.

Response fields: workflow_id, workflow_version_id (null for candidate/versionless), source (saved/candidate), valid, execution_ready, issues (code/message/structural path), issues_truncated and plan. execution_ready is true only when the graph compiles and every node has an installed executor (all six registered pure types in 5C). It does not guarantee valid runtime input, a saved snapshot, permission to start an archived workflow or execution success. A valid report's plan summarizes entry_node_id, node_count, edge_count, topological_order and terminal_node_ids. Semantic invalidity is 200 valid false/plan null, with at most 100 static diagnostics. Reports are staged, bounded, no-store and never quote raw configs/validator text. Storage/auth failures keep safe 503/401 behavior.

Compilation requires a supported root envelope (schema_version/nodes/edges plus optional metadata object), strict snake_case nodes/edges, unique bounded IDs, six typed configs, one manual entry, end terminals, exact default/true/false routes, explicit merges, reachability and a DAG. Optional input_mapping and declared config output references require a strict dominating source, not just a possible ancestor. No implicit convergence, parallel fan-out, cycles, arbitrary expressions or unimplemented node types compile. Labels/positions/root metadata do not execute. Actual output field/type checks and operation failures remain runtime work.

The service pins/copies one authorized immutable snapshot, closes its read Session and compiles outside storage. It never saves, appends, activates or rewinds; unfinished drafts still save under Phase 4B. Run creation independently recompiles its exact selected version. The plan order includes all alternative branches, not an executed route. See [workflow validation notes](../learning-notes/workflow-validation.md) and [real-data instructions](../real-backend-walkthrough.md).

## Implemented workflow contract — Phase 4B

All workflow operations require an active-user Bearer JWT; caller owner IDs/cookies do not authenticate or assign ownership. Success responses are no-store. The existing metadata pagination/archive contract now includes immutable draft definitions:

- POST /workflows: strict trimmed name (1–200), optional description (max 5000, default empty) and optional definition. Returns 201/Location and status draft. Omit definition for a versionless draft; include it to insert version 1 and advance the pointer in the same transaction.
- GET /workflows: bounded page/page_size, status and literal case-insensitive name q, default excludes archived; explicit status=archived selects it. Items/totals remain owner scoped, ordered by updated_at/ID descending. Unknown list query fields are 422. Count/pages are not a frozen concurrent snapshot.
- GET /workflows/{workflow_id}: current metadata plus current snapshot. Optional version_id UUID selects a historical snapshot from this same owned workflow; current_version_id/current_version_number and metadata still describe the workflow as read. It does not rewind the pointer. No history-list endpoint yet.
- PATCH /workflows/{workflow_id}: metadata and/or definition. Definition and strict integer expected_version (0–2147483647) require each other; use 0 for a versionless draft, otherwise the server's current number. Omitted metadata is preserved, null/empty body rejected, description empty clears. Owner/status/pointer fields are forbidden. A stale save returns 409 WORKFLOW_VERSION_CONFLICT and rolls back metadata/snapshot/pointer together. Metadata-only edits keep serialized last-write semantics without a version precondition. Identical definition saves still append; no idempotent replay/deduplication is claimed.
- DELETE /workflows/{workflow_id}: archive only with empty 204; repeated owned archive is safe. History/pointer remain, including historical reads. PATCH on an archived workflow returns 409 WORKFLOW_ARCHIVED. Activation/restore remain pending.

WorkflowResponse list metadata fields remain id, owner_id, name, description, status, current_version_id, created_at and updated_at. POST/item GET/PATCH use WorkflowDetailResponse, adding current_version_number and version. Versionless means number 0/version null; a snapshot contains id, workflow_id, version_number, definition, created_by and created_at. IDs are UUID strings and timestamps UTC. Selected historical version and current pointer can differ intentionally.

Definition requires schema_version "1.0" and nodes/edges arrays of JSON objects, max 500/2000 entries, string keys/finite JSON values, nesting at most 32 levels and compact UTF-8 serialization at most 256 KiB. Extension and nested business keys are preserved verbatim. These are draft-storage checks after body parsing; no transport body limit, node/config/DAG validation, activation or execution is claimed. Do not put credentials in snapshots; arbitrary business JSON is not automatically redacted.

Services own mutation transactions and refreshed owner-scoped row locks; public DTOs are built before commit. Missing/unowned/mismatched versions share generic 404, invalid input 422, storage failure 503 and unexpected errors safe 500. See [workflow version notes](../learning-notes/workflow-versions.md) for complete limits, examples and actual verification.

## Internal execution storage — Phase 5A

Migration 0003 implements workflow_runs, node_runs and execution_events, with frozen version identity, retained attempt history, owner-scoped repository operations, expected revisions and atomic state/event writes. Phases 5B/5C use this unchanged schema for actual synchronous runs, including skipped attempts; no new migration was needed. See [execution persistence notes](../learning-notes/execution-persistence.md).

## Implemented run contract — Phases 5B/5C

**POST /workflows/{workflow_id}/runs** requires active-user Bearer auth and exactly `{"workflow_version_id":"<saved-uuid>","input":{...}}`. Both fields are required. Input uses the same finite native JSON object/copy/depth/256 KiB boundaries as execution storage. Definition/owner/status/parent spoofing and other extra command fields are rejected. Version selection is explicit; there is no implicit latest-version start and no unsaved candidate execution.

The service copies/compiles the exact owned saved version, then rechecks workflow archive/ownership/version membership while creating the run. Valid graphs using the six implemented pure types can start. Conditions follow only the selected true/false route; calculators produce bounded numeric results; merge copies the chosen incoming output. Runtime input mapping replaces incoming data when supplied; otherwise nodes receive previous output. manual/end and identity copy their inputs; pick_fields selects exact top-level keys and fails on absent keys. Mapping resolution uses dictionaries and already completed outputs only. A failed attempt prevents downstream execution; nodes unvisited after failure have no attempts. At a successful end, unvisited nodes get pending-to-skipped attempts (input {}, output/error null, no start, duration 0/revision 1) in the same transaction as the end result and run completion. No unchosen input/config reference is runtime-resolved or evaluated.

The response is **201**, Location: /api/v1/runs/{run_id}, Cache-Control: no-store and RunResponse. This synchronous POST waits and returns a persisted succeeded or failed run. Inspect status/error_code: HTTP 201 means a run was created, not that its computation succeeded. RunResponse includes id, workflow_id, workflow_version_id, parent_run_id, trigger_type, status, revision, event_sequence, input/output/error_code, created/updated/start/completion timestamps, exact version (the existing WorkflowVersionResponse shape), and ordered node_runs. Attempts include run/node/attempt identity, status/revision, input/output/error, timestamps and duration_ms. Public JSON uses input/output, not internal input_json/output_json. No synthetic telemetry is included.

**GET /runs/{run_id}** returns that same owned representation with 200/no-store, including earlier attempts and the original version after later saves/archive. A short run-row lock keeps status and attempts coherent with cooperating writers; reads do not mutate history.

Missing/unowned/mismatched resources share 404; invalid body/header/path is 422; a semantically invalid or currently unsupported saved graph returns 422 WORKFLOW_NOT_EXECUTABLE before creation; archive/incompatible state returns 409; storage failure returns safe 503. Runtime failures are persisted codes (EXECUTION_FAILED, INPUT_MAPPING_FAILED or INTERNAL_FAILURE) in a failed 201 run. Raw exceptions/configs are absent from errors/events/logs. Only the owner can inspect business inputs/outputs/version snapshots.

Unkeyed POST creates a new run. Phase 5D now supports optional Idempotency-Key and max_attempts as documented below. Storage failure after a known committed creation returns Location for inspection, with the current transaction rolled back and earlier committed history retained. An initial commit/response loss remains ambiguous; no automatic retry/replay/recovery is claimed. Future 202 worker dispatch belongs to Phase 6. GET /runs listing is implemented below; cancel/retry are implemented below; SSE/events remain proposals. See [first runner notes](../learning-notes/first-runner.md) and [runnable Swagger steps](../real-backend-walkthrough.md).

## Typed branch operations — Phase 5C

condition outputs {"result":boolean}; equality treats number/bool/string/null as separate scalar categories (int/float share numeric equality), ordered operators require finite numbers and contains is case-sensitive substring. Runtime numeric operands and every calculator intermediate/result are within ±10^12, excluding bool/string coercion; comparison strings are at most 4096 characters. calculator supports add/multiply (2–20 operands), subtract/divide (two operands), with explicit literal/output operands, returning {"result":number}. Divide by zero, overflow and invalid runtime types give persisted EXECUTION_FAILED. Missing/non-dictionary input/config references give INPUT_MAPPING_FAILED. Python int/float semantics apply; no currency decimal engine or arbitrary expression evaluation is introduced.

WorkflowRunner walks declared selected edges, not the whole topological order. Nested branches, early ends, shared merges and two handles reaching the same merge are supported. Config bindings and data mappings resolve separately against already executed outputs. The saved compiler/dominator rules still reject branch-local references after convergence. Skipped nodes are recorded only on successful completion, and skip/result/run-completion writes roll back together on failure. API paths/statuses/DTO fields and migration 0003 remain unchanged. See [branch execution rules and runnable JSON](../learning-notes/branch-execution.md).

## Prototype differences addressed by initial frontend adapters

| Existing frontend                                                                   | Proposed backend                                      | Integration action                                                                                                                |
| ----------------------------------------------------------------------------------- | ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Local `wf_...` / `exec_...` IDs                                                     | UUID entity IDs                                       | Demo fixtures remain separate; do not upload/reinterpret them as production IDs                                                   |
| Node IDs `manual`, `llm`, `extract`, `classify`, `agent`, `condition`, `http`, etc. | Keep these identifiers                                | Backend registry is authoritative; illustrative `manual_trigger`/`document_extraction` names are not silently accepted as aliases |
| No definition schema version                                                        | `schema_version: "1.0"`                               | Add explicit schema/adapter and reject unknown versions                                                                           |
| `Workflow.version` and entire graph mixed with metadata                             | Workflow + immutable version + definition             | DTO adapter returns current graph and retains version identity for saves/runs                                                     |
| CamelCase (`sourceHandle`, `systemPrompt`, `workflowId`)                            | Snake_case API fields                                 | Convert only documented DTO/config fields, not user JSON payload keys                                                             |
| Condition `value: "50000"`, dotted variable lookup                                  | Typed comparison value + explicit node-output mapping | Map editor field types intentionally; no string/number guessing during execution                                                  |
| Free-text `approver: "Moulika"`                                                     | `assigned_to` UUID with authorization                 | User selector/owner default; display name never grants permission                                                                 |
| String expressions and `{{...}}` placeholders                                       | Bounded mappings and predefined operations            | Replace ambiguous expressions in API mode; no arbitrary JavaScript/Python evaluation                                              |
| `Execution.nodeRuns` has one displayed entry per node                               | Multiple persisted attempts per node                  | Aggregate latest status for graph; expose attempt history without discarding retries                                              |
| Demo NodeRunStatus omits cancelled                                                  | Backend attempt status includes cancelled             | Add explicit adapter/UI handling when execution is integrated                                                                     |
| Browser timers/local state update runs                                              | Server records + SSE                                  | Server is authoritative; no local simulator for API-backed runs                                                                   |
| Synchronous save/run actions                                                        | Awaitable HTTP commands and loading/errors            | Navigate or mark clean only after server success; retain failed draft and stale-version conflict state                            |
| UI route `/executions/:id`                                                          | API resource `/runs/{id}`                             | Resource names need not match page URLs; adapt in service layer                                                                   |
| Simulated connection cards                                                          | Provider catalog + owned connection resources         | Keep catalog metadata separate from actual connection status/secret reference                                                     |
| Browser-local auth flag                                                             | Actual auth/session and ownership                     | Separate demo and API modes; never use localStorage flag as authorization                                                         |
| Browser-created model/span/usage data                                               | Server/provider actual telemetry                      | Preserve unavailable/redacted states; no synthetic values in real execution history                                               |

The frontend's current `outputSchema` default is an example shape, not necessarily a valid JSON Schema contract. Schema 1.0 must require an actual supported JSON Schema subset. Likewise the existing registry marks several nodes as present for mock mode; backend `/node-types` must advertise only implemented/allowed capabilities.

## Save example and proposed run contract

Workflow draft update example (implemented in Phase 4B; executable semantics remain planned):

```json
{
  "expected_version": 3,
  "name": "Invoice Processing",
  "definition": {
    "schema_version": "1.0",
    "nodes": [
      {
        "id": "start",
        "type": "manual",
        "label": "Start",
        "position": { "x": 0, "y": 0 },
        "config": {}
      },
      {
        "id": "amount_check",
        "type": "condition",
        "config": { "field": "$.start.output.amount", "operator": "greater_than", "value": 50000 }
      },
      { "id": "above_limit", "type": "end", "config": {} },
      { "id": "within_limit", "type": "end", "config": {} }
    ],
    "edges": [
      { "id": "e1", "source": "start", "target": "amount_check" },
      { "id": "e2", "source": "amount_check", "source_handle": "true", "target": "above_limit" },
      { "id": "e3", "source": "amount_check", "source_handle": "false", "target": "within_limit" }
    ]
  }
}
```

Optional labels/positions are presentation metadata. Restrict initial mapping lookups to `$.[node_id].output.[field path]` in concept, serialized without brackets as `$.start.output.amount`; they access only validated upstream outputs. Define the precise grammar in Phase 4; do not introduce a general expression interpreter. The static proposal above uses typed numeric comparison, not the current mock form's numeric string.

Implemented Phase 5D command contract: the existing run body `{ "workflow_version_id": "<uuid>", "input": { "amount": 60000 } }` accepts an optional scoped `Idempotency-Key` header and strict `max_attempts` integer 1–3 (default 1), returning synchronous 201 for new/replayed runs. All six pure types remain supported. The service verifies the version belongs to the owned workflow. A replay returns the original run; a changed body under the same key returns 409. Retry creates a new run with `parent_run_id`, preserving the original history/version; an unsafe partial external retry requires reconciliation or an explicit refusal, not blind reexecution.

The initial engine accepts structured manual input/text. Gmail read-only OAuth connection setup is implemented, while inbox processing, schedules/webhooks, email actions, binary upload/OCR, invoice-specific database tables, parallel fan-out, user teams and arbitrary loops remain separately scoped features. Finishing the invoice example can persist its result in `workflow_runs.output_json`; it does not imply a payment system or an undocumented file-upload API.

## Version-bound edit proposals

`POST /workflows/{workflow_id}/edit-proposal` accepts an edit prompt and exact `base_version_id` for the current owned saved version. The server sends the saved definition and prompt to Groq and returns a complete validated candidate definition for review. It does not change ownership, credentials, run history or metadata and does not save the result.

The editor summarizes added, removed and changed nodes and connections, and lets the user inspect both full definitions. Applying the proposal changes only the unsaved editor draft. Saving uses `PATCH /workflows/{workflow_id}` with the expected current version; a changed base is a 409, not an overwrite. The frontend invalidates the proposal if the editor draft changes.

## Browser auth and event streaming

Short-lived access JWT stays in memory; refresh token is a rotating opaque Secure/HttpOnly cookie backed by a hashed server session. `GET /runs/{run_id}/events/stream` uses Bearer authentication and emits SSE events with sequence IDs. It supports `Last-Event-ID`, checks account/token validity on each poll, and closes periodically for reauthentication. The frontend reconnects with the last sequence and keeps paginated polling as a fallback; no token is placed in the URL.

## Contract verification

Each implemented router emits explicit Pydantic response schemas and OpenAPI. Add examples and contract fixtures as endpoints arrive. Test Python serialization against TypeScript adapters, UUID/timestamp/status cases, schema-version refusal and arbitrary payload-key preservation. No frontend source edits are part of Phase 0; the table above is a migration plan, not a change already applied.

## Implemented run discovery — initial frontend integration

GET /api/v1/runs is authenticated, owner-scoped and no-store. It accepts page (1–1,000,000), page_size (1–100, default 25), optional status and workflow_id UUID; unknown fields are rejected. Returns items/total/page/page_size in created_at DESC, id DESC order. Each summary includes current workflow name and frozen version number with IDs/status/error/timestamps, excluding business payloads, snapshots and attempts. Archived workflows retain history. Empty/out-of-range pages are empty; a foreign workflow filter reveals no rows. Count/page are separate READ COMMITTED queries and may shift under concurrent writes. Database failures use safe 503. No mutation, migration or worker is added. See [frontend API notes](../learning-notes/frontend-api.md).

## Implemented execution commands — Phase 5D

POST /workflows/{workflow_id}/runs and POST /runs/{run_id}/retry accept optional Idempotency-Key: 1–128 ASCII letters/digits and . _ : -, with duplicate fields rejected. Scope is the authenticated owner across both operations. Canonical request identity includes workflow/version/input/max_attempts/retry parent; map ordering is ignored but types and numeric representation are retained. Identical commands return the current original history with 201/Location/no-store; mismatch returns 409. Receipts have no expiry, retain digests only and commit with initial run/event. Replays never launch another runner or recover stranded work, including after archive. Without a key a valid request creates a new run.

Run creation adds max_attempts (strict 1–3, default 1), persisted and immutable. Automatic retries apply only to explicit pure types and INTERNAL_FAILURE/DEADLINE_EXCEEDED; deterministic failures stop immediately. Each attempt is distinct retained history. No backoff, scheduled retries or new elapsed deadline enforcement.

POST /runs/{run_id}/retry requires JSON {} or {"max_attempts":2}; extra input/version fields are rejected. It reruns the original pure snapshot/input from entry, setting parent_run_id. Only failed/cancelled sources qualify. Fresh retries of archived workflows and retries of active/succeeded sources return 409. Already committed keyed retry receipts still replay. POST /runs/{run_id}/cancel takes no body and returns 200/no-store for active or already-cancelled history. Other terminal states return 409. Open attempts/run/events cancel atomically; completed history remains, and in-flight pure results cannot overwrite cancellation. Both routes require owner authentication; missing/unowned return 404. Storage failures use 503 with known retained-run Location.

Migration 0004 adds command receipts and the frozen retry budget. The RunResponse DTO now also exposes max_attempts. See [execution command notes](../learning-notes/execution-commands.md) for lock order, concurrency, ambiguous commits and actual checks.

## Calculator agent — Phase 8A

`GET /api/v1/node-types` includes executable `agent`, configured with `instruction`, `input_field` and `max_tool_rounds` (strict integer 1–5, default 3). Existing exact-version run commands execute agent graphs synchronously with 201, including when pure background mode is enabled. They are excluded from automatic node retry, whole-workflow retry and worker recovery. No new route or migration is added.

Successful output contains `model`, `content` and actual `tool_calls`. The attempt has optional `agent` operational metadata: `tool_rounds`, `provider_calls` (at most six validated provider metadata records) and a static `failure_reason` on failure. This metadata is stored in the same immutable node-status event as the result/failure; business outputs are not rewritten with operational usage. See [full limits and sample](../learning-notes/calculator-agent.md).

## Authorized HTTP agent tools — Phase 8B

The same `agent` type is displayed as **Tool Agent**. Its config adds `connection_ids`: up to ten unique UUID strings, empty by default for calculator-only compatibility. Saving freezes the selected allowlist in that immutable workflow version. Before each model turn the runner rechecks active ownership; before HTTP it reauthorizes/decrypts in a short session, then closes storage before external I/O. Missing/unowned/revoked bindings fail `CONNECTION_UNAVAILABLE` without leaking ownership. The model receives only selected ID/name/endpoint metadata and a code-owned `http_get` schema accepting one selected `connection_id`. Fetched JSON goes to Groq; credentials remain server-side. Generation/edit proposal authorization now covers these agent bindings as well as standalone HTTP nodes.

HTTP uses the existing fixed public HTTPS GET executor with a 32 KiB agent response limit and the smaller of its 20-second budget or remaining agent time. Calculator and HTTP share the existing 1–5 tool limit and 60-second budget. Each endpoint can be fetched once per agent invocation, including duplicate URL aliases; a separate agent node/fresh run is a new invocation. Phase 8C adds explicit continuation from saved post-tool checkpoints; it does not add automatic request retry, background execution or recovery of an unknown external effect.

Successful HTTP `tool_calls` add `id`, `tool: "http_get"`, `connection_id`, `status_code` and `body`; existing calculator entries retain their shape. Agent metadata adds defaulted `http_tool_attempts` and bounded `http_calls` containing selected IDs and recorded status/error. Old stored events decode with empty defaults. These summaries commit atomically with the terminal attempt event and remain available on failure; they do not guarantee that every external request completed or its usage is known. Static failure reasons now include `connection_unavailable`, `http_failure`, `duplicate_http_call` and `tool_result_too_large`. See the [sample flow, authorization and limits](../learning-notes/http-agent.md).

## Owner approvals

Owner approvals for pure background workflows add `GET /api/v1/approvals`, `GET /api/v1/approvals/{approval_id}` and `POST /api/v1/approvals/{approval_id}/decision`. Bearer authentication and current ownership are required. Lists support status/run filters and bounded pagination. Decisions accept `approved` or `rejected` and an optional note; identical replay returns the receipt, conflicting decisions return 409, and an elapsed request resolves to `expired` without resuming. See [approval contracts, restart recovery and limits](../learning-notes/approvals.md).
