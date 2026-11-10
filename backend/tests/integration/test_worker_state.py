"""Worker state changes must be owned, claim-fenced, atomic and auditable."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.infrastructure.database.models import NodeRun, RunClaim, WorkflowRun
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.claims.repository import ClaimLostError, ClaimRepository
from app.modules.executions.exceptions import ExecutionConflictError, ExecutionNotFoundError
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import FailureCode, NodeStatus, RunStatus
from app.modules.executions.worker_state import WorkerState
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [{"id": "e1", "source": "start", "target": "end"}],
}


@pytest.fixture
def prepared(repository_database: Database):
    with repository_database.unit_of_work() as session:
        users = UserRepository(session)
        owner = users.add(
            email="worker-state@example.com", display_name="Owner", password_hash="fixture"
        )
        other = users.add(
            email="worker-other@example.com", display_name="Other", password_hash="fixture"
        )
        repo = WorkflowRepository(session)
        workflow = repo.add(owner_id=owner.id, name="Worker")
        version = repo.append_version(
            workflow_id=workflow.id, owner_id=owner.id, expected_version=0, definition=GRAPH
        )
        run = ExecutionRepository(session).create_run(
            workflow_id=workflow.id, version_id=version.id, owner_id=owner.id, input_json={"x": 1}
        )
        run_id, owner_id, other_id = run.id, owner.id, other.id
    with repository_database.unit_of_work() as session:
        claim = ClaimRepository(session).acquire(run_id)
        assert claim is not None
    return run_id, owner_id, other_id, claim


def test_state_changes_record_actual_results_and_events(
    repository_database: Database, prepared
) -> None:
    run_id, owner, _, claim = prepared
    worker = WorkerState(repository_database, owner_id=owner, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    attempt = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={"x": 1})
    worker.finish_attempt(
        expected_run_revision=1,
        attempt_id=attempt,
        expected_revision=1,
        target=NodeStatus.SUCCEEDED,
        output={"x": 1},
    )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        node = session.get(NodeRun, attempt)
        assert run is not None and run.status == RunStatus.RUNNING and run.event_sequence == 5
        assert (
            node is not None
            and node.status == NodeStatus.SUCCEEDED
            and node.output_json == {"x": 1}
        )


def test_owner_and_expired_claim_block_all_worker_operations(
    repository_database: Database, prepared
) -> None:
    run_id, owner, other, claim = prepared
    with pytest.raises(ExecutionNotFoundError):
        WorkerState(repository_database, owner_id=other, claim=claim).transition_run(
            expected_revision=0, target=RunStatus.RUNNING
        )
    with repository_database.unit_of_work() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(minutes=1)
    worker = WorkerState(repository_database, owner_id=owner, claim=claim)
    with pytest.raises(ClaimLostError):
        worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    with pytest.raises(ClaimLostError):
        worker.start_attempt(expected_run_revision=0, node_id="start", input_data={})
    with pytest.raises(ClaimLostError):
        worker.finish_attempt(
            expected_run_revision=0,
            attempt_id=run_id,
            expected_revision=0,
            target=NodeStatus.FAILED,
            error_code=FailureCode.INTERNAL_FAILURE,
        )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None and run.status == RunStatus.QUEUED and run.event_sequence == 1
        assert not session.scalars(select(NodeRun).where(NodeRun.workflow_run_id == run_id)).all()


def test_cancellation_prevents_late_success(repository_database: Database, prepared) -> None:
    run_id, owner, _, claim = prepared
    worker = WorkerState(repository_database, owner_id=owner, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    attempt = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={"x": 1})
    with repository_database.unit_of_work() as session:
        repo = ExecutionRepository(session)
        repo.transition_attempt(
            run_id=run_id,
            owner_id=owner,
            attempt_id=attempt,
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.CANCELLED,
        )
        repo.transition_run(
            run_id=run_id, owner_id=owner, expected_revision=1, target=RunStatus.CANCELLED
        )
    with pytest.raises(ClaimLostError):
        worker.finish_attempt(
            expected_run_revision=1,
            attempt_id=attempt,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output={"x": 1},
        )
    with repository_database.session() as session:
        node = session.get(NodeRun, attempt)
        assert node is not None and node.status == NodeStatus.CANCELLED and node.output_json is None


def test_terminal_failure_and_attempt_commit_together(
    repository_database: Database, prepared
) -> None:
    run_id, owner, _, claim = prepared
    worker = WorkerState(repository_database, owner_id=owner, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    attempt = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={})
    worker.finish_attempt(
        expected_run_revision=1,
        attempt_id=attempt,
        expected_revision=1,
        target=NodeStatus.FAILED,
        error_code=FailureCode.INTERNAL_FAILURE,
        fail_run=True,
    )
    with repository_database.session() as session:
        node = session.get(NodeRun, attempt)
        run = session.get(WorkflowRun, run_id)
        assert node is not None and node.status == NodeStatus.FAILED
        assert (
            run is not None
            and run.status == RunStatus.FAILED
            and run.error_code == FailureCode.INTERNAL_FAILURE
        )
        assert run.event_sequence == 6


def test_event_failure_rolls_back_attempt_and_run(
    repository_database: Database, prepared, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, owner, _, claim = prepared
    worker = WorkerState(repository_database, owner_id=owner, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    attempt = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={})
    original = ExecutionRepository._event
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        event = original(self, *args, **kwargs)
        if calls == 2:
            raise OperationalError("private", {}, Exception())
        return event

    monkeypatch.setattr(ExecutionRepository, "_event", fail_second)
    with pytest.raises(OperationalError):
        worker.finish_attempt(
            expected_run_revision=1,
            attempt_id=attempt,
            expected_revision=1,
            target=NodeStatus.FAILED,
            error_code=FailureCode.INTERNAL_FAILURE,
            fail_run=True,
        )
    with repository_database.session() as session:
        node = session.get(NodeRun, attempt)
        run = session.get(WorkflowRun, run_id)
        assert node is not None and node.status == NodeStatus.RUNNING
        assert run is not None and run.status == RunStatus.RUNNING and run.event_sequence == 4


def test_cancel_waits_for_fenced_transaction_and_no_late_write(
    repository_database: Database, prepared, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, owner, _, claim = prepared
    worker = WorkerState(repository_database, owner_id=owner, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    attempt = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={})
    entered, release = Event(), Event()
    original = ExecutionRepository.transition_attempt

    def pause(self, **kwargs):
        if kwargs["target"] == NodeStatus.SUCCEEDED:
            entered.set()
            assert release.wait(10)
        return original(self, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "transition_attempt", pause)

    def finish():
        worker.finish_attempt(
            expected_run_revision=1,
            attempt_id=attempt,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output={},
        )

    def cancel():
        with repository_database.unit_of_work() as session:
            ExecutionRepository(session).transition_run(
                run_id=run_id, owner_id=owner, expected_revision=1, target=RunStatus.CANCELLED
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(finish)
        try:
            assert entered.wait(10)
            second = pool.submit(cancel)
        finally:
            release.set()
        first.result(10)
        second.result(10)
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        node = session.get(NodeRun, attempt)
        assert run is not None and run.status == RunStatus.CANCELLED
        assert node is not None and node.status == NodeStatus.SUCCEEDED


def test_replaced_claim_cannot_start_run(repository_database: Database, prepared) -> None:
    run_id, owner, _, old_claim = prepared
    with repository_database.unit_of_work() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(minutes=1)
    with repository_database.unit_of_work() as session:
        new_claim = ClaimRepository(session).acquire(run_id)
        assert new_claim is not None and new_claim.generation > old_claim.generation
    with pytest.raises(ClaimLostError):
        WorkerState(repository_database, owner_id=owner, claim=old_claim).transition_run(
            expected_revision=0, target=RunStatus.RUNNING
        )
    WorkerState(repository_database, owner_id=owner, claim=new_claim).transition_run(
        expected_revision=0, target=RunStatus.RUNNING
    )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None and run.status == RunStatus.RUNNING and run.event_sequence == 2


@pytest.fixture
def branch_ready(repository_database: Database):
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "choose",
                "type": "condition",
                "config": {
                    "field": "$.start.output.x",
                    "operator": "greater_than",
                    "value": 0,
                },
            },
            {"id": "yes", "type": "end", "config": {}},
            {"id": "no", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "choose"},
            {"id": "b", "source": "choose", "target": "yes", "source_handle": "true"},
            {"id": "c", "source": "choose", "target": "no", "source_handle": "false"},
        ],
    }
    with repository_database.unit_of_work() as session:
        owner = UserRepository(session).add(
            email="worker-branch@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Branch")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owner.id, expected_version=0, definition=graph
        )
        run = ExecutionRepository(session).create_run(
            workflow_id=workflow.id, version_id=version.id, owner_id=owner.id, input_json={"x": 1}
        )
        run_id, owner_id = run.id, owner.id
    with repository_database.unit_of_work() as session:
        claim = ClaimRepository(session).acquire(run_id)
        assert claim is not None
    worker = WorkerState(repository_database, owner_id=owner_id, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    for node, data, result in (
        ("start", {"x": 1}, {"x": 1}),
        ("choose", {"x": 1}, {"result": True}),
    ):
        attempt = worker.start_attempt(expected_run_revision=1, node_id=node, input_data=data)
        worker.finish_attempt(
            expected_run_revision=1,
            attempt_id=attempt,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output=result,
        )
    end = worker.start_attempt(expected_run_revision=1, node_id="yes", input_data={"result": True})
    return run_id, owner_id, claim, worker, end


def test_fenced_completion_atomically_records_end_skipped_branch_and_run(
    repository_database: Database, branch_ready
) -> None:
    run_id, _, _, worker, end = branch_ready
    worker.complete_workflow(
        expected_run_revision=1, attempt_id=end, expected_revision=1, output={"result": True}
    )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        rows = session.scalars(select(NodeRun).where(NodeRun.workflow_run_id == run_id)).all()
        assert run is not None and run.status == RunStatus.SUCCEEDED
        assert run.output_json == {"result": True}
        assert {row.node_id: row.status for row in rows} == {
            "start": NodeStatus.SUCCEEDED,
            "choose": NodeStatus.SUCCEEDED,
            "yes": NodeStatus.SUCCEEDED,
            "no": NodeStatus.SKIPPED,
        }


def test_fenced_completion_rejects_expired_claim_and_wrong_result(
    repository_database: Database, branch_ready
) -> None:
    run_id, _, _, worker, end = branch_ready
    with pytest.raises(ExecutionConflictError):
        worker.complete_workflow(
            expected_run_revision=1, attempt_id=end, expected_revision=1, output={}
        )
    with pytest.raises(ExecutionConflictError):
        worker.complete_workflow(
            expected_run_revision=1, attempt_id=end, expected_revision=1, output={"result": 1}
        )
    with repository_database.unit_of_work() as session:
        claim = session.get(RunClaim, run_id)
        assert claim is not None and claim.lease_until is not None
        claim.lease_until -= timedelta(minutes=1)
    with pytest.raises(ClaimLostError):
        worker.complete_workflow(
            expected_run_revision=1, attempt_id=end, expected_revision=1, output={"result": True}
        )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None and run.status == RunStatus.RUNNING


def test_fenced_completion_rolls_back_every_write_on_skip_failure(
    repository_database: Database, branch_ready, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id, _, _, worker, end = branch_ready
    original = ExecutionRepository.transition_attempt

    def fail_skip(self, **kwargs):
        if kwargs["target"] == NodeStatus.SKIPPED:
            raise OperationalError("private", {}, Exception())
        return original(self, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "transition_attempt", fail_skip)
    with pytest.raises(OperationalError):
        worker.complete_workflow(
            expected_run_revision=1, attempt_id=end, expected_revision=1, output={"result": True}
        )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        attempt = session.get(NodeRun, end)
        rows = session.scalars(select(NodeRun).where(NodeRun.workflow_run_id == run_id)).all()
        assert run is not None and run.status == RunStatus.RUNNING
        assert attempt is not None and attempt.status == NodeStatus.RUNNING
        assert {row.node_id for row in rows} == {"start", "choose", "yes"}


def test_fenced_completion_rejects_attempt_on_unselected_branch(
    repository_database: Database, branch_ready
) -> None:
    run_id, _, _, worker, end = branch_ready
    wrong = worker.start_attempt(expected_run_revision=1, node_id="no", input_data={"result": True})
    with pytest.raises(ExecutionConflictError):
        worker.complete_workflow(
            expected_run_revision=1, attempt_id=wrong, expected_revision=1, output={"result": True}
        )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        attempt = session.get(NodeRun, end)
        assert run is not None and run.status == RunStatus.RUNNING
        assert attempt is not None and attempt.status == NodeStatus.RUNNING


def test_fenced_completion_cannot_override_cancellation(
    repository_database: Database, branch_ready
) -> None:
    run_id, owner, _, worker, end = branch_ready
    with repository_database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        repository.transition_attempt(
            run_id=run_id,
            owner_id=owner,
            attempt_id=end,
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.CANCELLED,
        )
        repository.transition_run(
            run_id=run_id,
            owner_id=owner,
            expected_revision=1,
            target=RunStatus.CANCELLED,
        )
    with pytest.raises(ClaimLostError):
        worker.complete_workflow(
            expected_run_revision=1, attempt_id=end, expected_revision=1, output={"result": True}
        )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None and run.status == RunStatus.CANCELLED and run.output_json is None
