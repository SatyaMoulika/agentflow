"""Actual pure execution, process interruption and lease races on disposable PostgreSQL."""

import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool

from app.infrastructure.database.models import NodeRun, RunClaim, WorkflowRun
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.claims.repository import ClaimLostError, ClaimRepository
from app.modules.executions import worker_runner
from app.modules.executions.exceptions import ExecutionNotFoundError, WorkflowNotExecutableError
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.recovery import InconsistentHistoryError
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import FailureCode, NodeStatus, RunStatus
from app.modules.executions.worker_runner import PureWorkerRunner
from app.modules.executions.worker_state import WorkerState
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration

GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "choose",
            "type": "condition",
            "config": {"field": "$.start.output.Amount", "operator": "greater_than", "value": 10},
        },
        {
            "id": "double",
            "type": "calculator",
            "config": {
                "operation": "multiply",
                "operands": [
                    {"kind": "output", "path": "$.start.output.Amount"},
                    {"kind": "literal", "value": 2},
                ],
            },
        },
        {
            "id": "plus",
            "type": "calculator",
            "config": {
                "operation": "add",
                "operands": [
                    {"kind": "output", "path": "$.start.output.Amount"},
                    {"kind": "literal", "value": 1},
                ],
            },
        },
        {"id": "join", "type": "merge", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "a", "source": "start", "target": "choose"},
        {"id": "b", "source": "choose", "target": "double", "source_handle": "true"},
        {"id": "c", "source": "choose", "target": "plus", "source_handle": "false"},
        {"id": "d", "source": "double", "target": "join"},
        {"id": "e", "source": "plus", "target": "join"},
        {"id": "f", "source": "join", "target": "end"},
    ],
}


@pytest.fixture
def make_run(repository_database: Database):
    def create(*, graph=None, data=None, max_attempts=2):
        with repository_database.unit_of_work() as session:
            owner = UserRepository(session).add(
                email=f"worker-{uuid4().hex}@example.com",
                display_name="Worker",
                password_hash="fixture",
            )
            workflows = WorkflowRepository(session)
            workflow = workflows.add(owner_id=owner.id, name="Pure worker")
            version = workflows.append_version(
                workflow_id=workflow.id,
                owner_id=owner.id,
                expected_version=0,
                definition=deepcopy(GRAPH if graph is None else graph),
            )
            run = ExecutionRepository(session).create_run(
                workflow_id=workflow.id,
                version_id=version.id,
                owner_id=owner.id,
                input_json={"Amount": 11, "CaseKey": {"ID": 7}} if data is None else data,
                max_attempts=max_attempts,
            )
            return run.id, owner.id

    return create


def expire(database: Database, run_id) -> None:
    with database.unit_of_work() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(hours=1)


def start(database: Database, run_id, owner):
    with database.unit_of_work() as session:
        claim = ClaimRepository(session).acquire(run_id)
        assert claim is not None
    worker = WorkerState(database, owner_id=owner, claim=claim)
    worker.transition_run(expected_revision=0, target=RunStatus.RUNNING)
    return claim, worker


def result(database: Database, run_id, owner):
    return ExecutionService(database).get(run_id=run_id, owner_id=owner)


@pytest.mark.parametrize(
    ("amount", "chosen", "skipped", "expected"),
    [
        (11, "double", "plus", 22),
        (4, "plus", "double", 5),
    ],
)
def test_real_branches_execute_without_open_transactions(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
    amount,
    chosen,
    skipped,
    expected,
) -> None:
    run_id, owner = make_run(data={"Amount": amount, "CaseKey": {"ID": 7}})
    execute = worker_runner.execute_node
    seen = []
    pool = repository_database.engine.pool
    assert isinstance(pool, QueuePool)
    baseline = pool.checkedout()

    def unlocked(node, data, **kwargs):
        assert pool.checkedout() == baseline
        with repository_database.session() as session:
            assert (
                session.scalar(
                    select(WorkflowRun.id)
                    .where(WorkflowRun.id == run_id)
                    .with_for_update(nowait=True)
                )
                == run_id
            )
        seen.append(node.id)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", unlocked)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = result(repository_database, run_id, owner)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"result": expected}
    assert seen == ["start", "choose", chosen, "join", "end"]
    rows = {row.node_id: row for row in completed.node_runs}
    assert rows["start"].output == {"Amount": amount, "CaseKey": {"ID": 7}}
    assert rows[skipped].status == NodeStatus.SKIPPED
    assert rows[skipped].output is None and rows[skipped].started_at is None
    with repository_database.session() as session:
        events = ExecutionRepository(session).events_owned(run_id=run_id, owner_id=owner)
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert not PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    assert result(repository_database, run_id, owner) == completed


