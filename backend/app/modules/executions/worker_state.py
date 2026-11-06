"""Claim-fenced worker state writes; computation belongs outside these transactions."""

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.infrastructure.database.models import NodeRun, WorkflowRun, WorkflowVersion
from app.infrastructure.database.session import Database
from app.modules.claims.repository import Claim, ClaimRepository
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.exceptions import ExecutionConflictError
from app.modules.executions.payloads import copy_payload
from app.modules.executions.recovery import (
    InconsistentHistoryError,
    StoredAttempt,
    reconstruct_progress,
)
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.retry_models import NodeRetry
from app.modules.executions.retry_policy import retry_delay
from app.modules.executions.runner import RETRY_SAFE_TYPES
from app.modules.executions.state import (
    RETRYABLE_FAILURE_CODES,
    EventType,
    FailureCode,
    NodeStatus,
    RunStatus,
)
from app.modules.workflows.compiler import compile_workflow


class WorkerState:
    """Each operation checks ownership and lease under the same run-row lock as its write.

    This is an internal foundation, not a worker or a recovery scheduler. Callers
    must recompile/validate exact-version history and enforce retry eligibility.
    """

    def __init__(self, database: Database, *, owner_id: UUID, claim: Claim) -> None:
        self.database = database
        self.owner_id = owner_id
        self.claim = claim

    def _checked(self, session: Session) -> ExecutionRepository:
        repository = ExecutionRepository(session)
        repository.lock_owned(run_id=self.claim.run_id, owner_id=self.owner_id)
        ClaimRepository(session).assert_current(self.claim)
        return repository

    def renew(self, *, lease_seconds: int = 30) -> None:
        """Renew between computations; an expired or cancelled lease cannot be revived."""
        with self.database.unit_of_work() as session:
            session.execute(text("SET LOCAL statement_timeout = '2000ms'"))
            self._checked(session)
            ClaimRepository(session).renew(self.claim, lease_seconds=lease_seconds)

    def _retry_or_fail(
        self,
        session: Session,
        repository: ExecutionRepository,
        run: WorkflowRun,
        attempt: NodeRun,
    ) -> bool:
        """True permits an immediate/new due attempt; False ends this worker delivery."""
        code = attempt.error_code
        if code is None or attempt.status != NodeStatus.FAILED:
            raise ExecutionConflictError()
        if attempt.attempt_number >= run.max_attempts or code not in RETRYABLE_FAILURE_CODES:
            repository.transition_run(
                run_id=run.id,
                owner_id=self.owner_id,
                expected_revision=run.revision,
                target=RunStatus.FAILED,
                error_code=code,
            )
            return False
        dispatch = session.get(WorkflowDispatch, run.id)
        if dispatch is None:
            return True  # Unintegrated/internal pure runs retain immediate retries.
        now = session.scalar(select(func.clock_timestamp()))
        assert now is not None
        scheduled = session.get(NodeRetry, attempt.id)
        if scheduled is not None:
            if scheduled.resumed_at is not None or scheduled.cancelled_at is not None:
                raise ExecutionConflictError()
            if scheduled.due_at <= now:
                return True
        else:
            delay = retry_delay(
                attempt.attempt_number,
                base_seconds=dispatch.retry_base_seconds,
                max_seconds=dispatch.retry_max_seconds,
            )
            scheduled = NodeRetry(
                node_run_id=attempt.id,
                workflow_run_id=run.id,
                created_at=now,
                due_at=now + timedelta(seconds=delay),
            )
            session.add(scheduled)
            session.flush()
            repository._event(
                run,
                EventType.NODE_RETRY_SCHEDULED,
                {
                    "node_id": attempt.node_id,
                    "attempt_number": attempt.attempt_number,
                    "retry_at": scheduled.due_at.isoformat(),
                },
                attempt.id,
            )
        dispatch.next_dispatch_at = scheduled.due_at
        # Failure, deadline, event and release commit together. The worker never sleeps.
        ClaimRepository(session).release(self.claim)
        return False

    def fail_attempt(
        self,
        *,
        expected_run_revision: int,
        attempt_id: UUID,
        expected_revision: int,
        error_code: FailureCode,
    ) -> bool:
        """Atomically fail an attempt and either fail, schedule, or permit a retry."""
        with self.database.unit_of_work() as session:
            repository = self._checked(session)
            attempt = repository.transition_attempt(
                run_id=self.claim.run_id,
                owner_id=self.owner_id,
                attempt_id=attempt_id,
                expected_run_revision=expected_run_revision,
                expected_revision=expected_revision,
                target=NodeStatus.FAILED,
                error_code=error_code,
            )
            run = repository.lock_owned(run_id=self.claim.run_id, owner_id=self.owner_id)
            return self._retry_or_fail(session, repository, run, attempt)

    def reconcile_attempt(self, *, expected_run_revision: int) -> bool:
        """Close an interrupted pure attempt, retaining its history and retry budget.

        Only the selected route of the exact saved pure graph is eligible. An
        interrupted attempt consumes its original slot and becomes INTERNAL_FAILURE.
        Deterministic failures and exhausted budgets atomically fail the run. No
        computation occurs here; True permits a new attempt. False means terminal
        failure or a durable scheduled retry with its claim released.
        """
        with self.database.unit_of_work() as session:
            repository = self._checked(session)
            run = repository.lock_owned(run_id=self.claim.run_id, owner_id=self.owner_id)
            if run.status != RunStatus.RUNNING or run.revision != expected_run_revision:
                raise ExecutionConflictError()
            version = session.get(WorkflowVersion, run.workflow_version_id)
            if version is None or version.workflow_id != run.workflow_id:
                raise ExecutionConflictError()
            plan = compile_workflow(version.definition_json).plan
            if plan is None or any(node.type not in RETRY_SAFE_TYPES for node in plan.nodes):
                raise ExecutionConflictError()
            attempts = list(
                session.scalars(
                    select(NodeRun)
                    .where(NodeRun.workflow_run_id == run.id)
                    .order_by(NodeRun.created_at, NodeRun.id)
                    .execution_options(populate_existing=True)
                )
            )
            try:
                progress = reconstruct_progress(
                    plan,
                    run.input_json,
                    [
                        StoredAttempt(row.node_id, row.attempt_number, row.status, row.output_json)
                        for row in attempts
                    ],
                )
            except InconsistentHistoryError:
                raise ExecutionConflictError() from None
            if progress.state not in {"interrupted", "failed"}:
                raise ExecutionConflictError()
            latest = next(row for row in reversed(attempts) if row.node_id == progress.next_node_id)
            if progress.state == "interrupted":
                repository.transition_attempt(
                    run_id=run.id,
                    owner_id=self.owner_id,
                    attempt_id=latest.id,
                    expected_run_revision=expected_run_revision,
                    expected_revision=latest.revision,
                    target=NodeStatus.FAILED,
                    error_code=FailureCode.INTERNAL_FAILURE,
                )
            return self._retry_or_fail(session, repository, run, latest)

    def transition_run(
        self,
        *,
        expected_revision: int,
        target: RunStatus,
        output: dict[str, Any] | None = None,
        error_code: FailureCode | None = None,
    ) -> None:
        with self.database.unit_of_work() as session:
            self._checked(session).transition_run(
                run_id=self.claim.run_id,
                owner_id=self.owner_id,
                expected_revision=expected_revision,
                target=target,
                output=output,
                error_code=error_code,
            )

    def start_attempt(
        self,
        *,
        expected_run_revision: int,
        node_id: str,
        input_data: dict[str, Any],
    ) -> UUID:
        """Create and start an attempt atomically; no node computation occurs here."""
        with self.database.unit_of_work() as session:
            repository = self._checked(session)
            scheduled = session.scalar(
                select(NodeRetry).where(
                    NodeRetry.workflow_run_id == self.claim.run_id,
                    NodeRetry.resumed_at.is_(None),
                    NodeRetry.cancelled_at.is_(None),
                )
            )
            if scheduled is not None:
                previous = session.get(NodeRun, scheduled.node_run_id)
                now = session.scalar(select(func.clock_timestamp()))
                if (
                    previous is None
                    or previous.node_id != node_id
                    or previous.status != NodeStatus.FAILED
                    or now is None
                    or scheduled.due_at > now
                ):
                    raise ExecutionConflictError()
            attempt = repository.add_attempt(
                run_id=self.claim.run_id,
                owner_id=self.owner_id,
                expected_run_revision=expected_run_revision,
                node_id=node_id,
                input_json=input_data,
            )
            repository.transition_attempt(
                run_id=self.claim.run_id,
                owner_id=self.owner_id,
                attempt_id=attempt.id,
                expected_run_revision=expected_run_revision,
                expected_revision=0,
                target=NodeStatus.RUNNING,
            )
            if scheduled is not None:
                scheduled.resumed_at = session.scalar(select(func.clock_timestamp()))
                session.flush()
            return attempt.id

    def finish_attempt(
        self,
        *,
        expected_run_revision: int,
        attempt_id: UUID,
        expected_revision: int,
        target: NodeStatus,
        output: dict[str, Any] | None = None,
        error_code: FailureCode | None = None,
        fail_run: bool = False,
    ) -> None:
        if target not in {NodeStatus.SUCCEEDED, NodeStatus.FAILED}:
            raise ValueError("A worker can only succeed or fail an active attempt")
        if fail_run and target != NodeStatus.FAILED:
            raise ValueError("Run failure requires a failed attempt")
        with self.database.unit_of_work() as session:
            repository = self._checked(session)
            repository.transition_attempt(
                run_id=self.claim.run_id,
                owner_id=self.owner_id,
                attempt_id=attempt_id,
                expected_run_revision=expected_run_revision,
                expected_revision=expected_revision,
                target=target,
                output=output,
                error_code=error_code,
            )
            if fail_run:
                repository.transition_run(
                    run_id=self.claim.run_id,
                    owner_id=self.owner_id,
                    expected_revision=expected_run_revision,
                    target=RunStatus.FAILED,
                    error_code=error_code,
                )

    def complete_workflow(
        self,
        *,
        expected_run_revision: int,
        attempt_id: UUID,
        expected_revision: int,
        output: dict[str, Any],
    ) -> None:
        """Commit a selected end, all unvisited skips, and success under one claim.

        The route and skipped nodes come from the saved version and committed attempts,
        never from a caller-provided skip list. No provider calls occur here.
        """
        result = copy_payload(output)
        with self.database.unit_of_work() as session:
            repository = self._checked(session)
            run = repository.lock_owned(run_id=self.claim.run_id, owner_id=self.owner_id)
            if run.status != RunStatus.RUNNING or run.revision != expected_run_revision:
                raise ExecutionConflictError()
            version = session.get(WorkflowVersion, run.workflow_version_id)
            if version is None or version.workflow_id != run.workflow_id:
                raise ExecutionConflictError()
            plan = compile_workflow(version.definition_json).plan
            if plan is None:
                raise ExecutionConflictError()
            attempts = list(
                session.scalars(
                    select(NodeRun)
                    .where(NodeRun.workflow_run_id == run.id)
                    .order_by(NodeRun.created_at, NodeRun.id)
                )
            )
            try:
                progress = reconstruct_progress(
                    plan,
                    run.input_json,
                    [
                        StoredAttempt(row.node_id, row.attempt_number, row.status, row.output_json)
                        for row in attempts
                    ],
                )
            except InconsistentHistoryError:
                raise ExecutionConflictError() from None
            end = next((row for row in attempts if row.id == attempt_id), None)
            if (
                progress.state != "interrupted"
                or end is None
                or end.node_id != progress.next_node_id
                or end.node_id not in plan.terminal_node_ids
                or end.status != NodeStatus.RUNNING
                or end.revision != expected_revision
                or json.dumps(end.input_json, sort_keys=True) != json.dumps(result, sort_keys=True)
            ):
                raise ExecutionConflictError()
            repository.transition_attempt(
                run_id=run.id,
                owner_id=self.owner_id,
                attempt_id=attempt_id,
                expected_run_revision=expected_run_revision,
                expected_revision=expected_revision,
                target=NodeStatus.SUCCEEDED,
                output=result,
            )
            visited = {*progress.visited, end.node_id}
            for node in plan.nodes:
                if node.id in visited:
                    continue
                skipped = repository.add_attempt(
                    run_id=run.id,
                    owner_id=self.owner_id,
                    expected_run_revision=expected_run_revision,
                    node_id=node.id,
                    input_json={},
                )
                repository.transition_attempt(
                    run_id=run.id,
                    owner_id=self.owner_id,
                    attempt_id=skipped.id,
                    expected_run_revision=expected_run_revision,
                    expected_revision=0,
                    target=NodeStatus.SKIPPED,
                )
            repository.transition_run(
                run_id=run.id,
                owner_id=self.owner_id,
                expected_revision=expected_run_revision,
                target=RunStatus.SUCCEEDED,
                output=result,
            )
