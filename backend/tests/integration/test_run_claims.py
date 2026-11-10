"""Claim concurrency, stale-worker fences and cancellation on real PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.models import RunClaim
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.claims.repository import ClaimLostError, ClaimRepository
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import RunStatus
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def owned_run(repository_database: Database):
    with repository_database.unit_of_work() as session:
        owner = UserRepository(session).add(
            email="claim@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Claim test")
        version = workflows.append_version(
            workflow_id=workflow.id,
            owner_id=owner.id,
            expected_version=0,
            definition={"schema_version": "1.0", "nodes": [], "edges": []},
        )
        run = ExecutionRepository(session).create_run(
            workflow_id=workflow.id, version_id=version.id, owner_id=owner.id, input_json={}
        )
        return run.id, owner.id


def test_duplicate_claims_serialize_and_fence_loser(
    repository_database: Database, owned_run
) -> None:
    run_id, _ = owned_run
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        with repository_database.unit_of_work() as session:
            return ClaimRepository(session).acquire(run_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(claim), pool.submit(claim)
        results = [a.result(10), b.result(10)]
    assert sum(result is not None for result in results) == 1
    assert next(result for result in results if result is not None).generation == 1


def test_expired_claim_cannot_mutate_after_takeover(
    repository_database: Database, owned_run
) -> None:
    run_id, _ = owned_run
    with repository_database.unit_of_work() as session:
        first = ClaimRepository(session).acquire(run_id)
    assert first is not None
    with repository_database.unit_of_work() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(minutes=1)
    with repository_database.unit_of_work() as session:
        second = ClaimRepository(session).acquire(run_id)
        assert second is not None and second.generation == 2 and second.token != first.token
    for action in ("assert_current", "renew", "release"):
        with repository_database.unit_of_work() as session, pytest.raises(ClaimLostError):
            getattr(ClaimRepository(session), action)(first)
    with repository_database.unit_of_work() as session:
        assert ClaimRepository(session).assert_current(second).id == run_id
        ClaimRepository(session).renew(second)
        ClaimRepository(session).release(second)
    with repository_database.unit_of_work() as session:
        third = ClaimRepository(session).acquire(run_id)
        assert third is not None and third.generation == 3


def test_cancellation_and_running_state_refuse_claims(
    repository_database: Database, owned_run
) -> None:
    run_id, owner = owned_run
    with repository_database.unit_of_work() as session:
        claim = ClaimRepository(session).acquire(run_id)
        assert claim is not None
    with repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.CANCELLED
        )
    with repository_database.unit_of_work() as session:
        assert ClaimRepository(session).acquire(run_id) is None
        with pytest.raises(ClaimLostError):
            ClaimRepository(session).assert_current(claim)
        assert ClaimRepository(session).acquire(uuid4()) is None


def test_running_recovery_is_not_claimed_without_persisted_progress(
    repository_database: Database, owned_run
) -> None:
    run_id, owner = owned_run
    with repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.RUNNING
        )
    with repository_database.unit_of_work() as session:
        assert ClaimRepository(session).acquire(run_id) is None


def test_acquisition_rolls_back_with_caller_transaction(
    repository_database: Database, owned_run
) -> None:
    run_id, _ = owned_run
    with pytest.raises(RuntimeError), repository_database.unit_of_work() as session:
        assert ClaimRepository(session).acquire(run_id) is not None
        raise RuntimeError("rollback")
    with repository_database.session() as session:
        assert session.scalar(select(RunClaim).where(RunClaim.run_id == run_id)) is None


@pytest.mark.parametrize("duration", [0, 4, 3601, True])
def test_invalid_lease_bounds_are_rejected(
    repository_database: Database, owned_run, duration: int
) -> None:
    run_id, _ = owned_run
    with repository_database.session() as session, pytest.raises(ValueError):
        ClaimRepository(session).acquire(run_id, lease_seconds=duration)


def test_database_prevents_claim_deletion_and_generation_regression(
    repository_database: Database, owned_run
) -> None:
    run_id, _ = owned_run
    with repository_database.unit_of_work() as session:
        claim = ClaimRepository(session).acquire(run_id)
        assert claim is not None
    for statement in [
        "DELETE FROM run_claims",
        "TRUNCATE run_claims",
        "UPDATE run_claims SET generation=0",
        "UPDATE run_claims SET generation=3",
    ]:
        with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
            schema = session.get_bind().get_execution_options()["schema_translate_map"][None]
            session.execute(text(statement.replace("run_claims", f'"{schema}".run_claims')))


def test_fenced_transition_checks_and_mutates_under_same_run_lock(
    repository_database: Database, owned_run
) -> None:
    run_id, owner = owned_run
    with repository_database.unit_of_work() as session:
        first = ClaimRepository(session).acquire(run_id)
    assert first is not None
    with repository_database.unit_of_work() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(minutes=1)
    with repository_database.unit_of_work() as session:
        second = ClaimRepository(session).acquire(run_id)
    assert second is not None
    with pytest.raises(ClaimLostError), repository_database.unit_of_work() as session:
        ClaimRepository(session).assert_current(first)
        ExecutionRepository(session).transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.RUNNING
        )
    with repository_database.unit_of_work() as session:
        ClaimRepository(session).assert_current(second)
        run = ExecutionRepository(session).transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.RUNNING
        )
        assert run.status == RunStatus.RUNNING
