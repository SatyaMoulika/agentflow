# Models and migrations — Phase 2B

## Scope and architecture

Three active SQLAlchemy models now map to PostgreSQL tables: User, Workflow, and WorkflowVersion. Their modules own the persistence definitions; the shared database infrastructure owns Base/metadata, the model registry, engine, and session factory. Alembic owns schema history. Models are not HTTP response schemas and will not be returned directly by future endpoints.

This increment added no authentication, password hashing, workflow CRUD, repository, graph compiler, or model provider operation. Phase 2C now adds [repositories and transaction contexts](repositories.md). Those follow in their owning increments. The earlier `backend/agentflow/` files and generated frontend `dist/` assets are unchanged.

## Table design and constraints

| Table               | Fields and database invariants                                                                                                                                                                                                                   |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `users`             | UUID PK; unique lowercase/space-trimmed email (max 320); nonempty password_hash (max 1024); nonempty display_name (max 100); active flag defaults true; timezone-aware created_at/updated_at                                                     |
| `workflows`         | UUID PK; owner FK; nonempty name (max 200); description defaults empty; status defaults draft and is limited to draft/active/paused/archived; nullable current_version_id; created_at/updated_at                                                 |
| `workflow_versions` | UUID PK; workflow and creator FKs; positive version number, unique per workflow; JSONB object definition; supported schema_version `1.0`, matching a non-null JSON string field; created_at; database guard rejects UPDATE, DELETE, and TRUNCATE |

UUIDs are identifiers, not permission checks. SQLAlchemy supplies uuid4 values, while database defaults also support inserts outside the ORM. `timestamptz` represents instants; the tested Compose server returns UTC offsets. Future response schemas must serialize timestamps as UTC. Timestamp defaults use PostgreSQL now(); user/workflow updates run a database trigger using clock_timestamp(), including direct SQL updates. `FetchedValue` tells SQLAlchemy that the database can change updated_at; refresh before depending on an already-loaded object's latest timestamp.

Email checks enforce the selected normalized storage form; they do not validate email deliverability or implement account registration. Password hashing/Argon2 verification belongs to Phase 3, not a SQL constraint. The database cannot prove an arbitrary string is a real password hash. Tests use synthetic fixture values only; no actual accounts were created in the development database.

The JSONB constraints establish a versioned storage envelope, not executable graph validity. Empty node lists can still be stored; typed node configuration, ownership authorization, DAG validation, limits, and compilation are Phase 4. `dict[str, Any]` reflects the currently variable JSON shape. Version numbers must be positive/unique; consecutive allocation and stale-write handling are service/repository responsibilities, not implemented here.

## Relationships and indexes

One user owns many workflows. One workflow has many version snapshots. A version has one creator, whose identity exists independently of the workflow owner. Foreign keys ensure referenced rows exist; later authorization checks must verify who may create/edit each resource.

