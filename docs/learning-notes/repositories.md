# Repositories and transaction boundaries — Phase 2C

## Implemented scope

UserRepository and WorkflowRepository now provide concrete persistence operations over a caller-owned SQLAlchemy Session. Database.unit_of_work() provides a transaction context. These are internal Python components, not new API endpoints. Authentication, password hashing, workflow CRUD services, graph validation, and HTTP mappings remain in their planned phases.

No dependency, table, index, constraint, or migration changed. Alembic revision remains 0001. Private `.env`, generated frontend assets, frontend source, and the earlier SQLite drafts were untouched. All new writes during verification targeted disposable schemas in the guarded local test database.

## Why repositories do not commit

One use case can write several tables. If inserting a user commits immediately and creating their first workflow fails, partial data remains. The caller must choose one transaction around both repositories. Each repository flushes pending work so IDs/defaults exist and database constraints fail early; flushing does not commit or make changes visible to another transaction.

`Database.unit_of_work()` uses the existing `session()` context plus `session.begin()`. Entering the context explicitly chooses the transaction boundary. Normal exit commits; an exception (including a commit/flush failure) rolls back; either path closes the session. Repositories never call commit/rollback. Let failures propagate outside the unit of work before handling them. See [SQLAlchemy transactions](https://docs.sqlalchemy.org/en/20/orm/session_transaction.html).

`Database.session()` retains its earlier behavior: it only closes, rolling back uncommitted work. Use it for reads or manually managed transactions. Do not start independent nested units of work and assume they are one transaction: pass the same Session to cooperating repositories. Convert required results to response DTOs inside a future service; lazy ORM relationships cannot safely be loaded after the session closes.

```text
Future synchronous service (not implemented yet)
  → with database.unit_of_work() as session
      → UserRepository(session): insert/lookup
      → WorkflowRepository(session): insert draft
      → append version and move pointer
  → success: commit all → close
  → exception: rollback all → close → caller handles failure
```

There is no new request path today: public health remains the same, with no database query. Future sync services run their entire unit of work in the same thread; sessions are never shared across concurrent workers.

## Files, functions, and boundaries

| File                                                                   | Implemented responsibility                                                                                                                                                                                                                                                 |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/infrastructure/database/session.py`                               | Adds `Database.unit_of_work() -> Iterator[Session]` as an async-free context manager around a new operation-local session and transaction. Existing session/pool behavior is unchanged.                                                                                    |
| `app/modules/auth/repository.py`                                       | `UserRepository(session)` accepts an existing Session. `add(email, password_hash, display_name) -> User` inserts/flushes. `get_by_id(UUID)` and `get_by_email(normalized_email)` return a User or None. Inputs must already be normalized/hashed by a future auth service. |
| `app/modules/workflows/repository.py`                                  | `WorkflowRepository(session)` inserts draft metadata, performs owner-scoped workflow/version reads, provides bounded deterministic listings, and appends immutable snapshots under a workflow row lock. All writes flush without committing.                               |
| `app/modules/workflows/exceptions.py`                                  | `WorkflowNotFoundError` and `WorkflowVersionConflictError` are plain exceptions with static public-safe messages. They import neither HTTP nor SQLAlchemy. Missing/not-owned resources have the same outcome.                                                              |
| `tests/integration/conftest.py`                                        | Adds repository_database: migrates a random schema, then binds independent pooled sessions using schema_translate_map. Other migration/model fixtures keep their existing connection isolation.                                                                            |
| `tests/integration/test_repositories.py`                               | Real read/write, transaction visibility, rollback/recovery, closed-session, ownership, listing, snapshot-copy, cached-navigation, stale-edit, and invalid-envelope checks.                                                                                                 |
| `tests/integration/test_repository_concurrency.py`                     | Threaded writers with separate sessions/connections prove stale-save exclusion and unique-email race rollback.                                                                                                                                                             |
| Guides, plan, architecture/schema status, development log, these notes | Record actual scope and next increment. Manifest/lock and migrations are unchanged.                                                                                                                                                                                        |

Both concrete repositories import models through the explicit registry so all relationship targets are registered before ORM use. There is no generic repository base, abstract interface, HTTP dependency, or extra unit-of-work class: none is needed for this concrete boundary yet.

## Query behavior

User email lookup is exact. The repository does not lowercase/validate email, verify passwords, or enforce account activity; those are AuthService responsibilities in Phase 3. It accepts a password_hash argument, never a plaintext-password operation. Test hashes are synthetic fixture values, not evidence that password security is implemented.

`get_owned(workflow_id, owner_id)` includes both IDs in SQL. `get_version_owned(workflow_id, version_id, owner_id)` joins the owning workflow and checks all three IDs, so knowing a version UUID alone does not bypass scope. Nonexistent and not-owned resources return None. The append operation uses the same scope and raises WorkflowNotFoundError for either case.

`list_owned` accepts limit 1–100 and a nonnegative offset; it orders by updated_at descending, then ID descending. It includes archived rows in this foundation method and exposes no public pagination contract yet. API status filters, totals, and final pagination semantics belong to Phase 4. These queries require a trusted owner_id from the future authenticated service: they do not authenticate callers by themselves.

## Version append and concurrency

```text
append_version(workflow_id, owner_id, expected_version, definition)
  → flush pending changes in this transaction
  → SELECT owned workflow FOR UPDATE, refreshing cached ORM attributes
  → read current pointer's version number (0 if versionless)
  → compare with expected_version; stale value raises conflict
  → calculate max(history version_number) + 1
  → deep-copy definition into a new WorkflowVersion; flush
  → move current_version_id; flush
  → expire cached current/history navigation and updated_at
  → caller exits unit of work: commit and release lock
```

The expected number is a stale-write check, not an instruction for the new number. A versionless draft uses expected_version 0. History allocation uses the maximum saved number, so moving the pointer backward through lower-level code would not reuse an old number. Owner is recorded as creator; collaboration/other approvers are not part of the current ownership model.

PostgreSQL row locks serialize cooperating appends for the same workflow until commit/rollback. Two writers can both read version 1 first; the winner appends version 2. After that transaction commits, the waiting writer reloads the workflow and rejects its stale expected version rather than adding version 3. The existing database unique constraint remains the final defense against duplicate numbers. Raw writers that bypass this lock protocol can still cause integrity errors; this repository does not retry them. Tests use PostgreSQL's default READ COMMITTED isolation. Other isolation levels can raise serialization errors requiring a later explicit retry policy. See [PostgreSQL row locks](https://www.postgresql.org/docs/16/explicit-locking.html).

`populate_existing=True` is important because a Session identity map may already contain an older workflow. Merely executing another SELECT can retain loaded attributes. Explicit refresh makes the expected-version comparison use the locked row. Pending changes are flushed before refresh so it cannot silently discard earlier metadata edits in the same transaction; a subsequent conflict rolls those edits back with the whole unit of work. See [SQLAlchemy populate existing](https://docs.sqlalchemy.org/en/20/orm/queryguide/api.html#populate-existing).

After the pointer changes, the cached view-only current_version/history relationships and timestamp are expired. Reading them again in the same open session reloads current values rather than returning an earlier snapshot. The definition is deep-copied at insertion so later mutation of the caller's nested input cannot alter the returned snapshot object. Database triggers still protect actual saved rows. This is storage concurrency, not validation that a definition is an executable DAG.

## Failure handling and transaction limits

Invalid list bounds/negative expected numbers raise ValueError. Missing/not-owned workflow writes raise WorkflowNotFoundError; stale saves raise WorkflowVersionConflictError. Database constraint violations remain SQLAlchemy IntegrityError for the future service to classify using the relevant constraint. No HTTP handlers for these internal outcomes have been added because there are no consuming endpoints yet.

If a constraint fails after user/workflow/version inserts, or business code raises after those flushes, the unit of work removes all of those writes. If a stale save occurs after pending metadata edits, those edits roll back as well. Catching and swallowing exceptions inside the transaction can change intended behavior; handle them outside the context. Database errors must not be copied into HTTP responses or logs; the existing HTTP boundary remains available for future routes.

Locks remain held until the caller ends the transaction. Do not perform model/tool calls, network waits, or human approval inside it. The repository does not configure production statement/lock deadlines or perform automatic deadlock retries; those need explicit policies when services are introduced. Concurrency tests set local SQL deadlines and bounded barriers/future waits to fail instead of hanging.

## PostgreSQL verification

The existing guarded TEST_DATABASE_URL is required. Repository fixtures reuse the migrated random-schema setup, but schema_translate_map directs **independent engine connections** to that schema. They do not bind every Session to one shared transaction/connection, which would be unable to prove actual commit visibility or locking. Fixture cleanup drops only its own schema after all worker sessions close; the public test schema and development database are untouched.

The suite adds **15 integration cases**:

- Commit user/workflow/first-version together; exact/missing lookups and permanent session closure.
- Business and database failures roll back all writes; a fresh transaction subsequently works.
- Flushed repository inserts are invisible to another connection and disappear without commit.
- Other owners and mismatched workflow/version identifiers cannot read/append those resources.
- Bounded owner listing with deterministic tie-breaking; three invalid pagination cases.
- Snapshot input copying, preserved old history, refreshed cached relationships/timestamp, and preserved pending metadata edits.
- Stale saves roll back other pending changes without adding a version.
- Two invalid snapshot-envelope cases preserve the current pointer and existing history.
- Concurrent cached-version writers use distinct backend connections and produce one commit/one conflict.
- Concurrent duplicate emails produce one committed row/one unique-constraint failure with rollback.

On 30 October 2026 the full checker reports **105 tests passed**, Ruff lint/format passes for **47 Python files**, and Pyright reports zero errors/warnings. Ordinary checks report **55 passed, 50 skipped**. Existing migration round-trip/drift and schema tests remain green. No dependency or revision change was required. The development database remains at 0001; it was not written by these tests. Its existing service remains running; only the verification test container is removed afterward.

From your current `agentflow/backend` directory:

```bash
# Ordinary checks; database tests are explicitly skipped:
uv run --locked python scripts/check.py

# Start the dedicated test service and include real PostgreSQL checks:
docker compose --profile test up -d --wait postgres_test
TEST_DATABASE_URL='postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test' \
  uv run --locked python scripts/check.py --integration
```

From the repository root, add `--directory backend` to uv run. The published test credential is local-only. No frontend, authentication, live provider, worker, or new HTTP-server behavior was tested for this increment.

## Review questions

Discuss one at a time:

1. Why must repositories flush without committing when several tables form one operation?
2. What happens if an exception escapes a unit of work after three successful inserts?
3. Why can a cached ORM object make a locked read stale without populate_existing?
4. Why must a concurrency test use independent PostgreSQL connections?
5. Why is an owner-filtered SQL query still not authentication?

## Independent exercise and next increment

Add a PostgreSQL test that raises after a successful version append, then verifies in a fresh unit of work that the earlier version remains current and the new version does not exist. Use the isolated repository_database fixture and no development writes. Try it before requesting a solution.

Phase 2 database foundation is complete. Next: **Phase 3A — registration with Argon2 hashing, AuthService, safe unique-email conflict mapping, and the registration endpoint**. Token login/refresh follow in later authentication increments.
