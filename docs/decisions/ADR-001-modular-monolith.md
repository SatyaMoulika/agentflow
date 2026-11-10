# ADR-001 — Modular monolith

Status: proposed in Phase 0, 30 October 2026.

**Decision:** one Python codebase with module ownership and router → service → domain/repository boundaries. Run FastAPI and Celery as separate processes from that codebase. Introduce infrastructure only when a phase needs it.

**Reason:** the product needs durable background execution without the deployment/versioning overhead of independently owned microservices. A pure domain engine remains testable without HTTP, ORM, broker or model services.

**Alternatives:** a single oversized FastAPI file tangles business logic and persistence; microservices add network consistency and operational work before there is a demonstrated need. Neither is the chosen MVP structure.

**Consequences:** a single deployment/schema must preserve module boundaries by code review and tests. No generic repository framework or empty directory/class hierarchy is created preemptively. Worker messages contain IDs/correlation, not live sessions or ORM objects.