@pytest.mark.parametrize("status", [NodeStatus.PENDING, NodeStatus.RUNNING])
@pytest.mark.parametrize("budget", [1, 2])
def test_interrupted_attempt_consumes_saved_budget_and_keeps_history(
    repository_database: Database,
    make_run,
    status: NodeStatus,
    budget: int,
) -> None:
    run_id, owner = make_run(max_attempts=budget)
    old, worker = start(repository_database, run_id, owner)
    if status == NodeStatus.RUNNING:
        interrupted_id = worker.start_attempt(
            expected_run_revision=1, node_id="start", input_data={"Amount": 11}
        )
    else:
        with repository_database.unit_of_work() as session:
            interrupted_id = (
                ExecutionRepository(session)
                .add_attempt(
                    run_id=run_id,
                    owner_id=owner,
                    expected_run_revision=1,
                    node_id="start",
                    input_json={"Amount": 11},
                )
                .id
            )
    expire(repository_database, run_id)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = result(repository_database, run_id, owner)
    first = next(row for row in completed.node_runs if row.id == interrupted_id)
    assert first.status == NodeStatus.FAILED and first.error_code == FailureCode.INTERNAL_FAILURE
    assert first.output is None and first.completed_at is not None
    if budget == 1:
        assert completed.status == RunStatus.FAILED
        assert len(completed.node_runs) == 1
    else:
        assert completed.status == RunStatus.SUCCEEDED
        starts = [row for row in completed.node_runs if row.node_id == "start"]
        assert [row.attempt_number for row in starts] == [1, 2]
        assert starts[1].output == {"Amount": 11, "CaseKey": {"ID": 7}}
    with pytest.raises(ClaimLostError):
        worker.renew()
    with repository_database.session() as session:
        slot = session.get(RunClaim, run_id)
        assert slot is not None and slot.generation == old.generation + 1


@pytest.mark.parametrize(
    ("code", "budget", "succeeds"),
    [
        (FailureCode.INTERNAL_FAILURE, 2, True),
        (FailureCode.DEADLINE_EXCEEDED, 2, True),
        (FailureCode.INTERNAL_FAILURE, 1, False),
        (FailureCode.EXECUTION_FAILED, 2, False),
        (FailureCode.INPUT_MAPPING_FAILED, 2, False),
    ],
)
def test_recovery_of_committed_failure_preserves_retry_policy(
    repository_database: Database,
    make_run,
    code: FailureCode,
    budget: int,
    succeeds: bool,
) -> None:
    run_id, owner = make_run(max_attempts=budget)
    _, worker = start(repository_database, run_id, owner)
    attempt = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={})
    worker.finish_attempt(
        expected_run_revision=1,
        attempt_id=attempt,
        expected_revision=1,
        target=NodeStatus.FAILED,
        error_code=code,
    )
    expire(repository_database, run_id)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = result(repository_database, run_id, owner)
    assert completed.status == (RunStatus.SUCCEEDED if succeeds else RunStatus.FAILED)
    if not succeeds:
        assert completed.error_code == code and len(completed.node_runs) == 1


