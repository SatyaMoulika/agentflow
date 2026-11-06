"""Internal claim-fenced runner for saved pure workflows, without broker dispatch."""

from copy import deepcopy
from uuid import UUID

from app.infrastructure.database.models import WorkflowVersion
from app.infrastructure.database.session import Database
from app.modules.claims.repository import Claim, ClaimRepository
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.exceptions import ExecutionConflictError, WorkflowNotExecutableError
from app.modules.executions.heartbeat import LeaseHeartbeat
from app.modules.executions.operations import (
    NodeExecutionError,
    execute_node,
    next_node_id,
    resolve_config,
    resolve_input,
)
from app.modules.executions.payloads import copy_payload
from app.modules.executions.recovery_snapshot import read_recovery_snapshot
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.runner import RETRY_SAFE_TYPES
from app.modules.executions.state import FailureCode, NodeStatus, RunStatus
from app.modules.executions.worker_state import WorkerState
from app.modules.workflows.compiler import compile_workflow


class PureWorkerRunner:
    def __init__(
        self,
        database: Database,
        *,
        lease_seconds: int = 30,
        heartbeat: bool = False,
        require_dispatch: bool = False,
    ) -> None:
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 3600:
            raise ValueError("Invalid claim lease duration")
        self.database = database
        self.lease_seconds = lease_seconds
        self.heartbeat = heartbeat
        self.require_dispatch = require_dispatch

    def _claim(self, *, run_id: UUID, owner_id: UUID) -> Claim | None:
        # Validate the entire immutable graph before changing a claim, including
        # unselected branches. Never take over unclaimed synchronous running work.
        with self.database.session() as session:
            repository = ExecutionRepository(session)
            run = repository.lock_owned(run_id=run_id, owner_id=owner_id)
            if self.require_dispatch and session.get(WorkflowDispatch, run_id) is None:
                raise WorkflowNotExecutableError()
            if run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                return None
            version = session.get(WorkflowVersion, run.workflow_version_id)
            if version is None or version.workflow_id != run.workflow_id:
                raise WorkflowNotExecutableError()
            definition = deepcopy(version.definition_json)
        plan = compile_workflow(definition).plan
        if plan is None or any(node.type not in RETRY_SAFE_TYPES for node in plan.nodes):
            raise WorkflowNotExecutableError()
        with self.database.unit_of_work() as session:
            ExecutionRepository(session).lock_owned(run_id=run_id, owner_id=owner_id)
            return ClaimRepository(session).acquire_for_recovery(
                run_id, lease_seconds=self.lease_seconds
            )

    def run(self, *, run_id: UUID, owner_id: UUID) -> bool:
        """Execute/recover a pure run; False means unavailable, claimed, or not yet due.

        Successful outputs are reused, interrupted attempts consume the saved budget,
        and each write is fenced. Claim loss and storage errors escape without further
        writes. True means this delivery finished or durably scheduled a retry.
        """
        claim = self._claim(run_id=run_id, owner_id=owner_id)
        if claim is None:
            return False
        worker = WorkerState(self.database, owner_id=owner_id, claim=claim)
        with LeaseHeartbeat(
            worker, lease_seconds=self.lease_seconds, enabled=self.heartbeat
        ) as beat:
            return self._run_claimed(owner_id=owner_id, claim=claim, worker=worker, beat=beat)

    def _run_claimed(
        self, *, owner_id: UUID, claim: Claim, worker: WorkerState, beat: LeaseHeartbeat
    ) -> bool:
        while True:
            beat.check()
            worker.renew(lease_seconds=self.lease_seconds)
            snapshot = read_recovery_snapshot(self.database, owner_id=owner_id, claim=claim)
            if snapshot.status == RunStatus.QUEUED:
                worker.transition_run(expected_revision=snapshot.revision, target=RunStatus.RUNNING)
                continue
            progress = snapshot.progress
            if progress.state in {"interrupted", "failed"}:
                if not worker.reconcile_attempt(expected_run_revision=snapshot.revision):
                    return True
                # Re-read the committed history after reconciliation. A failed attempt
                # stays failed; retry always creates a fresh attempt.
                snapshot = read_recovery_snapshot(self.database, owner_id=owner_id, claim=claim)
                progress = snapshot.progress
            node = next(
                (node for node in snapshot.plan.nodes if node.id == progress.next_node_id), None
            )
            if node is None or progress.state not in {"ready", "failed"}:
                raise ExecutionConflictError()
            code = None
            try:
                resolved = resolve_input(node, progress.incoming, progress.outputs)
                config = resolve_config(node, progress.outputs)
            except NodeExecutionError as error:
                resolved, config, code = {}, {}, error.code
            except Exception:
                resolved, config, code = {}, {}, FailureCode.INTERNAL_FAILURE
            attempt_id = worker.start_attempt(
                expected_run_revision=snapshot.revision, node_id=node.id, input_data=resolved
            )
            output = None
            if code is None:
                try:
                    # No transaction is held across input resolution or node execution.
                    output = copy_payload(
                        execute_node(
                            node, copy_payload(resolved), resolved_config=copy_payload(config)
                        )
                    )
                    following = next_node_id(node, output)
                    if following is not None and (
                        following in progress.visited
                        or all(other.id != following for other in snapshot.plan.nodes)
                    ):
                        raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
                except NodeExecutionError as error:
                    code = error.code
                except Exception:
                    code = FailureCode.INTERNAL_FAILURE
            beat.check()
            if code is not None:
                retry = worker.fail_attempt(
                    expected_run_revision=snapshot.revision,
                    attempt_id=attempt_id,
                    expected_revision=1,
                    error_code=code,
                )
                if not retry:
                    return True
            elif output is not None:
                if node.type == "end":
                    worker.complete_workflow(
                        expected_run_revision=snapshot.revision,
                        attempt_id=attempt_id,
                        expected_revision=1,
                        output=output,
                    )
                    return True
                worker.finish_attempt(
                    expected_run_revision=snapshot.revision,
                    attempt_id=attempt_id,
                    expected_revision=1,
                    target=NodeStatus.SUCCEEDED,
                    output=output,
                )