The optional current-version pointer is separate from history. It is valid for a deliberately versionless draft to have no pointer. The composite FK compares `(workflow.id, workflow.current_version_id)` with `(workflow_version.workflow_id, workflow_version.id)`. Referencing an existing version from another workflow therefore fails. The target has a matching unique key because PostgreSQL requires referenced columns to be unique. See [PostgreSQL constraints](https://www.postgresql.org/docs/16/ddl-constraints.html).

ORM joins disambiguate the history FK from the circular current-pointer FK with explicit `foreign_keys`. The current_version relationship is view-only: set current_version_id deliberately after inserting/flushing the new version. Assigning a view-only relationship is not a persistence operation. If that relationship was already loaded, expire/refresh it or reload in a new session after changing the pointer; an old loaded object is not a live query. See [SQLAlchemy relationships](https://docs.sqlalchemy.org/en/20/orm/basic_relationships.html).

Named indexes cover `(owner_id, updated_at, id)` and `(owner_id, status, updated_at, id)` for future owned listings. Version uniqueness on `(workflow_id, version_number)` also indexes history lookup; a creator index supports creator references. No speculative JSONB GIN index is added.

All current foreign keys use RESTRICT rather than cascading history deletion. ORM collections use passive_deletes='all' so deleting a loaded parent does not first null child references. A future workflow DELETE will archive; this increment tests that raw/ORM physical deletion cannot erase version history implicitly.

## Creation transaction and migration order

```text
Alembic upgrade 0001:
  create users
  → create workflows (current pointer has no FK yet)
  → create workflow_versions and unique keys
  → add composite current-pointer FK
  → add version immutability and updated_at functions/triggers

Future service operation, one transaction:
  insert user/identify existing owner
  → insert workflow with null pointer → flush
  → insert first version → flush
  → set workflow.current_version_id → commit
```

The integration fixture exercises this order through the ORM. `flush()` sends pending rows and obtains IDs/defaults without committing. A failure in the future service transaction should roll everything back. Dedicated repository/transaction operations and race tests are Phase 2C; they are not inferred from these mappings.

The migration's statement trigger rejects version UPDATE/DELETE/TRUNCATE, even when the operation would affect zero rows. ORM assignment and raw SQL are both covered. Replacing a definition requires an INSERT of a new snapshot, then moving the workflow pointer. A database owner/superuser can still drop/disable guards; deployment role restrictions are later work. SQLAlchemy does not track arbitrary in-place changes to plain JSON dictionaries automatically; treat loaded versions as immutable rather than mutating a nested dict and expecting a flush error.

Downgrade removes the guard, drops the composite FK, then drops versions, workflows, users, and helper functions. **Downgrading this initial revision destroys its table data.** Tests run that path only in random schemas of the dedicated test database. No development downgrade was run. An upgrade after a downgrade recreates the schema, not the deleted data. There is no application startup migration or `create_all()` path.

## Files and important calls

| File                                                                        | Responsibility                                                                                                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `app/infrastructure/database/base.py`                                       | `Base(DeclarativeBase)` owns shared MetaData and consistent constraint/index naming.                                                                                                                                                                                                                                                                          |
| `app/infrastructure/database/models.py`                                     | Imports/re-exports all current models so their tables and relationship names are registered before Alembic/ORM use; no network/DDL side effect.                                                                                                                                                                                                               |
| `app/modules/__init__.py`, `auth/__init__.py`, `workflows/__init__.py`      | Package markers describing the implemented persistence boundaries.                                                                                                                                                                                                                                                                                            |
| `app/modules/auth/models.py`                                                | User mapping, typed `Mapped` fields, server defaults/checks, owned workflow and created-version relationships.                                                                                                                                                                                                                                                |
| `app/modules/workflows/models.py`                                           | WorkflowStatus with lowercase stored values; Workflow and WorkflowVersion mappings, composite FK, checks, history/current joins, unique keys/indexes.                                                                                                                                                                                                         |
| `alembic.ini`                                                               | Resolves migrations/import path relative to the config file; no URL or credentials stored/interpolated.                                                                                                                                                                                                                                                       |
| `migrations/env.py`                                                         | Registers metadata and configures type/default comparison. `migrate(connection)` runs Alembic inside its transaction. Online commands use validated settings/Database or an explicitly supplied Connection for tests. Offline mode needs only the PostgreSQL dialect. Standalone SQLAlchemy failures become a static error instead of echoing driver details. |
| `migrations/script.py.mako`                                                 | Template for future revision files; every generated migration still needs review.                                                                                                                                                                                                                                                                             |
| `migrations/versions/0001_users_workflows_versions.py`                      | Frozen revision-specific upgrade/downgrade, explicit creation/removal order and PostgreSQL functions/triggers. It does not import changing application models to define historical DDL.                                                                                                                                                                       |
| `tests/integration/conftest.py`                                             | Adds random test schemas and supplies their connection to Alembic, without private dotenv or development URL. Each fixture rolls back, restores public search_path, and drops its own schema in finally.                                                                                                                                                      |
| `tests/integration/test_migrations.py`                                      | Empty upgrade, populated downgrade, re-upgrade, revision check, ORM drift check, helper cleanup, index/FK inspection.                                                                                                                                                                                                                                         |
| `tests/integration/test_models.py`                                          | Real ORM relationships/defaults, normalized unique emails, owner/status/name checks, version uniqueness/JSON/schema/FKs, same-workflow pointer, immutability, restrictive deletion, preserved old snapshots, timestamps.                                                                                                                                      |
| `tests/unit/test_orm_metadata.py`                                           | Configures all mappers without ambiguous joins and renders offline migration SQL without a database URL, checking table/FK dependency order.                                                                                                                                                                                                                  |
| `pyproject.toml`, `uv.lock`, `scripts/check.py`                             | Add Alembic, lock dependencies, and include migration Python files in Ruff/Pyright checks.                                                                                                                                                                                                                                                                    |
| Guides, schema/ER/architecture status, implementation plan, development log | Actual scope, migration commands, evidence, and next increment.                                                                                                                                                                                                                                                                                               |

## Run migrations and checks

Alembic **1.20.1**, Mako **1.4.3**, and MarkupSafe **3.0.4** were added; existing runtime versions remain unchanged. Alembic is a direct dependency because schema management is a deployment operation, not just a test utility. See the [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

From the repository root, after starting the development PostgreSQL service:

```bash
uv sync --directory backend --locked

# Requires AGENTFLOW_DATABASE_URL in your private backend .env or process environment:
uv run --directory backend --locked alembic upgrade head
uv run --directory backend --locked alembic current
uv run --directory backend --locked alembic check

# Offline SQL generation needs neither a database nor a URL:
uv run --directory backend --locked alembic upgrade head --sql

# Ordinary checks (database cases explicitly skipped):
uv run --directory backend --locked python scripts/check.py

# Dedicated real PostgreSQL tests:
docker compose --profile test up -d --wait postgres_test
TEST_DATABASE_URL='postgresql+psycopg://agentflow_test:agentflow_test_local@127.0.0.1:15433/agentflow_test' \
  uv run --directory backend --locked python scripts/check.py --integration
```

The test URL guard still rejects development databases, non-local hosts, and query overrides. Migrations/tests operate inside random schemas with a supplied connection; this is test isolation, not a multi-tenant product feature. The shared public test schema remains empty. Tests do not require the development database to be empty or downgrade it. Connection sharing follows [Alembic's documented pattern](https://alembic.sqlalchemy.org/en/latest/cookbook.html#sharing-a-connection-across-one-or-more-programmatic-migration-commands).

`alembic check` compares ORM table/column/FK/index/default metadata with the database. It does not prove trigger bodies or all check-constraint behavior match: the explicit mutation/constraint tests cover those. Offline SQL is a review artifact, not proof the database executed it.

## Actual verification and limits

On 30 October 2026, **90 tests passed with PostgreSQL**, including 29 new cases beyond Phase 2A. Ordinary checks report **55 passed, 35 skipped**. Ruff lint/format passed for 42 Python files; Pyright reported zero errors/warnings. Both upgrade and re-upgrade had no ORM drift. Downgrade was tested with populated circular references and removed helper functions correctly.

The confirmed-empty development database was upgraded to revision **0001**, `alembic current` showed head, and `alembic check` reported no new upgrade operations. All three application tables remained empty: no real account or workflow was seeded. The pre-existing development PostgreSQL service was left running. Only the verification test container was stopped/removed; its temporary data and random schemas were discarded. Private `.env`, frontend/build assets, and legacy drafts were untouched.

Initial lint/type feedback found long SQL strings and an optional reflected-FK metadata key; both were corrected without broad suppressions. Existing API/configuration/lifecycle tests remain green. No live browser/model/worker behavior, authentication/password security, executable workflow correctness, or repository concurrency result is claimed.

## Review questions

Discuss one at a time:

1. Why would a foreign key on current_version_id alone allow the wrong workflow's version?
2. Why does the version table need a unique key on workflow_id and id even though id is already a primary key?
3. What is the difference between flush and commit during initial workflow creation?
4. Why does an immutable snapshot need a database guard as well as application rules?
5. What does alembic check fail to verify about custom triggers?

## Independent exercise and next increment

Write a PostgreSQL integration test showing that two different workflows may each have version_number 1, while inserting another version_number 1 for the same workflow fails. Use the existing random-schema fixtures and do not edit the development database. No solution is included.

Phase 2C is now complete: see [repositories and transaction contexts](repositories.md). Next is Phase 3A, registration and Argon2 password hashing.
