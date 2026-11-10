"""Recovery snapshots enforce ownership, live leases and coherent committed history."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import NodeRun, RunClaim, WorkflowRun
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.claims.repository import ClaimLostError, ClaimRepository
from app.modules.executions.exceptions import ExecutionNotFoundError, WorkflowNotExecutableError
from app.modules.executions.recovery_snapshot import read_recovery_snapshot
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import NodeStatus, RunStatus
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
def setup_run(repository_database: Database):
    with repository_database.unit_of_work() as session:
        users = UserRepository(session)
        owner = users.add(
            email="snapshot-owner@example.com", display_name="Owner", password_hash="fixture"
        )
        other = users.add(
            email="snapshot-other@example.com", display_name="Other", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Snapshot")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owner.id, expected_version=0, definition=GRAPH
        )
        run = ExecutionRepository(session).create_run(
            workflow_id=workflow.id,
            version_id=version.id,
            owner_id=owner.id,
            input_json={"CaseKey": {"v": 3}},
        )
        run_id, owner_id, other_id, workflow_id, version_id = (
            run.id,
            owner.id,
            other.id,
            workflow.id,
            version.id,
        )
    with repository_database.unit_of_work() as session:
        claim = ClaimRepository(session).acquire(run_id)
        assert claim is not None
    return run_id, owner_id, other_id, workflow_id, version_id, claim


def test_queued_snapshot_pins_owned_version_and_is_detached(
    repository_database: Database, setup_run
) -> None:
    run_id, owner, _, workflow, version, claim = setup_run
    snapshot = read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    assert (snapshot.run_id, snapshot.workflow_id, snapshot.workflow_version_id) == (
        run_id,
        workflow,
        version,
    )
    assert snapshot.status == RunStatus.QUEUED and snapshot.revision == 0
    assert snapshot.progress.state == "ready" and snapshot.progress.next_node_id == "start"
    snapshot.progress.incoming["CaseKey"]["v"] = 99
    second = read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    assert second.progress.incoming == {"CaseKey": {"v": 3}}


def test_running_snapshot_follows_actual_committed_attempts(
    repository_database: Database, setup_run
) -> None:
    run_id, owner, _, _, _, claim = setup_run
    with repository_database.unit_of_work() as session:
        ClaimRepository(session).assert_current(claim)
        repo = ExecutionRepository(session)
        repo.transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.RUNNING
        )
        attempt = repo.add_attempt(
            run_id=run_id,
            owner_id=owner,
            expected_run_revision=1,
            node_id="start",
            input_json={"CaseKey": {"v": 3}},
        )
        repo.transition_attempt(
            run_id=run_id,
            owner_id=owner,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repo.transition_attempt(
            run_id=run_id,
            owner_id=owner,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output={"CaseKey": {"v": 3}},
        )
    snapshot = read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    assert snapshot.status == RunStatus.RUNNING and snapshot.revision == 1
    assert snapshot.progress.state == "ready" and snapshot.progress.next_node_id == "end"
    assert snapshot.progress.outputs == {"start": {"CaseKey": {"v": 3}}}
    with repository_database.session() as session:
        assert (
            len(session.scalars(select(NodeRun).where(NodeRun.workflow_run_id == run_id)).all())
            == 1
        )


def test_other_owner_and_stale_claim_are_refused(repository_database: Database, setup_run) -> None:
    run_id, owner, other, _, _, claim = setup_run
    with pytest.raises(ExecutionNotFoundError):
        read_recovery_snapshot(repository_database, owner_id=other, claim=claim)
    with repository_database.unit_of_work() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(minutes=1)
    with pytest.raises(ClaimLostError):
        read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    with repository_database.unit_of_work() as session:
        replacement = ClaimRepository(session).acquire(run_id)
        assert replacement is not None and replacement.generation > claim.generation
    with pytest.raises(ClaimLostError):
        read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    assert (
        read_recovery_snapshot(repository_database, owner_id=owner, claim=replacement).run_id
        == run_id
    )


def test_cancellation_invalidates_snapshot(repository_database: Database, setup_run) -> None:
    run_id, owner, _, _, _, claim = setup_run
    with repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.CANCELLED
        )
    with pytest.raises(ClaimLostError):
        read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)


def test_snapshot_uses_run_version_even_after_workflow_save(
    repository_database: Database, setup_run
) -> None:
    _, owner, _, workflow_id, version_id, claim = setup_run
    updated = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "different", "type": "manual", "config": {}},
            {"id": "end2", "type": "end", "config": {}},
        ],
        "edges": [{"id": "e2", "source": "different", "target": "end2"}],
    }
    with repository_database.unit_of_work() as session:
        WorkflowRepository(session).append_version(
            workflow_id=workflow_id, owner_id=owner, expected_version=1, definition=updated
        )
    snapshot = read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    assert snapshot.workflow_version_id == version_id and snapshot.plan.entry_node_id == "start"


def test_invalid_graph_is_refused_without_state_change(
    repository_database: Database, setup_run
) -> None:
    run_id, owner, _, workflow_id, _, claim = setup_run
    with repository_database.unit_of_work() as session:
        bad = WorkflowRepository(session).append_version(
            workflow_id=workflow_id,
            owner_id=owner,
            expected_version=1,
            definition={"schema_version": "1.0", "nodes": [], "edges": []},
        )
        another = ExecutionRepository(session).create_run(
            workflow_id=workflow_id, version_id=bad.id, owner_id=owner, input_json={}
        )
        invalid_id = another.id
    with repository_database.unit_of_work() as session:
        invalid_claim = ClaimRepository(session).acquire(invalid_id)
        assert invalid_claim is not None
    with pytest.raises(WorkflowNotExecutableError):
        read_recovery_snapshot(repository_database, owner_id=owner, claim=invalid_claim)
    assert read_recovery_snapshot(repository_database, owner_id=owner, claim=claim).run_id == run_id
    with repository_database.session() as session:
        assert not session.scalars(
            select(NodeRun).where(NodeRun.workflow_run_id == invalid_id)
        ).all()


def test_snapshot_compile_happens_outside_run_lock(
    repository_database: Database, setup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.executions import recovery_snapshot

    run_id, owner, _, _, _, claim = setup_run
    original = recovery_snapshot.compile_workflow

    def check_unlocked(definition):
        with repository_database.session() as session:
            locked = session.scalar(
                select(WorkflowRun.id).where(WorkflowRun.id == run_id).with_for_update(nowait=True)
            )
            assert locked == run_id
        return original(definition)

    monkeypatch.setattr(recovery_snapshot, "compile_workflow", check_unlocked)
    assert read_recovery_snapshot(repository_database, owner_id=owner, claim=claim).run_id == run_id


def test_returned_snapshot_does_not_bypass_later_cancellation(
    repository_database: Database, setup_run, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.executions import recovery_snapshot

    run_id, owner, _, _, _, claim = setup_run
    original = recovery_snapshot.compile_workflow

    def cancel_after_read(definition):
        with repository_database.unit_of_work() as session:
            ExecutionRepository(session).transition_run(
                run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.CANCELLED
            )
        return original(definition)

    monkeypatch.setattr(recovery_snapshot, "compile_workflow", cancel_after_read)
    snapshot = read_recovery_snapshot(repository_database, owner_id=owner, claim=claim)
    assert snapshot.status == RunStatus.QUEUED
    with repository_database.unit_of_work() as session, pytest.raises(ClaimLostError):
        ClaimRepository(session).assert_current(claim)
