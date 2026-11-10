"""Retry deadlines survive delivery, cancellation and transactional failures."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from time import monotonic, sleep

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.infrastructure.database.models import NodeRetry, RunClaim, WorkflowDispatch
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.claims.repository import ClaimLostError, ClaimRepository
from app.modules.executions import worker_runner
from app.modules.executions.dispatch import enqueue_run, schedule_recovery
from app.modules.executions.exceptions import ExecutionConflictError
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import EventType, FailureCode, NodeStatus, RunStatus
from app.modules.executions.worker_runner import PureWorkerRunner
from app.modules.executions.worker_state import WorkerState
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.models import OutboxMessage
from app.modules.workflows.repository import WorkflowRepository
from app.workers.workflow_tasks import consume_workflow

pytestmark = pytest.mark.integration
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "select",
            "type": "transform",
            "config": {"operation": "pick_fields", "fields": ["CustomerID"]},
        },
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "a", "source": "start", "target": "select"},
        {"id": "b", "source": "select", "target": "end"},
    ],
}


@pytest.fixture
def create_run(repository_database: Database):
    with repository_database.unit_of_work() as session:
        owner = UserRepository(session).add(
            email="retry@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Retry")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owner.id, expected_version=0, definition=GRAPH
        )
        owner_id, workflow_id, version_id = owner.id, workflow.id, version.id

    def create(*, budget=3, base=1, cap=2):
        with repository_database.unit_of_work() as session:
            run = ExecutionRepository(session).create_run(
                workflow_id=workflow_id,
                version_id=version_id,
                owner_id=owner_id,
                input_json={"CustomerID": 42, "CaseKey": {"ID": 7}},
                max_attempts=budget,
            )
            enqueue_run(session, run.id, retry_base_seconds=base, retry_max_seconds=cap)
            return run.id, owner_id

    return create


def detail(database, run_id, owner):
    return ExecutionService(database).get(run_id=run_id, owner_id=owner)


def wait_due(database, due_at):
    deadline = monotonic() + 6
    while monotonic() < deadline:
        with database.session() as session:
            now = session.scalar(select(func.clock_timestamp()))
        if now is not None and now >= due_at:
            return
        sleep(0.03)
    pytest.fail("Retry did not become due within the test deadline")


def transient(monkeypatch, *, always=False):
    execute = worker_runner.execute_node
    calls = []

    def wrapped(node, data, **kwargs):
        if node.id == "select":
            calls.append(node.id)
            if always or len(calls) == 1:
                raise RuntimeError("Synthetic transient computation failure")
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", wrapped)
    return calls


def test_failure_deadline_event_and_claim_release_commit_together(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run(base=30, cap=60)
    transient(monkeypatch)
    captured = []
    original = ClaimRepository.acquire_for_recovery

    def capture(self, *args, **kwargs):
        claim = original(self, *args, **kwargs)
        captured.append(claim)
        return claim

    monkeypatch.setattr(ClaimRepository, "acquire_for_recovery", capture)
    assert PureWorkerRunner(repository_database, require_dispatch=True).run(
        run_id=run_id, owner_id=owner
    )
    state = detail(repository_database, run_id, owner)
    assert state.status == RunStatus.RUNNING
    assert state.retry_node_id == "select" and state.next_retry_attempt == 2
    assert state.next_retry_at is not None
    failed = state.node_runs[-1]
    assert failed.status == NodeStatus.FAILED and failed.error_code == FailureCode.INTERNAL_FAILURE
    assert failed.retry is not None and failed.retry.due_at == state.next_retry_at
    assert (failed.retry.due_at - failed.retry.scheduled_at).total_seconds() == 30
    assert state.node_runs[0].output == {"CustomerID": 42, "CaseKey": {"ID": 7}}
    with repository_database.session() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_token is None and slot.lease_until is None
        events = ExecutionRepository(session).events_owned(run_id=run_id, owner_id=owner)
        assert events[-1].event_type == EventType.NODE_RETRY_SCHEDULED
        assert events[-1].node_run_id == failed.id
        assert events[-1].event_payload["retry_at"] == state.next_retry_at.isoformat()
        assert [row.sequence for row in events] == list(range(1, len(events) + 1))
    with pytest.raises(ClaimLostError):
        WorkerState(repository_database, owner_id=owner, claim=captured[0]).renew()


def test_duplicate_delivery_and_scan_cannot_start_a_retry_early(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run(base=30, cap=60)
    calls = transient(monkeypatch)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    before = detail(repository_database, run_id, owner)
    with repository_database.session() as session:
        message = session.scalar(select(OutboxMessage.id))
    consume_workflow(repository_database, str(message))
    assert not PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    with repository_database.unit_of_work() as session:
        assert ClaimRepository(session).acquire_for_recovery(run_id) is None
    OutboxDispatcher(
        repository_database, lambda _: None, publish_workflow=lambda _: None
    ).dispatch_once()
    with repository_database.unit_of_work() as session:
        delivery = session.get(WorkflowDispatch, run_id)
        assert delivery is not None
        delivery.next_dispatch_at -= timedelta(hours=1)
    assert schedule_recovery(repository_database) == 0
    assert calls == ["select"]
    assert detail(repository_database, run_id, owner) == before


def test_due_retry_consumes_deadline_with_new_attempt_and_reuses_upstream_output(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run()
    calls = transient(monkeypatch)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    before = detail(repository_database, run_id, owner)
    assert before.next_retry_at is not None
    wait_due(repository_database, before.next_retry_at)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = detail(repository_database, run_id, owner)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"CustomerID": 42}
    assert completed.node_runs[0] == before.node_runs[0]
    assert [(row.node_id, row.attempt_number, row.status) for row in completed.node_runs] == [
        ("start", 1, NodeStatus.SUCCEEDED),
        ("select", 1, NodeStatus.FAILED),
        ("select", 2, NodeStatus.SUCCEEDED),
        ("end", 1, NodeStatus.SUCCEEDED),
    ]
    assert completed.next_retry_at is None and completed.retry_node_id is None
    retry = completed.node_runs[1].retry
    assert retry is not None and retry.resumed_at is not None and retry.resumed_at >= retry.due_at
    assert retry.due_at == before.next_retry_at and retry.cancelled_at is None
    assert calls == ["select", "select"]


def test_exponential_delays_stop_at_saved_budget(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run(budget=3, base=1, cap=2)
    calls = transient(monkeypatch, always=True)
    for expected_delay in (1, 2):
        assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
        state = detail(repository_database, run_id, owner)
        retry = state.node_runs[-1].retry
        assert retry is not None
        assert (retry.due_at - retry.scheduled_at).total_seconds() == expected_delay
        wait_due(repository_database, retry.due_at)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    state = detail(repository_database, run_id, owner)
    assert state.status == RunStatus.FAILED and state.error_code == FailureCode.INTERNAL_FAILURE
    assert state.next_retry_at is None and len(calls) == 3
    assert len([row for row in state.node_runs if row.retry is not None]) == 2
    assert not PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    assert schedule_recovery(repository_database) == 0


@pytest.mark.parametrize("code", [FailureCode.INPUT_MAPPING_FAILED, FailureCode.EXECUTION_FAILED])
def test_deterministic_failures_never_schedule_retry(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
    code,
) -> None:
    run_id, owner = create_run()
    execute = worker_runner.execute_node

    def fail(node, data, **kwargs):
        if node.id == "select":
            raise NodeExecutionError(code)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", fail)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    state = detail(repository_database, run_id, owner)
    assert state.status == RunStatus.FAILED and state.error_code == code
    assert all(row.retry is None for row in state.node_runs)


def test_single_attempt_budget_has_no_scheduled_retry(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run(budget=1)
    transient(monkeypatch, always=True)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    state = detail(repository_database, run_id, owner)
    assert state.status == RunStatus.FAILED and state.next_retry_at is None
    assert all(row.retry is None for row in state.node_runs)


def test_cancellation_closes_retry_and_later_delivery_cannot_revive_run(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run()
    transient(monkeypatch)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    waiting = detail(repository_database, run_id, owner)
    assert waiting.next_retry_at is not None
    cancelled = ExecutionService(repository_database).cancel(run_id=run_id, owner_id=owner)
    assert cancelled.status == RunStatus.CANCELLED and cancelled.next_retry_at is None
    assert cancelled.node_runs[-1].retry is not None
    assert cancelled.node_runs[-1].retry.cancelled_at is not None
    wait_due(repository_database, waiting.next_retry_at)
    with repository_database.session() as session:
        message = session.scalar(select(OutboxMessage.id))
    consume_workflow(repository_database, str(message))
    assert detail(repository_database, run_id, owner) == cancelled
    assert schedule_recovery(repository_database) == 0


def test_scheduling_event_failure_rolls_back_failure_deadline_and_release(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run()
    transient(monkeypatch)
    original = ExecutionRepository._event

    def fail(self, run, event_type, *args, **kwargs):
        if event_type == EventType.NODE_RETRY_SCHEDULED:
            raise OperationalError("synthetic", {}, Exception())
        return original(self, run, event_type, *args, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "_event", fail)
    with pytest.raises(OperationalError):
        PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    state = detail(repository_database, run_id, owner)
    assert state.status == RunStatus.RUNNING and state.node_runs[-1].status == NodeStatus.RUNNING
    assert state.next_retry_at is None and state.node_runs[-1].retry is None
    with repository_database.session() as session:
        assert not session.scalars(select(NodeRetry)).all()
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_token is not None


def test_retry_resume_event_failure_rolls_back_new_attempt_and_deadline_resolution(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run()
    transient(monkeypatch)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    before = detail(repository_database, run_id, owner)
    assert before.next_retry_at is not None
    wait_due(repository_database, before.next_retry_at)
    original = ExecutionRepository._event

    def fail(self, run, event_type, payload, *args, **kwargs):
        if event_type == EventType.NODE_CREATED and payload.get("attempt_number") == 2:
            raise OperationalError("synthetic", {}, Exception())
        return original(self, run, event_type, payload, *args, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "_event", fail)
    with pytest.raises(OperationalError):
        PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    assert detail(repository_database, run_id, owner) == before


def test_deadlines_and_policy_are_immutable_and_cannot_be_resolved_without_resume(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run(base=30, cap=60)
    transient(monkeypatch)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    before = detail(repository_database, run_id, owner)
    schema = repository_database.engine.get_execution_options()["schema_translate_map"][None]
    for sql in (
        f"UPDATE \"{schema}\".node_retries SET due_at=due_at-interval '1 second'",
        f'UPDATE "{schema}".node_retries SET resumed_at=clock_timestamp()',
        f'UPDATE "{schema}".node_retries SET cancelled_at=clock_timestamp()',
        f'DELETE FROM "{schema}".node_retries',
        f'TRUNCATE "{schema}".node_retries',
        f'UPDATE "{schema}".workflow_dispatches SET retry_base_seconds=2',
    ):
        with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
            session.execute(text(sql))
    assert detail(repository_database, run_id, owner) == before


def test_cancellation_racing_due_retry_resolves_history_once(
    repository_database: Database,
    create_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = create_run()
    transient(monkeypatch)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    waiting = detail(repository_database, run_id, owner)
    assert waiting.next_retry_at is not None
    wait_due(repository_database, waiting.next_retry_at)
    gate = Barrier(2)

    def resume():
        gate.wait(5)
        consume_workflow(repository_database, message)

    def cancel():
        gate.wait(5)
        try:
            ExecutionService(repository_database).cancel(run_id=run_id, owner_id=owner)
        except ExecutionConflictError:
            pass  # Terminal success can win before cancellation obtains the lock.

    with repository_database.session() as session:
        message = str(session.scalar(select(OutboxMessage.id)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(resume), pool.submit(cancel)
        a.result(10)
        b.result(10)
    retained = detail(repository_database, run_id, owner)
    assert retained.status in {RunStatus.SUCCEEDED, RunStatus.CANCELLED}
    retry = retained.node_runs[1].retry
    assert retry is not None
    assert (retry.resumed_at is None) != (retry.cancelled_at is None)
    consume_workflow(repository_database, message)
    assert detail(repository_database, run_id, owner) == retained
