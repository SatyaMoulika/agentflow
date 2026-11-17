"""Consume only stored delivery IDs; ownership and business data come from PostgreSQL."""

import logging
from uuid import UUID

from sqlalchemy import select

from app.core.tracing import parent_trace, span
from app.infrastructure.database.models import User, Workflow, WorkflowDispatch, WorkflowRun
from app.infrastructure.database.session import Database
from app.modules.claims.repository import ClaimLostError
from app.modules.executions.worker_runner import PureWorkerRunner
from app.modules.outbox.models import OutboxMessage

logger = logging.getLogger("agentflow.worker.workflow")


def consume_workflow(database: Database, message_id: str, *, lease_seconds: int = 30) -> None:
    try:
        identifier = UUID(message_id)
        if str(identifier) != message_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        logger.warning("Workflow delivery has an invalid identifier")
        return
    try:
        with database.session() as session:
            target = session.execute(
                select(WorkflowRun.id, Workflow.owner_id, WorkflowDispatch.traceparent)
                .select_from(OutboxMessage)
                .join(WorkflowDispatch, OutboxMessage.workflow_run_id == WorkflowDispatch.run_id)
                .join(WorkflowRun, WorkflowRun.id == WorkflowDispatch.run_id)
                .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
                .join(User, User.id == Workflow.owner_id)
                .where(
                    OutboxMessage.id == identifier,
                    OutboxMessage.kind == "workflow_run",
                    User.is_active.is_(True),
                )
            ).one_or_none()
        if target is None:
            logger.warning("Workflow delivery has no eligible target")
            return
        with parent_trace(target.traceparent), span("agentflow.worker_delivery"):
            handled = PureWorkerRunner(
                database,
                lease_seconds=lease_seconds,
                heartbeat=True,
                require_dispatch=True,
            ).run(run_id=target.id, owner_id=target.owner_id)
        logger.info(
            "Workflow delivery processed"
            if handled
            else "Workflow delivery deferred or already handled"
        )
    except ClaimLostError:
        logger.info("Workflow delivery lost its claim")
    except Exception:
        # The durable scheduler will rediscover unfinished work. Never let Celery
        # serialize/log exception text, database parameters or business payloads.
        logger.warning("Workflow delivery stopped; retained state requires recovery")
