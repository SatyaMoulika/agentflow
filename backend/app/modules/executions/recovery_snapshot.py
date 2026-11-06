"""Read an owner-scoped, claim-fenced execution snapshot for future recovery."""

from copy import deepcopy
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from app.infrastructure.database.models import NodeRun, WorkflowVersion
from app.infrastructure.database.session import Database
from app.modules.claims.repository import Claim, ClaimRepository
from app.modules.executions.exceptions import ExecutionNotFoundError, WorkflowNotExecutableError
from app.modules.executions.payloads import copy_payload
from app.modules.executions.recovery import (
    ReconstructedProgress,
    StoredAttempt,
    reconstruct_progress,
)
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.runner import RETRY_SAFE_TYPES
from app.modules.executions.state import RunStatus
from app.modules.workflows.compiler import CompiledWorkflow, compile_workflow


@dataclass(frozen=True)
class RecoverySnapshot:
    run_id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    revision: int
    status: RunStatus
    max_attempts: int
    plan: CompiledWorkflow
    progress: ReconstructedProgress


def read_recovery_snapshot(database: Database, *, owner_id: UUID, claim: Claim) -> RecoverySnapshot:
    """Copy coherent history under the owned run lock; compile after releasing it.

    The returned snapshot is advisory: every subsequent state write must recheck
    the claim while holding the run lock in its own transaction. This read never
    executes nodes, mutates run state, or grants access based on a run ID alone.
    """
    with database.session() as session:
        run = ExecutionRepository(session).lock_owned(run_id=claim.run_id, owner_id=owner_id)
        ClaimRepository(session).assert_current(claim)
        version = session.scalar(
            select(WorkflowVersion).where(
                WorkflowVersion.id == run.workflow_version_id,
                WorkflowVersion.workflow_id == run.workflow_id,
            )
        )
        if version is None:
            raise ExecutionNotFoundError()
        definition = deepcopy(version.definition_json)
        initial = copy_payload(run.input_json)
        rows = session.scalars(
            select(NodeRun)
            .where(NodeRun.workflow_run_id == run.id)
            .order_by(NodeRun.created_at, NodeRun.id)
        ).all()
        attempts = [
            StoredAttempt(row.node_id, row.attempt_number, row.status, deepcopy(row.output_json))
            for row in rows
        ]
        run_id, workflow_id, version_id = run.id, run.workflow_id, run.workflow_version_id
        revision, status, max_attempts = run.revision, run.status, run.max_attempts
    compiled = compile_workflow(definition)
    plan = compiled.plan
    if plan is None or any(node.type not in RETRY_SAFE_TYPES for node in plan.nodes):
        raise WorkflowNotExecutableError()
    progress = reconstruct_progress(plan, initial, attempts)
    if status == RunStatus.QUEUED and (progress.state != "ready" or progress.visited):
        raise WorkflowNotExecutableError()
    if status == RunStatus.RUNNING and progress.state == "complete":
        raise WorkflowNotExecutableError()
    return RecoverySnapshot(
        run_id, workflow_id, version_id, revision, status, max_attempts, plan, progress
    )
