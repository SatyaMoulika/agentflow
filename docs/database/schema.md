# Proposed schema and transaction design

Migration **0010** extends run/attempt failure-code checks for explicit provider
outcomes and refuses lossy downgrade of retained failures. Operational usage/model
metadata lives in existing immutable node-status event JSON, committed atomically
with the result/failure. No extra result column or mutable usage ledger is added.
See [provider history semantics](../learning-notes/provider-integration-hardening.md).

Migration **0009** adds owner-scoped `connections`, immutable endpoint/owner identity,
credential-state constraints, revocation-only updates and a listing index. Optional
credentials use a server-held Fernet key and owner/connection-bound ciphertext.
Revocation removes ciphertext and retains identity; downgrade refuses retained
connections or HTTP failure history. Runs/attempts add `CONNECTION_UNAVAILABLE`,
`HTTP_REQUEST_FAILED` and `HTTP_TARGET_BLOCKED`. See
[connections](../learning-notes/secure-http-connections.md) for boundaries and tests.

Migration 0008 adds immutable `retry_base_seconds`/`retry_max_seconds` policy columns
to `workflow_dispatches` and retained `node_retries` rows identifying the failed
attempt, run, creation/due time and mutually exclusive resume/cancellation time.
Composite attempt FKs, eligibility/resolution guards, a unique pending-retry index
and immutable deadlines preserve history. Execution events now accept
`node.retry_scheduled` with required attempt context. Downgrade refuses retry history.
See [scheduled retries](../learning-notes/scheduled-retries.md).

Migration 0007 adds `workflow_dispatches` as retained worker provenance and
redispatch timing, plus nullable `outbox_messages.workflow_run_id` targeting that
provenance. A kind/target check and partial unique pending-workflow index constrain
delivery. Run/event/receipt/provenance/initial intent commit atomically; published
outbox rows stay immutable. Upgrade preserves existing synchronous runs and probes.
Downgrade refuses existing workflow dispatch history. See [background execution](../learning-notes/background-execution.md)
for transactions, recovery and the isolated checks. Earlier phase schemas below are
historical snapshots and planning targets.

Phase 6C groundwork adds queued-run claim leases and fencing primitives. Workflow execution remains synchronous; persisted progress, worker recovery, workflow outbox integration and asynchronous dispatch are not yet implemented. See [claim notes](../learning-notes/run-claims.md). Prior phase descriptions below are historical.

Phase 6B foundation: migration 0005 adds a durable outbox and leased dispatcher for transport probes. Workflow runs remain synchronous; worker claims/recovery and workflow dispatch remain next. See [outbox notes](../learning-notes/transactional-outbox.md). Earlier phase descriptions below are historical.

Phase 5D complete, 4 November 2026: command receipts, bounded pure retries, whole-workflow retry lineage and cooperative cancellation are implemented and wired to the frontend. API 18 operations/15 paths; migration head 0004. Backend 905 tests, frontend 120 tests pass. Next is Phase 6 background dispatch/recovery. See [execution command notes](../learning-notes/execution-commands.md). Earlier snapshots below describe their historical increments.

Current status, 4 November 2026: initial frontend API integration was brought forward after backend Phase 5C. The active App uses src/api for real authentication, owned workflow editing/validation and execution history; earlier prototype modules described below remain unrouted reference code. GET /runs is implemented (16 operations/13 paths); migration head remains 0003. Backend 5D is next. See [frontend API notes](../learning-notes/frontend-api.md) and the [startup walkthrough](../real-backend-walkthrough.md). Browser visual QA remains outstanding.

Phase 0 target design, updated through Phase 5C (3 November 2026). PostgreSQL is authoritative. SQLAlchemy mappings and Alembic revision 0001 now implement users, workflows, and workflow_versions. Phase 2C adds repositories and transaction/concurrency checks without changing revision 0001. Phase 3C migration 0002 adds refresh_sessions (families) and refresh_tokens (consumed hash history), separate tables for locking and replay detection. Phase 5A migration 0003 adds workflow_runs, node_runs and execution_events, with owner-scoped repository operations and lifecycle guards. Other tables and future lease/checkpoint/idempotency columns remain proposals. See [execution persistence notes](../learning-notes/execution-persistence.md) for exact implemented fields and transitions. See [refresh-session notes](../learning-notes/refresh-sessions.md) for implemented fields and constraints. See [model/migration notes](../learning-notes/migrations.md) for actual fields, constraints, triggers, and verification; [session notes](../learning-notes/sqlalchemy.md) cover Phase 2A.

## General conventions

Application entities use UUID IDs. The target table below includes future fields; only the implemented inventory in the linked learning notes is present in migrations 0001–0003. Events use a global bigint primary key plus a distinct per-run replay sequence. Timestamps are UTC `timestamptz`. Store status values with checked text/string enums initially, serialized as lowercase API strings; this avoids silently diverging from existing frontend states while retaining valid-state constraints.

