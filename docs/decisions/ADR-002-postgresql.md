# ADR-002 — PostgreSQL and Alembic

Status: proposed in Phase 0, 30 October 2026.

**Decision:** PostgreSQL is the application source of truth, accessed through SQLAlchemy 2.x and migrated through Alembic. Normalize entities/relationships; use JSONB for versioned definitions and variable inputs/outputs. Test integration behavior on PostgreSQL.

**Reason:** ownership, version integrity, transactional run/event/outbox writes and concurrent approvals need real relational constraints and transactions. The earlier SQLite/JSON drafts do not meet the requested architecture and will not be extended as production persistence.

**Alternatives:** retaining SQLite temporarily reduces setup but tests different locking/JSON/constraint behavior; storing all objects in generic JSON rows sacrifices useful relational constraints. Neither is selected.

**Consequences:** PostgreSQL must be available for database integration tests. Every schema change is a migration; no production `create_all()` path. The circular current-version pointer has explicit creation/FK order. Version saves are append-only. Transaction boundaries belong to application services, not routers or auto-committing repositories.
