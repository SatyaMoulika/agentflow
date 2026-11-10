"""Owner-scoped persistence; caller owns the transaction, every mutation appends an event."""

import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import (
    ExecutionEvent,
    NodeRun,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
)
from app.modules.agents.schemas import AgentMetadata
from app.modules.executions.exceptions import (
    ExecutionConflictError,
    ExecutionNotFoundError,
    InvalidExecutionDataError,
)
from app.modules.executions.payloads import copy_payload
from app.modules.executions.provider_schemas import ProviderMetadata
from app.modules.executions.state import (
    NODE_TERMINAL,
    RUN_TERMINAL,
    EventType,
    FailureCode,
    NodeStatus,
    RunStatus,
    require_node_transition,
    require_run_transition,
)
from app.modules.workflows.models import WorkflowStatus
from app.modules.workflows.node_configs import NODE_ID_PATTERN
from app.modules.workflows.repository import WorkflowRepository


def _check_revision(actual: int, expected: int) -> None:
    if type(expected) is not int or expected < 0 or actual != expected:
        raise ExecutionConflictError()


def _result_data(
    target: RunStatus | NodeStatus,
    output: object,
    error_code: FailureCode | None,
) -> dict[str, Any] | None:
    if target.value == "succeeded":
        if error_code is not None or not isinstance(output, dict):
            raise InvalidExecutionDataError()
        return copy_payload(output)
    if (
        output is not None
        or (target.value == "failed" and not isinstance(error_code, FailureCode))
        or (target.value != "failed" and error_code is not None)
    ):
        raise InvalidExecutionDataError()
    return None


class ExecutionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_owned(self, *, run_id: UUID, owner_id: UUID) -> WorkflowRun | None:
        return self.session.scalar(
            select(WorkflowRun)
            .join(
                Workflow,
                WorkflowRun.workflow_id == Workflow.id,
            )
            .where(WorkflowRun.id == run_id, Workflow.owner_id == owner_id)
        )

    def lock_owned(self, *, run_id: UUID, owner_id: UUID) -> WorkflowRun:
        self.session.flush()
        run = self.session.scalar(
            select(WorkflowRun)
            .join(
                Workflow,
                WorkflowRun.workflow_id == Workflow.id,
            )
            .where(WorkflowRun.id == run_id, Workflow.owner_id == owner_id)
            .with_for_update(of=WorkflowRun)
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise ExecutionNotFoundError()
        return run

    def _event(
        self,
        run: WorkflowRun,
        event_type: EventType,
        payload: dict[str, Any],
        node_run_id: UUID | None = None,
    ) -> ExecutionEvent:
        """Caller holds the run lock; escaping failure must roll back the whole unit of work."""
        run.event_sequence += 1
        self.session.flush()
        event = ExecutionEvent(
            workflow_run_id=run.id,
            node_run_id=node_run_id,
            sequence=run.event_sequence,
            event_type=event_type,
            event_payload=payload,
        )
        self.session.add(event)
        self.session.flush()
        self.session.expire(run, ["events", "updated_at"])
        return event

    def create_run(
        self,
        *,
        workflow_id: UUID,
        version_id: UUID,
        owner_id: UUID,
        input_json: dict[str, Any],
        parent_run_id: UUID | None = None,
        max_attempts: int = 1,
    ) -> WorkflowRun:
        workflows = WorkflowRepository(self.session)
        workflow = workflows.lock_owned(workflow_id=workflow_id, owner_id=owner_id)
        if (
            workflow is None
            or workflows.get_version_owned(
                workflow_id=workflow_id,
                version_id=version_id,
                owner_id=owner_id,
            )
            is None
        ):
            raise ExecutionNotFoundError()
        if workflow.status == WorkflowStatus.ARCHIVED:
            raise ExecutionConflictError()
        if parent_run_id is not None:
            parent = self.get_owned(run_id=parent_run_id, owner_id=owner_id)
            if parent is None or (parent.workflow_id, parent.workflow_version_id) != (
                workflow_id,
                version_id,
            ):
                raise ExecutionNotFoundError()
        run = WorkflowRun(
            workflow_id=workflow_id,
            workflow_version_id=version_id,
            parent_run_id=parent_run_id,
            max_attempts=max_attempts,
            input_json=copy_payload(input_json),
        )
        self.session.add(run)
        self.session.flush()
        self._event(run, EventType.RUN_CREATED, {"status": run.status.value})
        return run

    def _latest_attempts(self, run_id: UUID) -> list[NodeRun]:
        return list(
            self.session.scalars(
                select(NodeRun)
                .where(NodeRun.workflow_run_id == run_id)
                .distinct(NodeRun.node_id)
                .order_by(NodeRun.node_id, NodeRun.attempt_number.desc())
                .execution_options(populate_existing=True)
            )
        )

    def _version_nodes(self, run: WorkflowRun) -> list[dict[str, Any]]:
        version = self.session.get(WorkflowVersion, run.workflow_version_id)
        if version is None:
            raise ExecutionNotFoundError()
        nodes = version.definition_json.get("nodes")
        return [node for node in nodes if isinstance(node, dict)] if isinstance(nodes, list) else []

    def transition_run(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        expected_revision: int,
        target: RunStatus,
        output: dict[str, Any] | None = None,
        error_code: FailureCode | None = None,
    ) -> WorkflowRun:
        run = self.lock_owned(run_id=run_id, owner_id=owner_id)
        _check_revision(run.revision, expected_revision)
        require_run_transition(run.status, target)
        result = _result_data(target, output, error_code)
        latest = self._latest_attempts(run.id)
        if target in RUN_TERMINAL and any(row.status not in NODE_TERMINAL for row in latest):
            raise ExecutionConflictError()
        if target == RunStatus.SUCCEEDED:
            ends = {
                node.get("id")
                for node in self._version_nodes(run)
                if node.get("type") == "end" and isinstance(node.get("id"), str)
            }
            if not any(
                row.node_id in ends and row.status == NodeStatus.SUCCEEDED for row in latest
            ) or any(
                row.status not in {NodeStatus.SUCCEEDED, NodeStatus.SKIPPED} for row in latest
            ):
                raise ExecutionConflictError()
        if target == RunStatus.WAITING_APPROVAL and (
            not any(row.status == NodeStatus.WAITING_APPROVAL for row in latest)
            or any(row.status == NodeStatus.RUNNING for row in latest)
        ):
            raise ExecutionConflictError()
        previous = run.status
        now = self.session.scalar(select(func.clock_timestamp()))
        assert now is not None
        if run.started_at is None and target == RunStatus.RUNNING:
            run.started_at = now
        if target in RUN_TERMINAL:
            run.completed_at = now
        run.status, run.revision = target, run.revision + 1
        run.output_json, run.error_code = result, error_code
        self.session.flush()
        self._event(
            run,
            EventType.RUN_STATUS_CHANGED,
            {"from_status": previous.value, "to_status": target.value},
        )
        return run

    def add_attempt(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        expected_run_revision: int,
        node_id: str,
        input_json: dict[str, Any],
    ) -> NodeRun:
        run = self.lock_owned(run_id=run_id, owner_id=owner_id)
        _check_revision(run.revision, expected_run_revision)
        if run.status != RunStatus.RUNNING:
            raise ExecutionConflictError()
        if (
            not isinstance(node_id, str)
            or re.fullmatch(NODE_ID_PATTERN, node_id) is None
            or not any(node.get("id") == node_id for node in self._version_nodes(run))
        ):
            raise ExecutionNotFoundError()
        latest = self.session.scalar(
            select(NodeRun)
            .where(
                NodeRun.workflow_run_id == run_id,
                NodeRun.node_id == node_id,
            )
            .order_by(NodeRun.attempt_number.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if latest is not None and latest.status != NodeStatus.FAILED:
            raise ExecutionConflictError()
        attempt = NodeRun(
            workflow_run_id=run.id,
            node_id=node_id,
            attempt_number=1 if latest is None else latest.attempt_number + 1,
            input_json=copy_payload(input_json),
        )
        self.session.add(attempt)
        self.session.flush()
        self.session.expire(run, ["attempts"])
        self._event(
            run,
            EventType.NODE_CREATED,
            {
                "node_id": node_id,
                "attempt_number": attempt.attempt_number,
                "status": "pending",
            },
            attempt.id,
        )
        return attempt

    def transition_attempt(
        self,
        *,
        run_id: UUID,
        attempt_id: UUID,
        owner_id: UUID,
        expected_run_revision: int,
        expected_revision: int,
        target: NodeStatus,
        output: dict[str, Any] | None = None,
        error_code: FailureCode | None = None,
        provider_metadata: dict[str, Any] | None = None,
        agent_metadata: dict[str, Any] | None = None,
    ) -> NodeRun:
        run = self.lock_owned(run_id=run_id, owner_id=owner_id)
        _check_revision(run.revision, expected_run_revision)
        if run.status not in {RunStatus.RUNNING, RunStatus.WAITING_APPROVAL}:
            raise ExecutionConflictError()
        attempt = self.session.scalar(
            select(NodeRun)
            .where(
                NodeRun.workflow_run_id == run_id,
                NodeRun.id == attempt_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None:
            raise ExecutionNotFoundError()
        _check_revision(attempt.revision, expected_revision)
        require_node_transition(attempt.status, target)
        result = _result_data(target, output, error_code)
        provider = None
        if provider_metadata is not None:
            if target not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
                raise InvalidExecutionDataError()
            try:
                detail = ProviderMetadata.model_validate(provider_metadata)
            except ValidationError:
                raise InvalidExecutionDataError() from None
            if detail.error_code is not None and detail.error_code != error_code:
                raise InvalidExecutionDataError()
            provider = detail.model_dump(exclude_none=True)
        agent = None
        if agent_metadata is not None:
            if target not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
                raise InvalidExecutionDataError()
            try:
                agent_detail = AgentMetadata.model_validate(agent_metadata)
            except ValidationError:
                raise InvalidExecutionDataError() from None
            if (agent_detail.failure_reason is not None) != (target == NodeStatus.FAILED):
                raise InvalidExecutionDataError()
            agent = agent_detail.model_dump(exclude_none=True)
        previous = attempt.status
        now = self.session.scalar(select(func.clock_timestamp()))
        assert now is not None
        if attempt.started_at is None and target == NodeStatus.RUNNING:
            attempt.started_at = now
        if target in NODE_TERMINAL:
            attempt.completed_at = now
            attempt.duration_ms = (
                max(0, int((now - attempt.started_at).total_seconds() * 1000))
                if attempt.started_at is not None
                else 0
            )
        attempt.status, attempt.revision = target, attempt.revision + 1
        attempt.output_json, attempt.error_code = result, error_code
        self.session.flush()
        self._event(
            run,
            EventType.NODE_STATUS_CHANGED,
            {
                "from_status": previous.value,
                "to_status": target.value,
                **({"provider": provider} if provider is not None else {}),
                **({"agent": agent} if agent is not None else {}),
            },
            attempt.id,
        )
        return attempt

    def events_owned(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[ExecutionEvent]:
        if (
            type(after_sequence) is not int
            or after_sequence < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError("Invalid event cursor or page size")
        if self.get_owned(run_id=run_id, owner_id=owner_id) is None:
            raise ExecutionNotFoundError()
        return list(
            self.session.scalars(
                select(ExecutionEvent)
                .where(
                    ExecutionEvent.workflow_run_id == run_id,
                    ExecutionEvent.sequence > after_sequence,
                )
                .order_by(ExecutionEvent.sequence)
                .limit(limit)
            )
        )