Normalize identities, ownership, versions, run/attempt history and relationships into tables. Use JSONB for variable workflow definitions, node inputs/outputs, event payloads and executor metadata. JSONB does not replace foreign keys, ownership checks or state-transition rules. Add GIN indexes only for demonstrated JSONB query needs, not indiscriminately.

## Table constraints and useful indexes

| Table               | Important invariants                                                                                                                                                                            | Initial useful indexes                                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `users`             | UUID PK; case-normalized email unique; Argon2 hash only; bounded fields; active flag                                                                                                            | Unique index on normalized email                                                                       |
| `workflows`         | Owner FK; checked status; current pointer refers to a version of this same workflow                                                                                                             | `(owner_id, updated_at, id)`; `(owner_id, status, updated_at, id)`                                     |
| `workflow_versions` | Workflow/creator FKs; `version_number >= 1`; unique `(workflow_id, version_number)` and `(workflow_id, id)` for composite references; supported schema version                                  | Version lookup/uniqueness indexes; creator FK index if queried                                         |
| `workflow_runs`     | Workflow/version FKs with same-workflow constraint; legal status; immutable definition reference; parent-run FK for retry lineage; nonnegative lease generation/event sequence                  | `(workflow_id, started_at, id)`; status/next-wake recovery index; lease-expiry index for active states |
| `node_runs`         | Run FK; node ID belongs to its saved definition; unique `(workflow_run_id, node_id, attempt_number)`; attempt >= 1; duration >= 0; unique `(workflow_run_id, id)` to constrain event references | `(workflow_run_id, started_at, id)`; run/node/attempt uniqueness                                       |
| `execution_events`  | Run FK; nullable node-attempt FK constrained to the same run; unique `(workflow_run_id, sequence)`; payload validated/redacted                                                                  | `(workflow_run_id, sequence)` for ordered replay                                                       |
| `connections`       | Owner FK; provider/status constraints; owned connection name unique per provider if adopting that naming rule; no raw secret column                                                             | `(owner_id, provider, status)`                                                                         |
| `approvals`         | Run/requester/assignee FKs; defined status; at most one request per `(workflow_run_id, node_id)` for the loop-free MVP; decision immutability                                                   | `(assigned_to, status, created_at, id)`; partial pending-expiry index                                  |
| `refresh_sessions`  | Family UUID PK, user FK ON DELETE CASCADE, created_at, absolute expires_at > created_at, nullable revoked_at                                                                                    | user and expiry indexes                                                                                |
| `refresh_tokens`    | Family FK ON DELETE CASCADE, unique token_hash; hex format checks on both digests, created_at, consumed_at; only digests stored                                                                 | unique token hash; family index; partial unique family WHERE consumed_at IS NULL                       |
| `dispatch_outbox`   | Run FK; logical dispatch key unique; retry count >= 0; payload excludes secrets; claim/publish lifecycle                                                                                        | Partial `(available_at, created_at)` where unpublished                                                 |
| `idempotency_keys`  | User/run FKs; unique `(user_id, operation, key_hash)`; fingerprint detects changed request body; retention policy explicit                                                                      | Unique scoped key index; expiry cleanup index                                                          |

Foreign-key columns get indexes where joins, lookup or deletion/reconciliation require them. Do not assume PostgreSQL automatically indexes referencing columns.

## Implemented execution history — revision 0003

workflow_runs stores workflow/exact-version/optional same-version parent identity, manual trigger, status/revision/event_sequence, bounded input/output objects, static error code and created/updated/start/completion times. It indexes workflow/creation/id, status/creation/id and parent lookup. It has no lease, next-wake or checkpoint columns yet.

node_runs stores run/saved-node/attempt identity, status/revision, input/output/error and timestamps/duration. Unique run/node/attempt and a partial unique open-attempt index retain history without simultaneous open attempts for one node. SQL guards validate membership against the run's frozen definition, freeze identity/input and enforce legal transitions/revision increments.

execution_events stores global bigint identity, run, optional same-run attempt, positive unique per-run sequence, event type, metadata object and time. Run events reject attempt IDs; node events require them. Events reject UPDATE/DELETE/TRUNCATE; runs/attempts reject DELETE/TRUNCATE. Ordinary business writes use the repository/UoW so status and event commit atomically; privileged SQL does not automatically synthesize events.

Succeeded rows require object output and no failure code; failed rows require a code-owned failure and no output. Timestamp/result/state consistency checks are enforced in PostgreSQL. JSON object payloads have a repository compact UTF-8 limit of 256 KiB and a direct-SQL textual JSONB ceiling of 1 MiB. Arbitrary JSON inputs/outputs are not automatically redacted. Run/attempt lifecycle storage reserves waiting/cancelled states without implementing approval/cancellation services. Full field, constraint and function explanations are in [execution persistence notes](../learning-notes/execution-persistence.md).

## Circular workflow/version relationship

Migration/creation order:

1. Create users, then workflows with nullable `current_version_id` but without its FK.
2. Create workflow_versions with `workflow_id` FK and required unique keys.
3. Add the current-version composite FK `(workflows.id, workflows.current_version_id)` → `(workflow_versions.workflow_id, workflow_versions.id)` using an explicit named Alembic constraint.
4. In one service transaction: insert workflow without a pointer, insert its first version, then set its pointer. Commit only the valid final state.
5. Add run references with the same-workflow composite constraint when runs are introduced.
6. Downgrades remove referencing constraints before dropping referenced tables. Test downgrade/re-upgrade on an isolated database.

An immutable version is never updated in place or deleted by normal CRUD. Enforce this through append-only repository operations and verify no update route can mutate it; the initial migration adds a statement-level UPDATE/DELETE/TRUNCATE guard to make the guarantee hold across API and worker code. The current pointer changes on a save. Metadata-only changes do not append a snapshot. Phase 4B exposes immutable draft saves/history without changing this schema: a successful supplied definition always appends, even for identical JSON. Optional initial definition and pointer creation are atomic; stale expected-version saves roll back accompanying metadata too. Draft saving remains permissive. Phase 4D separately validates/compiles exact saved versions or candidates read-only; the run service recompiles the exact owned version before executing. See [workflow version notes](../learning-notes/workflow-versions.md).

## Transaction boundaries

- **Register:** insert user and commit; map unique-email races to a stable API error.
- **Refresh:** lock the refresh-session/family state, validate expiry/revocation, mark the old token consumed and insert its replacement atomically. Retain consumed hashes; a replay revokes the family and commits before returning 401. Concurrent refresh/reuse must not produce two valid descendants unnoticed.
- **Workflow save:** lock/check current pointer or expected version, append version, advance pointer, commit. Concurrent stale writer loses with 409.
- **Run creation (5A storage):** lock owned workflow, select exact version and insert queued run + run.created event together. Phase 5B exposes an exact-version run command that copies/compiles the owned snapshot outside storage before this locked creation recheck; 5D adds scoped command idempotency and Phase 6 adds the outbox.
- **Node start/result (5A storage):** lock the containing run, refresh/check expected revisions, create/transition an attempt and append an event in one caller-owned unit of work. Latest-attempt reads refresh cached states; each retry is a new numbered attempt. Phases 5B/5C execute all six registered pure types between those transactions and persist actual results/failures; the end result, unvisited-node skips and succeeded run/events commit together in one final unit of work; no checkpoint exists yet. Future provider/tool calls also belong outside short transactions.
- **Approval creation:** pending approval + waiting run/checkpoint + event in one transaction.
- **Decision/expiry/cancel:** lock run first, then approval(s), in the same consistent order everywhere; update legal states and append event/resume outbox atomically. This reduces deadlock risk and prevents cancellation/decision races from reviving a terminal run.
- **Outbox publisher:** claim pending rows with locking/lease, publish outside a long-held transaction, then mark publication. Duplicate publication remains possible and expected.

`execution_events.sequence` comes from incrementing a run's `event_sequence` while the same transaction holds its run lock. This serializes sequence allocation with commit order for that run. A plain database sequence value allocated before commit is not a sufficient replay-order guarantee.

## Deletion, privacy and retention

Workflow DELETE archives rather than physically deleting history. No broad `ON DELETE CASCADE` should erase workflow versions, runs, attempts or approval/audit records. Prefer restrictive FKs for business history; define a separate authorized retention/deletion procedure later. User deletion/deactivation and credential revocation are separate operations, not an unreviewed cascading wipe.

A connection DELETE revokes/disables it and removes/invalidates its secret reference; references in old version snapshots remain historical metadata. A run requiring a revoked connection must fail authorization/configuration clearly. Encrypt stored credentials through an infrastructure adapter with a deployment-held key, or keep only a secrets-manager reference. Never put a usable credential in a workflow definition or event.

Payloads may themselves be sensitive. Define capture/retention/access rules separately from status/trace metadata. Export redacted operational metadata to Phoenix by default. Input/output persistence is bounded and subject to access controls; a settings checkbox is not enforcement by itself.

## Migration staging

Phase 2 establishes users/workflows/versions and the migration/session foundation. Phase 3 adds refresh sessions. Phase 5 adds runs, attempts, events and API idempotency. Phase 6 adds outbox/lease recovery columns. Connections arrive before controlled HTTP tooling; approvals with Phase 10. Agent checkpoint setup belongs to its maintained checkpointer adapter and is isolated from application migrations.

Every later column/index/constraint change gets an Alembic migration. Do not precreate unused tables simply because they appear in the ERD.

## Implemented command storage — migration 0004

workflow_runs.max_attempts is a non-null integer default 1, constrained 1–3 and immutable after creation. Existing runs receive 1. run_commands has composite primary key (owner_id, key_digest), request_digest, run_id and created_at. Digests are 64 lowercase hexadecimal characters; restrictive FKs retain owner/run context. An insert trigger verifies the run belongs to that owner; UPDATE/DELETE/TRUNCATE are refused. Creation is serialized per owner and receipts commit with run/event. No retention cleanup, worker leases or outbox is implemented here. Additive upgrade and disposable downgrade/re-upgrade preserve existing run/auth/workflow rows; downgrade drops receipts/budgets and belongs only to disposable testing.
