# ADR-003 — Deterministic outer engine, LangGraph agent nodes

Status: proposed in Phase 0, 30 October 2026.

**Decision:** the application owns DAG validation, version selection, node scheduling, legal state transitions, attempts, cancellation and approvals. Celery transports durable work after Phase 5 proves execution semantics. LangGraph runs inside registered agent nodes and owns their internal tool loop/checkpoints.

**Reason:** deterministic workflow routing should remain predictable, auditable and testable without a model. Agent iteration is a bounded capability inside that workflow. Job transport, business state and agent state have distinct lifecycles.

**Alternatives:** using LangGraph as the entire application execution database or treating Celery result states as the workflow state couples the UI/history to infrastructure and obscures approvals/version invariants. Retaining browser/process-only execution cannot provide durable recovery.

**Consequences:** PostgreSQL persists application run/attempt/event state; LangGraph checkpoints are isolated and correlated by explicit IDs. Use outbox dispatch, duplicate-safe claims and recovery tests. Promise at-least-once delivery with idempotency/reconciliation, not exactly-once external side effects. Approval waiting releases workers and resumes through a committed decision and outbox entry.