@pytest.mark.parametrize("transient", [True, False])
def test_actual_node_failures_retry_only_transient_errors(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
    transient: bool,
) -> None:
    run_id, owner = make_run()
    execute = worker_runner.execute_node
    calls = 0

    def fail(node, data, **kwargs):
        nonlocal calls
        if node.id == "double":
            calls += 1
            if calls == 1:
                if transient:
                    raise RuntimeError("synthetic unlogged failure")
                raise NodeExecutionError(FailureCode.EXECUTION_FAILED)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", fail)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = result(repository_database, run_id, owner)
    assert completed.status == (RunStatus.SUCCEEDED if transient else RunStatus.FAILED)
    assert calls == (2 if transient else 1)
    attempts = [row for row in completed.node_runs if row.node_id == "double"]
    assert attempts[0].status == NodeStatus.FAILED
    if not transient:
        assert all(row.node_id not in {"join", "end", "plus"} for row in completed.node_runs)


def test_real_process_kill_recovers_selected_route_and_fences_dead_worker(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = make_run()
    schema = repository_database.engine.get_execution_options()["schema_translate_map"][None]
    # This child opens its own engine using only the guarded test URL. It never loads
    # settings or the private .env and exits while an actual selected node is running.
    script = """
import os, signal, sys
from uuid import UUID
from pydantic import SecretStr
from app.infrastructure.database.session import Database
from app.modules.executions import worker_runner
db = Database(SecretStr(os.environ['TEST_DATABASE_URL']))
db.engine = db.engine.execution_options(schema_translate_map={None: sys.argv[1]})
db.session_factory.configure(bind=db.engine)
execute = worker_runner.execute_node
def interrupted(node, data, **kwargs):
    if node.id == 'double':
        os.kill(os.getpid(), signal.SIGKILL)
    return execute(node, data, **kwargs)
worker_runner.execute_node = interrupted
worker_runner.PureWorkerRunner(db).run(run_id=UUID(sys.argv[2]), owner_id=UUID(sys.argv[3]))
"""
    process = subprocess.run(
        [sys.executable, "-c", script, schema, str(run_id), str(owner)],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert process.returncode == -signal.SIGKILL
    interrupted = result(repository_database, run_id, owner)
    assert interrupted.status == RunStatus.RUNNING
    assert [(row.node_id, row.status) for row in interrupted.node_runs] == [
        ("start", NodeStatus.SUCCEEDED),
        ("choose", NodeStatus.SUCCEEDED),
        ("double", NodeStatus.RUNNING),
    ]
    before = interrupted.node_runs[:2]
    execute = worker_runner.execute_node
    seen = []

    def resumed(node, data, **kwargs):
        seen.append(node.id)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", resumed)
    expire(repository_database, run_id)
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = result(repository_database, run_id, owner)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"result": 22}
    assert completed.node_runs[:2] == before
    assert seen == ["double", "join", "end"]
    doubles = [row for row in completed.node_runs if row.node_id == "double"]
    assert [(row.attempt_number, row.status) for row in doubles] == [
        (1, NodeStatus.FAILED),
        (2, NodeStatus.SUCCEEDED),
    ]


@pytest.mark.parametrize("running", [False, True])
def test_any_groq_branch_is_refused_before_claim_change(
    repository_database: Database,
    make_run,
    running: bool,
) -> None:
    graph = deepcopy(GRAPH)
    # This is the unselected branch for Amount=11. The entire graph must be pure.
    graph["nodes"][3] = {
        "id": "plus",
        "type": "groq",
        "config": {"instruction": "Summarize", "input_field": "message"},
    }
    run_id, owner = make_run(graph=graph)
    if running:
        start(repository_database, run_id, owner)
        expire(repository_database, run_id)
    before = result(repository_database, run_id, owner)
    with repository_database.session() as session:
        slot = session.get(RunClaim, run_id)
        generation = slot.generation if slot is not None else None
    with pytest.raises(WorkflowNotExecutableError):
        PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    assert result(repository_database, run_id, owner) == before
    with repository_database.session() as session:
        slot = session.get(RunClaim, run_id)
        assert (slot.generation if slot is not None else None) == generation


def test_unclaimed_synchronous_running_run_cannot_be_taken_over(
    repository_database: Database,
    make_run,
) -> None:
    run_id, owner = make_run()
    with repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_run(
            run_id=run_id, owner_id=owner, expected_revision=0, target=RunStatus.RUNNING
        )
    before = result(repository_database, run_id, owner)
    assert not PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    assert result(repository_database, run_id, owner) == before
    with repository_database.session() as session:
        assert session.get(RunClaim, run_id) is None


def test_owner_is_checked_before_acquiring_claim(repository_database: Database, make_run) -> None:
    run_id, owner = make_run()
    _, other = make_run()
    with pytest.raises(ExecutionNotFoundError):
        PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=other)
    with pytest.raises(ExecutionNotFoundError):
        PureWorkerRunner(repository_database).run(run_id=uuid4(), owner_id=owner)
    with repository_database.session() as session:
        assert session.get(RunClaim, run_id) is None


