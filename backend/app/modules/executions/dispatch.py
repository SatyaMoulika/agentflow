"""Schedule retained opaque-ID deliveries; never execute nodes or call the broker here."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import RunClaim, WorkflowRun
from app.infrastructure.database.session import Database
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.retry_models import NodeRetry
from app.modules.executions.state import RunStatus
from app.modules.outbox.models import OutboxMessage
from app.modules.outbox.repository import OutboxRepository


def enqueue_run(
    session: Session,
    run_id: UUID,
    *,
    redelivery_seconds: int = 30,
    retry_base_seconds: int = 5,
    retry_max_seconds: int = 60,
) -> None:
    """Caller owns the fresh run, event, command receipt and intent in one transaction."""
    now = session.scalar(select(func.clock_timestamp()))
    assert now is not None
    session.add(
        WorkflowDispatch(
            run_id=run_id,
            next_dispatch_at=now + timedelta(seconds=redelivery_seconds),
            retry_base_seconds=retry_base_seconds,
            retry_max_seconds=retry_max_seconds,
        )
    )
    session.flush()
    OutboxRepository(session).enqueue_workflow(run_id)


def schedule_recovery(database: Database, *, limit: int = 20, redelivery_seconds: int = 30) -> int:
    """Rediscover only worker-owned unfinished runs without a live lease/pending intent.

    Lock order matches workers: run first. Recheck the lease under that lock because
    a candidate query's earlier statement snapshot is not a fencing decision.
    Published outbox rows remain immutable; each redispatch creates another row.
    """
    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(redelivery_seconds) is not int
        or not 5 <= redelivery_seconds <= 3600
    ):
        raise ValueError("Invalid recovery scheduling bounds")
    pending = exists().where(
        OutboxMessage.workflow_run_id == WorkflowRun.id,
        OutboxMessage.published_at.is_(None),
    )
    not_due = exists().where(
        NodeRetry.workflow_run_id == WorkflowRun.id,
        NodeRetry.resumed_at.is_(None),
        NodeRetry.cancelled_at.is_(None),
        NodeRetry.due_at > func.clock_timestamp(),
    )
    with database.unit_of_work() as session:
        rows = session.execute(
            select(WorkflowRun, WorkflowDispatch)
            .join(WorkflowDispatch, WorkflowDispatch.run_id == WorkflowRun.id)
            .outerjoin(RunClaim, RunClaim.run_id == WorkflowRun.id)
            .where(
                WorkflowRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
                WorkflowDispatch.next_dispatch_at <= func.clock_timestamp(),
                or_(RunClaim.lease_until.is_(None), RunClaim.lease_until <= func.clock_timestamp()),
                ~pending,
                ~not_due,
            )
            .order_by(WorkflowDispatch.next_dispatch_at, WorkflowRun.id)
            .limit(limit)
            .with_for_update(of=WorkflowRun, skip_locked=True)
            .execution_options(populate_existing=True)
        ).all()
        scheduled = 0
        for run, delivery in rows:
            slot = session.get(RunClaim, run.id, populate_existing=True)
            now = session.scalar(select(func.clock_timestamp()))
            assert now is not None
            if slot is not None and slot.lease_until is not None and slot.lease_until > now:
                continue
            if session.scalar(
                select(
                    exists().where(
                        NodeRetry.workflow_run_id == run.id,
                        NodeRetry.resumed_at.is_(None),
                        NodeRetry.cancelled_at.is_(None),
                        NodeRetry.due_at > now,
                    )
                )
            ):
                continue
            if session.scalar(
                select(
                    exists().where(
                        OutboxMessage.workflow_run_id == run.id,
                        OutboxMessage.published_at.is_(None),
                    )
                )
            ):
                continue
            OutboxRepository(session).enqueue_workflow(run.id)
            delivery.dispatch_count += 1
            delivery.next_dispatch_at = now + timedelta(seconds=redelivery_seconds)
            scheduled += 1
        return scheduled
