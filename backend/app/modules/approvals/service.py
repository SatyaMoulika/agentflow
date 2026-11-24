"""Run-row serialized approval decisions and expiry; never execute nodes here."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.database.session import Database
from app.modules.approvals.models import Approval
from app.modules.approvals.schemas import (
    ApprovalDecision,
    ApprovalDetail,
    ApprovalPage,
    ApprovalResponse,
    ApprovalStatus,
)
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.exceptions import ExecutionConflictError, ExecutionNotFoundError
from app.modules.executions.models import NodeRun, WorkflowRun
from app.modules.executions.payloads import copy_payload
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import EventType, FailureCode, NodeStatus, RunStatus
from app.modules.outbox.models import OutboxMessage
from app.modules.outbox.repository import OutboxRepository
from app.modules.workflows.models import Workflow


def cancel_pending(session: Session, run: WorkflowRun) -> None:
    """Caller holds the owned run lock and owns cancellation plus its events."""
    for row in session.scalars(
        select(Approval).where(
            Approval.workflow_run_id == run.id,
            Approval.status == "pending",
        )
    ):
        row.status = "cancelled"
        resolved_at = session.scalar(select(func.clock_timestamp()))
        assert resolved_at is not None
        row.resolved_at = resolved_at
        session.flush()
        ExecutionRepository(session)._event(
            run,
            EventType.APPROVAL_RESOLVED,
            {"approval_id": str(row.id), "status": row.status},
            row.node_run_id,
        )


class ApprovalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(
        self,
        owner_id: UUID,
        *,
        status: ApprovalStatus | None = "pending",
        run_id: UUID | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> ApprovalPage:
        query = (
            select(Approval)
            .join(WorkflowRun, WorkflowRun.id == Approval.workflow_run_id)
            .join(
                Workflow,
                Workflow.id == WorkflowRun.workflow_id,
            )
            .where(Approval.assigned_to == owner_id, Workflow.owner_id == owner_id)
        )
        if status is not None:
            query = query.where(Approval.status == status)
        if run_id is not None:
            query = query.where(Approval.workflow_run_id == run_id)
        with self.database.session() as session:
            total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
            rows = session.scalars(
                query.order_by(Approval.created_at.desc(), Approval.id.desc())
                .offset(
                    (page - 1) * page_size,
                )
                .limit(page_size)
            )
            return ApprovalPage(
                items=[ApprovalResponse.model_validate(row) for row in rows],
                total=total,
                page=page,
                page_size=page_size,
            )

    @staticmethod
    def _lock(
        session: Session, owner_id: UUID, approval_id: UUID
    ) -> tuple[
        ExecutionRepository,
        WorkflowRun,
        Approval,
        NodeRun,
    ]:
        row = session.get(Approval, approval_id)
        if row is None or row.assigned_to != owner_id:
            raise ExecutionNotFoundError()
        repository = ExecutionRepository(session)
        run = repository.lock_owned(run_id=row.workflow_run_id, owner_id=owner_id)
        session.refresh(row)  # The run lock serializes decisions, expiry and cancellation.
        attempt = session.get(NodeRun, row.node_run_id)
        if attempt is None or attempt.workflow_run_id != run.id:
            raise ExecutionConflictError()
        return repository, run, row, attempt

    def get(self, owner_id: UUID, approval_id: UUID) -> ApprovalDetail:
        with self.database.session() as session:
            _, _, row, attempt = self._lock(session, owner_id, approval_id)
            return ApprovalDetail(
                **ApprovalResponse.model_validate(row).model_dump(),
                input=copy_payload(attempt.input_json),
            )

    @staticmethod
    def _resolve(
        session: Session,
        repository: ExecutionRepository,
        run: WorkflowRun,
        row: Approval,
        attempt: NodeRun,
        status: str,
        note: str | None = None,
    ) -> None:
        if (
            row.status != "pending"
            or run.status != RunStatus.WAITING_APPROVAL
            or attempt.status != NodeStatus.WAITING_APPROVAL
        ):
            raise ExecutionConflictError()
        dispatch = session.get(WorkflowDispatch, run.id)
        if dispatch is None:
            raise ExecutionConflictError()
        row.status, row.note = status, note
        resolved_at = session.scalar(select(func.clock_timestamp()))
        assert resolved_at is not None
        row.resolved_at = resolved_at
        session.flush()
        repository.transition_attempt(
            run_id=run.id,
            owner_id=row.assigned_to,
            attempt_id=attempt.id,
            expected_run_revision=run.revision,
            expected_revision=attempt.revision,
            target=NodeStatus.FAILED if status == "expired" else NodeStatus.SUCCEEDED,
            error_code=FailureCode.DEADLINE_EXCEEDED if status == "expired" else None,
            output=None if status == "expired" else {"decision": status},
        )
        repository._event(
            run,
            EventType.APPROVAL_RESOLVED,
            {"approval_id": str(row.id), "status": status},
            attempt.id,
        )
        repository.transition_run(
            run_id=run.id,
            owner_id=row.assigned_to,
            expected_revision=run.revision,
            target=RunStatus.FAILED if status == "expired" else RunStatus.RUNNING,
            error_code=FailureCode.DEADLINE_EXCEEDED if status == "expired" else None,
        )
        if status != "expired":
            # A decision and its delivery intent commit together. An unpublished original
            # delivery may still exist if the worker beat publisher acknowledgement.
            pending = session.scalar(
                select(OutboxMessage.id)
                .where(
                    OutboxMessage.workflow_run_id == run.id,
                    OutboxMessage.published_at.is_(None),
                )
                .limit(1)
            )
            if pending is None:
                OutboxRepository(session).enqueue_workflow(run.id)
            dispatch.next_dispatch_at = resolved_at

    def decide(self, owner_id: UUID, approval_id: UUID, data: ApprovalDecision) -> ApprovalResponse:
        with self.database.unit_of_work() as session:
            repository, run, row, attempt = self._lock(session, owner_id, approval_id)
            if row.status != "pending":
                if row.status == data.decision and row.note == data.note:
                    return ApprovalResponse.model_validate(row)
                raise ExecutionConflictError()
            now = session.scalar(select(func.clock_timestamp()))
            assert now is not None
            if now >= row.expires_at:
                self._resolve(session, repository, run, row, attempt, "expired")
            else:
                self._resolve(session, repository, run, row, attempt, data.decision, data.note)
            return ApprovalResponse.model_validate(row)

    def expire_due(self, *, limit: int = 20) -> int:
        with self.database.session() as session:
            candidates = list(
                session.execute(
                    select(Approval.id, Approval.assigned_to)
                    .where(
                        Approval.status == "pending",
                        Approval.expires_at <= func.clock_timestamp(),
                    )
                    .order_by(Approval.expires_at, Approval.id)
                    .limit(limit)
                )
            )
        expired = 0
        for approval_id, owner_id in candidates:
            with self.database.unit_of_work() as session:
                repository, run, row, attempt = self._lock(session, owner_id, approval_id)
                now = session.scalar(select(func.clock_timestamp()))
                if row.status == "pending" and now is not None and now >= row.expires_at:
                    self._resolve(session, repository, run, row, attempt, "expired")
                    expired += 1
        return expired
