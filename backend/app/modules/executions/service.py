"""Authorize and compile exact saved versions, then persist and execute pure runs."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import case, exists, func, select, update
from sqlalchemy.exc import OperationalError, TimeoutError

from app.core.config import Settings
from app.infrastructure.database.models import (
    ExecutionEvent,
    NodeRun,
    RunCommand,
    User,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
)
from app.infrastructure.database.session import Database
from app.modules.agents.schemas import AgentMetadata
from app.modules.executions.commands import key_digest, request_digest
from app.modules.executions.dispatch import enqueue_run
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.exceptions import (
    ExecutionConflictError,
    ExecutionNotFoundError,
    ExecutionStorageUnavailableError,
    WorkflowNotExecutableError,
)
from app.modules.executions.provider_schemas import ProviderMetadata
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.retry_models import NodeRetry
from app.modules.executions.runner import RETRY_SAFE_TYPES, WorkflowRunner
from app.modules.executions.schemas import (
    ExecutionEventPage,
    ExecutionEventResponse,
    NodeAttemptResponse,
    RetryScheduleResponse,
    RunCreateRequest,
    RunListItem,
    RunListParams,
    RunPage,
    RunResponse,
    RunSummary,
)
from app.modules.executions.state import (
    NODE_TERMINAL,
    RUN_TERMINAL,
    EventType,
    NodeStatus,
    RunStatus,
)
from app.modules.workflows.compiler import compile_workflow
from app.modules.workflows.exceptions import WorkflowNotFoundError
from app.modules.workflows.node_registry import EXECUTION_READY_TYPES
from app.modules.workflows.repository import WorkflowRepository
from app.modules.workflows.schemas import WorkflowVersionResponse


class ExecutionService:
    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings

    def events(
        self, *, run_id: UUID, owner_id: UUID, after_sequence: int, limit: int
    ) -> ExecutionEventPage:
        try:
            with self.database.session() as session:
                events = ExecutionRepository(session).events_owned(
                    run_id=run_id, owner_id=owner_id, after_sequence=after_sequence, limit=limit
                )
                items = [ExecutionEventResponse.model_validate(event) for event in events]
                return ExecutionEventPage(
                    items=items,
                    next_after_sequence=items[-1].sequence if items else after_sequence,
                )
        except (OperationalError, TimeoutError):
            raise ExecutionStorageUnavailableError() from None

    def list(self, *, owner_id: UUID, params: RunListParams) -> RunPage:
        terms = [Workflow.owner_id == owner_id]
        if params.status is not None:
            terms.append(WorkflowRun.status == params.status)
        if params.workflow_id is not None:
            terms.append(WorkflowRun.workflow_id == params.workflow_id)
        query = (
            select(
                WorkflowRun.id,
                WorkflowRun.workflow_id,
                WorkflowRun.workflow_version_id,
                Workflow.name.label("workflow_name"),
                WorkflowVersion.version_number,
                WorkflowRun.status,
                case(
                    (exists().where(WorkflowDispatch.run_id == WorkflowRun.id), "background"),
                    else_="synchronous",
                ).label("execution_mode"),
                WorkflowRun.error_code,
                WorkflowRun.created_at,
                WorkflowRun.started_at,
                WorkflowRun.completed_at,
            )
            .join(Workflow, WorkflowRun.workflow_id == Workflow.id)
            .join(WorkflowVersion, WorkflowRun.workflow_version_id == WorkflowVersion.id)
            .where(*terms)
        )
        try:
            with self.database.session() as session:
                total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
                rows = session.execute(
                    query.order_by(WorkflowRun.created_at.desc(), WorkflowRun.id.desc())
                    .offset((params.page - 1) * params.page_size)
                    .limit(params.page_size)
                ).mappings()
                return RunPage(
                    items=[RunListItem.model_validate(dict(row)) for row in rows],
                    total=total,
                    page=params.page,
                    page_size=params.page_size,
                )
        except (OperationalError, TimeoutError):
            raise ExecutionStorageUnavailableError() from None

    def create_and_execute(
        self,
        *,
        workflow_id: UUID,
        owner_id: UUID,
        data: RunCreateRequest,
        idempotency_key: str | None = None,
        parent_run_id: UUID | None = None,
    ) -> RunResponse:
        run_id = None
        key = key_digest(idempotency_key) if idempotency_key is not None else None
        fingerprint = request_digest(workflow_id, data, parent_run_id)
        try:
            if key is not None:
                with self.database.session() as session:
                    receipt = session.get(RunCommand, (owner_id, key))
                    if receipt is not None:
                        if receipt.request_digest != fingerprint:
                            raise ExecutionConflictError()
                        run_id = receipt.run_id
                if run_id is not None:
                    return self.get(run_id=run_id, owner_id=owner_id)
            with self.database.session() as session:
                version = WorkflowRepository(session).get_version_owned(
                    workflow_id=workflow_id,
                    version_id=data.workflow_version_id,
                    owner_id=owner_id,
                )
                if version is None:
                    raise WorkflowNotFoundError()
                definition = deepcopy(version.definition_json)
            # Compilation and pure execution never hold a database transaction open.
            compiled = compile_workflow(definition)
            plan = compiled.plan
            if plan is None or any(node.type not in EXECUTION_READY_TYPES for node in plan.nodes):
                raise WorkflowNotExecutableError()
            if parent_run_id is not None and any(
                node.type not in RETRY_SAFE_TYPES for node in plan.nodes
            ):
                raise WorkflowNotExecutableError()
            background = (
                self.settings is not None
                and self.settings.background_execution_enabled
                and all(node.type in RETRY_SAFE_TYPES for node in plan.nodes)
            )
            with self.database.unit_of_work() as session:
                # Serialize command creation per owner, including keys used on different
                # workflows. Never hold this lock during compilation or computation.
                if (
                    session.scalar(select(User.id).where(User.id == owner_id).with_for_update())
                    is None
                ):
                    raise ExecutionNotFoundError()
                receipt = session.get(RunCommand, (owner_id, key)) if key is not None else None
                replay = receipt is not None
                if receipt is not None:
                    if receipt.request_digest != fingerprint:
                        raise ExecutionConflictError()
                    created_id = receipt.run_id
                else:
                    if parent_run_id is not None:
                        parent = ExecutionRepository(session).get_owned(
                            run_id=parent_run_id, owner_id=owner_id
                        )
                        if parent is None:
                            raise ExecutionNotFoundError()
                        if parent.status not in {RunStatus.FAILED, RunStatus.CANCELLED}:
                            raise ExecutionConflictError()
                    run = ExecutionRepository(session).create_run(
                        workflow_id=workflow_id,
                        version_id=data.workflow_version_id,
                        owner_id=owner_id,
                        input_json=data.input,
                        parent_run_id=parent_run_id,
                        max_attempts=data.max_attempts,
                    )
                    created_id = run.id
                    if background:
                        assert self.settings is not None
                        enqueue_run(
                            session,
                            run.id,
                            redelivery_seconds=self.settings.worker_redelivery_seconds,
                            retry_base_seconds=self.settings.worker_retry_base_seconds,
                            retry_max_seconds=self.settings.worker_retry_max_seconds,
                        )
                    if key is not None:
                        session.add(
                            RunCommand(
                                owner_id=owner_id,
                                key_digest=key,
                                request_digest=fingerprint,
                                run_id=created_id,
                            )
                        )
            run_id = created_id
            if not replay and not background:
                WorkflowRunner(self.database, self.settings).run(
                    run_id=run_id,
                    owner_id=owner_id,
                    plan=plan,
                    input_data=data.input,
                    max_attempts=data.max_attempts,
                )
            return self.get(run_id=run_id, owner_id=owner_id)
        except (OperationalError, TimeoutError):
            raise ExecutionStorageUnavailableError(run_id) from None

    def retry(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        max_attempts: int = 1,
        idempotency_key: str | None = None,
    ) -> RunResponse:
        original = self.get(run_id=run_id, owner_id=owner_id)
        if original.status not in {RunStatus.FAILED, RunStatus.CANCELLED}:
            raise ExecutionConflictError()
        return self.create_and_execute(
            workflow_id=original.workflow_id,
            owner_id=owner_id,
            data=RunCreateRequest(
                workflow_version_id=original.workflow_version_id,
                input=original.input,
                max_attempts=max_attempts,
            ),
            parent_run_id=run_id,
            idempotency_key=idempotency_key,
        )

    def cancel(self, *, run_id: UUID, owner_id: UUID) -> RunResponse:
        try:
            with self.database.unit_of_work() as session:
                repository = ExecutionRepository(session)
                run = repository.lock_owned(run_id=run_id, owner_id=owner_id)
                if run.status != RunStatus.CANCELLED:
                    if run.status in RUN_TERMINAL:
                        raise ExecutionConflictError()
                    attempts = session.scalars(
                        select(NodeRun)
                        .where(NodeRun.workflow_run_id == run_id)
                        .order_by(NodeRun.created_at, NodeRun.id)
                    ).all()
                    for attempt in attempts:
                        if attempt.status not in NODE_TERMINAL:
                            repository.transition_attempt(
                                run_id=run_id,
                                owner_id=owner_id,
                                attempt_id=attempt.id,
                                expected_run_revision=run.revision,
                                expected_revision=attempt.revision,
                                target=NodeStatus.CANCELLED,
                            )
                    repository.transition_run(
                        run_id=run_id,
                        owner_id=owner_id,
                        expected_revision=run.revision,
                        target=RunStatus.CANCELLED,
                    )
                    session.execute(
                        update(NodeRetry)
                        .where(
                            NodeRetry.workflow_run_id == run_id,
                            NodeRetry.resumed_at.is_(None),
                            NodeRetry.cancelled_at.is_(None),
                        )
                        .values(cancelled_at=func.clock_timestamp())
                    )
            return self.get(run_id=run_id, owner_id=owner_id)
        except (OperationalError, TimeoutError):
            raise ExecutionStorageUnavailableError(run_id) from None

    def get(self, *, run_id: UUID, owner_id: UUID) -> RunResponse:
        try:
            with self.database.session() as session:
                # A short owner-scoped run-row lock keeps run/attempt DTOs coherent
                # with cooperating writers even at READ COMMITTED isolation.
                run = ExecutionRepository(session).lock_owned(run_id=run_id, owner_id=owner_id)
                version = session.get(WorkflowVersion, run.workflow_version_id)
                assert version is not None
                attempts = session.scalars(
                    select(NodeRun)
                    .where(NodeRun.workflow_run_id == run_id)
                    .order_by(NodeRun.created_at, NodeRun.id)
                ).all()
                summary = RunSummary.model_validate(run).model_dump()
                summary["execution_mode"] = (
                    "background"
                    if session.get(WorkflowDispatch, run.id) is not None
                    else "synchronous"
                )
                retries = {
                    row.node_run_id: row
                    for row in session.scalars(
                        select(NodeRetry).where(NodeRetry.workflow_run_id == run_id)
                    )
                }
                nodes = []
                providers = {
                    event.node_run_id: ProviderMetadata.model_validate(
                        event.event_payload["provider"]
                    )
                    for event in session.scalars(
                        select(ExecutionEvent).where(
                            ExecutionEvent.workflow_run_id == run_id,
                            ExecutionEvent.event_type == EventType.NODE_STATUS_CHANGED,
                            ExecutionEvent.event_payload.op("?")("provider"),
                        )
                    )
                }
                agents = {
                    event.node_run_id: AgentMetadata.model_validate(event.event_payload["agent"])
                    for event in session.scalars(
                        select(ExecutionEvent).where(
                            ExecutionEvent.workflow_run_id == run_id,
                            ExecutionEvent.event_type == EventType.NODE_STATUS_CHANGED,
                            ExecutionEvent.event_payload.op("?")("agent"),
                        )
                    )
                }
                for row in attempts:
                    node = NodeAttemptResponse.model_validate(row)
                    node.provider = providers.get(row.id)
                    node.agent = agents.get(row.id)
                    retry = retries.get(row.id)
                    if retry is not None:
                        node.retry = RetryScheduleResponse.model_validate(retry)
                        if (
                            retry.resumed_at is None
                            and retry.cancelled_at is None
                            and run.status == RunStatus.RUNNING
                        ):
                            summary.update(
                                next_retry_at=retry.due_at,
                                retry_node_id=row.node_id,
                                next_retry_attempt=row.attempt_number + 1,
                            )
                    nodes.append(node)
                return RunResponse(
                    **summary,
                    version=WorkflowVersionResponse.model_validate(version),
                    node_runs=nodes,
                )
        except (OperationalError, TimeoutError):
            raise ExecutionStorageUnavailableError(run_id) from None