def test_duplicate_delivery_and_cancellation_during_computation(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = make_run()
    entered, release = Event(), Event()
    execute = worker_runner.execute_node

    def paused(node, data, **kwargs):
        entered.set()
        assert release.wait(10)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(
            PureWorkerRunner(repository_database).run, run_id=run_id, owner_id=owner
        )
        try:
            assert entered.wait(10)
            assert not PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
            cancelled = ExecutionService(repository_database).cancel(run_id=run_id, owner_id=owner)
        finally:
            release.set()
        with pytest.raises(ClaimLostError):
            active.result(10)
    assert result(repository_database, run_id, owner) == cancelled
    assert cancelled.status == RunStatus.CANCELLED


def test_expired_worker_result_is_rejected_after_takeover(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = make_run()
    entered, release = Event(), Event()
    execute = worker_runner.execute_node
    first = True

    def paused(node, data, **kwargs):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(10)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        old = pool.submit(PureWorkerRunner(repository_database).run, run_id=run_id, owner_id=owner)
        try:
            assert entered.wait(10)
            expire(repository_database, run_id)
            assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
            completed = result(repository_database, run_id, owner)
        finally:
            release.set()
        with pytest.raises(ClaimLostError):
            old.result(10)
    assert completed.status == RunStatus.SUCCEEDED
    assert result(repository_database, run_id, owner) == completed


def test_exhausted_interruption_and_events_roll_back_together(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = make_run(max_attempts=1)
    _, worker = start(repository_database, run_id, owner)
    attempt_id = worker.start_attempt(expected_run_revision=1, node_id="start", input_data={})
    before = result(repository_database, run_id, owner)
    original = ExecutionRepository._event
    count = 0

    def fail_second(self, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OperationalError("synthetic", {}, Exception())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "_event", fail_second)
    with pytest.raises(OperationalError):
        worker.reconcile_attempt(expected_run_revision=1)
    assert result(repository_database, run_id, owner) == before
    with repository_database.session() as session:
        attempt = session.get(NodeRun, attempt_id)
        assert attempt is not None and attempt.status == NodeStatus.RUNNING


def test_inconsistent_history_never_executes_nodes(
    repository_database: Database,
    make_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id, owner = make_run()
    _, worker = start(repository_database, run_id, owner)
    # A future node was attempted before the entry; state storage alone does not
    # promise a valid selected route, so recovery must reject this history.
    worker.start_attempt(expected_run_revision=1, node_id="end", input_data={})
    expire(repository_database, run_id)
    before = result(repository_database, run_id, owner)

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid history reached node execution")

    monkeypatch.setattr(worker_runner, "execute_node", forbidden)
    with pytest.raises(InconsistentHistoryError):
        PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    assert result(repository_database, run_id, owner) == before


def test_recovery_keeps_original_version_after_workflow_edit(
    repository_database: Database,
    make_run,
) -> None:
    run_id, owner = make_run()
    original = result(repository_database, run_id, owner)
    new_graph = deepcopy(GRAPH)
    new_graph["nodes"][2]["config"]["operands"][1]["value"] = 100
    with repository_database.unit_of_work() as session:
        WorkflowRepository(session).append_version(
            workflow_id=original.workflow_id,
            owner_id=owner,
            expected_version=1,
            definition=new_graph,
        )
    assert PureWorkerRunner(repository_database).run(run_id=run_id, owner_id=owner)
    completed = result(repository_database, run_id, owner)
    assert completed.workflow_version_id == original.workflow_version_id
    assert completed.output == {"result": 22}
