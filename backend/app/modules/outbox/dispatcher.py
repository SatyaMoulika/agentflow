"""Publish outside DB transactions; broker acceptance can precede a crash/duplicate."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.tracing import parent_trace, span, traced
from app.infrastructure.database.session import Database
from app.modules.outbox.repository import OutboxRepository


@dataclass(frozen=True)
class DispatchResult:
    claimed: int
    published: int
    failed: int
    stale: int


class OutboxDispatcher:
    def __init__(
        self,
        database: Database,
        publish: Callable[[UUID], None],
        *,
        publish_workflow: Callable[[UUID], None] | None = None,
    ) -> None:
        self.database = database
        self.publish = publish
        self.publish_workflow = publish_workflow

    @traced("agentflow.outbox_dispatch")
    def dispatch_once(self, *, limit: int = 20, lease_seconds: int = 30) -> DispatchResult:
        with self.database.unit_of_work() as session:
            claims = OutboxRepository(session).claim(limit=limit, lease_seconds=lease_seconds)
        published = failed = stale = 0
        for claim in claims:
            try:
                if claim.kind == "workflow_run":
                    if self.publish_workflow is None:
                        raise ValueError("No workflow publisher configured")
                    with parent_trace(claim.traceparent), span("agentflow.outbox_publish"):
                        self.publish_workflow(claim.id)
                else:
                    self.publish(claim.id)
            except Exception:
                # The broker may have accepted a message despite a lost response.
                # Releasing the lease makes redelivery possible, never exactly-once.
                with self.database.unit_of_work() as session:
                    released = OutboxRepository(session).release(claim)
                failed += 1
                stale += int(not released)
                continue
            with self.database.unit_of_work() as session:
                marked = OutboxRepository(session).mark_published(claim)
            published += int(marked)
            stale += int(not marked)
        return DispatchResult(len(claims), published, failed, stale)
