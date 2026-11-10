"""Actual transactions persist execution history without executing any node."""

from copy import deepcopy
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

from app.infrastructure.database.models import (
    ExecutionEvent,
    NodeRun,
    WorkflowRun,
)
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.executions.exceptions import (
    ExecutionConflictError,
    ExecutionNotFoundError,
    InvalidExecutionDataError,
)
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import FailureCode, InvalidTransitionError, NodeStatus, RunStatus
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "step", "type": "transform", "config": {"operation": "identity"}},
        {"id": "finish", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "step"},
        {"id": "e2", "source": "step", "target": "finish"},
    ],
}


@pytest.fixture
def execution_context(repository_database: Database) -> dict[str, UUID]:
    result = {}
    with repository_database.unit_of_work() as session:
        for label in ("a", "b"):
            user = UserRepository(session).add(
                email=f"{label}@execution.example.com",
                password_hash="fixture",
                display_name=label,
            )
            workflow = WorkflowRepository(session).add(owner_id=user.id, name=f"{label} workflow")
            version = WorkflowRepository(session).append_version(
                workflow_id=workflow.id,
                owner_id=user.id,
                expected_version=0,
                definition=GRAPH,
            )
            result.update(
                {
                    f"owner_{label}": user.id,
                    f"workflow_{label}": workflow.id,
                    f"version_{label}": version.id,
                }
            )
    return result


def create_run(
    database: Database, context: dict[str, UUID], label: str = "a", start: bool = False
) -> UUID:
    with database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        run = repository.create_run(
            workflow_id=context[f"workflow_{label}"],
            version_id=context[f"version_{label}"],
            owner_id=context[f"owner_{label}"],
            input_json={"CustomerID": 12},
        )
        if start:
            repository.transition_run(
                run_id=run.id,
                owner_id=context[f"owner_{label}"],
                expected_revision=0,
                target=RunStatus.RUNNING,
            )
        return run.id


def test_lifecycle_retry_attempts_events_and_version_binding_are_durable(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    context = execution_context
    source = {"CustomerID": 123, "nested": [1, False, None]}
    expected_input = deepcopy(source)
    with repository_database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        run = repository.create_run(
            workflow_id=context["workflow_a"],
            version_id=context["version_a"],
            owner_id=context["owner_a"],
            input_json=source,
        )
        run_id = run.id
        source["nested"].append("private-source-change")
        assert run.input_json == expected_input
        repository.transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=0,
            target=RunStatus.RUNNING,
        )
        first = repository.add_attempt(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="step",
            input_json={"private_input": "private-value"},
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=first.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=first.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.FAILED,
            error_code=FailureCode.EXECUTION_FAILED,
        )
        second = repository.add_attempt(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="step",
            input_json={"CustomerID": 123},
        )
        assert first.attempt_number == 1 and second.attempt_number == 2
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=second.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=second.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output={"private_output": "private-value"},
        )
        end = repository.add_attempt(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="finish",
            input_json={},
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=end.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=end.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output={},
        )
        repository.transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=1,
            target=RunStatus.SUCCEEDED,
            output={"result": True},
        )
        assert run.event_sequence == 12 and run.revision == 2
    with repository_database.unit_of_work() as session:
        workflows = WorkflowRepository(session)
        workflows.append_version(
            workflow_id=context["workflow_a"],
            owner_id=context["owner_a"],
            expected_version=1,
            definition=GRAPH | {"metadata": {"revision": 2}},
        )
        workflow = workflows.lock_owned(
            workflow_id=context["workflow_a"], owner_id=context["owner_a"]
        )
        assert workflow is not None
        workflows.archive(workflow)
    with repository_database.session() as session:
        repository = ExecutionRepository(session)
        loaded = repository.get_owned(run_id=run_id, owner_id=context["owner_a"])
        assert loaded is not None and loaded.status == RunStatus.SUCCEEDED
        assert loaded.version.id == context["version_a"] and loaded.input_json == expected_input
        assert loaded.output_json == {"result": True}
        assert loaded.completed_at is not None and loaded.started_at is not None
        assert loaded.completed_at >= loaded.started_at >= loaded.created_at
        assert loaded.created_at.utcoffset() == timedelta(0)
        events = repository.events_owned(run_id=run_id, owner_id=context["owner_a"])
        assert [event.sequence for event in events] == list(range(1, 13))
        assert "private-value" not in str([event.event_payload for event in events])
        assert [
            event.sequence
            for event in repository.events_owned(
                run_id=run_id, owner_id=context["owner_a"], after_sequence=10, limit=1
            )
        ] == [11]
        assert all(
            attempt.duration_ms is not None and attempt.duration_ms >= 0
            for attempt in loaded.attempts
        )
        assert len(loaded.events) == 12


@pytest.mark.parametrize("operation", ["create", "start", "attempt", "result"])
def test_post_event_flush_failure_rolls_back_entire_operation_and_recovers(
    repository_database: Database,
    execution_context: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    context = execution_context
    run_id = None
    attempt_id = None
    if operation != "create":
        run_id = create_run(repository_database, context, start=operation in {"attempt", "result"})
    if operation == "result":
        assert run_id is not None
        with repository_database.unit_of_work() as session:
            attempt_id = (
                ExecutionRepository(session)
                .add_attempt(
                    run_id=run_id,
                    owner_id=context["owner_a"],
                    expected_run_revision=1,
                    node_id="step",
                    input_json={},
                )
                .id
            )
    baseline = {"create": 0, "start": 1, "attempt": 2, "result": 3}[operation]
    original = ExecutionRepository._event

    def fail_after_event(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise OperationalError("private-driver", {}, RuntimeError("private-value"))

    def mutate() -> None:
        with repository_database.unit_of_work() as session:
            repository = ExecutionRepository(session)
            if operation == "create":
                repository.create_run(
                    workflow_id=context["workflow_a"],
                    version_id=context["version_a"],
                    owner_id=context["owner_a"],
                    input_json={},
                )
            elif operation == "start":
                assert run_id is not None
                repository.transition_run(
                    run_id=run_id,
                    owner_id=context["owner_a"],
                    expected_revision=0,
                    target=RunStatus.RUNNING,
                )
            elif operation == "attempt":
                assert run_id is not None
                repository.add_attempt(
                    run_id=run_id,
                    owner_id=context["owner_a"],
                    expected_run_revision=1,
                    node_id="step",
                    input_json={},
                )
            else:
                assert run_id is not None and attempt_id is not None
                repository.transition_attempt(
                    run_id=run_id,
                    attempt_id=attempt_id,
                    owner_id=context["owner_a"],
                    expected_run_revision=1,
                    expected_revision=0,
                    target=NodeStatus.RUNNING,
                )

    with monkeypatch.context() as patch:
        patch.setattr(ExecutionRepository, "_event", fail_after_event)
        with pytest.raises(OperationalError):
            mutate()
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(ExecutionEvent)) == baseline
        run = session.get(WorkflowRun, run_id) if run_id else None
        if run:
            assert run.event_sequence == baseline
            assert run.revision == (0 if operation == "start" else 1)
        assert session.scalar(select(func.count()).select_from(NodeRun)) == (
            1 if operation == "result" else 0
        )
    mutate()
    with repository_database.session() as session:
        count = session.scalar(select(func.count()).select_from(ExecutionEvent))
        assert count == baseline + 1


@pytest.mark.parametrize("operation", ["create", "read", "mutate", "events", "attempt"])
def test_owner_filters_and_mismatched_attempt_membership_are_enforced(
    repository_database: Database,
    execution_context: dict[str, UUID],
    operation: str,
) -> None:
    context = execution_context
    foreign_id = create_run(repository_database, context, label="b", start=True)
    with pytest.raises(ExecutionNotFoundError), repository_database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        if operation == "create":
            repository.create_run(
                workflow_id=context["workflow_b"],
                version_id=context["version_b"],
                owner_id=context["owner_a"],
                input_json={},
            )
        elif operation == "read":
            assert repository.get_owned(run_id=foreign_id, owner_id=context["owner_a"]) is None
            raise ExecutionNotFoundError()
        elif operation == "mutate":
            repository.transition_run(
                run_id=foreign_id,
                owner_id=context["owner_a"],
                expected_revision=1,
                target=RunStatus.CANCELLED,
            )
        elif operation == "events":
            repository.events_owned(run_id=foreign_id, owner_id=context["owner_a"])
        else:
            repository.add_attempt(
                run_id=foreign_id,
                owner_id=context["owner_a"],
                expected_run_revision=1,
                node_id="step",
                input_json={},
            )
    own_id = create_run(repository_database, context, start=True)
    with pytest.raises(ExecutionNotFoundError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_attempt(
            run_id=own_id,
            attempt_id=uuid4(),
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
    with repository_database.session() as session:
        foreign = session.get(WorkflowRun, foreign_id)
        assert (
            foreign is not None
            and foreign.status == RunStatus.RUNNING
            and foreign.event_sequence == 2
        )


def test_expected_revisions_open_attempts_results_and_terminal_states_are_checked(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    context = execution_context
    run_id = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        attempt_id = (
            ExecutionRepository(session)
            .add_attempt(
                run_id=run_id,
                owner_id=context["owner_a"],
                expected_run_revision=1,
                node_id="step",
                input_json={},
            )
            .id
        )
    for target, output, error in [
        (RunStatus.SUCCEEDED, {}, None),
        (RunStatus.FAILED, None, FailureCode.EXECUTION_FAILED),
        (RunStatus.CANCELLED, None, None),
    ]:
        with pytest.raises(ExecutionConflictError), repository_database.unit_of_work() as session:
            ExecutionRepository(session).transition_run(
                run_id=run_id,
                owner_id=context["owner_a"],
                expected_revision=1,
                target=target,
                output=output,
                error_code=error,
            )
    with pytest.raises(InvalidExecutionDataError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_attempt(
            run_id=run_id,
            attempt_id=attempt_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.FAILED,
        )
    with repository_database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        skipped = repository.transition_attempt(
            run_id=run_id,
            attempt_id=attempt_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.SKIPPED,
        )
        assert skipped.started_at is None and skipped.duration_ms == 0
        repository.transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=1,
            target=RunStatus.CANCELLED,
        )
    with pytest.raises(ExecutionConflictError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=1,
            target=RunStatus.RUNNING,
        )
    with pytest.raises(InvalidTransitionError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=2,
            target=RunStatus.RUNNING,
        )


def test_approval_reserved_states_preserve_start_time_and_reject_aba_stale_revision(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    context = execution_context
    run_id = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        attempt = repository.add_attempt(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="step",
            input_json={},
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=attempt.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        started = attempt.started_at
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=attempt.id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.WAITING_APPROVAL,
        )
        run = repository.transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=1,
            target=RunStatus.WAITING_APPROVAL,
        )
        run_start = run.started_at
        repository.transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=2,
            target=RunStatus.RUNNING,
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=attempt.id,
            owner_id=context["owner_a"],
            expected_run_revision=3,
            expected_revision=2,
            target=NodeStatus.RUNNING,
        )
        assert attempt.started_at == started and run.started_at == run_start
        attempt_id = attempt.id
    with pytest.raises(ExecutionConflictError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).transition_attempt(
            run_id=run_id,
            attempt_id=attempt_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.SUCCEEDED,
            output={},
        )


@pytest.mark.parametrize(
    "case",
    [
        "foreign_version",
        "parent_version",
        "parent_self",
        "json_type",
        "json_size",
        "status",
        "initial_revision",
        "initial_counter",
    ],
)
def test_database_rejects_invalid_run_identity_payload_and_initial_state(
    repository_database: Database,
    execution_context: dict[str, UUID],
    case: str,
) -> None:
    context = execution_context
    parent_id = create_run(repository_database, context, label="b")
    values: dict[str, Any] = {
        "id": uuid4(),
        "workflow_id": context["workflow_a"],
        "workflow_version_id": context["version_a"],
        "input_json": {},
    }
    if case == "foreign_version":
        values["workflow_version_id"] = context["version_b"]
    elif case == "parent_version":
        values["parent_run_id"] = parent_id
    elif case == "parent_self":
        values["parent_run_id"] = values["id"]
    elif case == "json_type":
        values["input_json"] = []
    elif case == "json_size":
        values["input_json"] = {"data": "x" * 1048576}
    elif case == "status":
        values["status"] = "running"
    elif case == "initial_revision":
        values["revision"] = 1
    else:
        values["event_sequence"] = 1
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        session.add(WorkflowRun(**values))
        session.flush()


@pytest.mark.parametrize(
    "case",
    [
        "unknown_node",
        "duplicate_attempt",
        "overlapping_attempt",
        "number",
        "input_type",
        "status",
        "initial_revision",
    ],
)
def test_database_enforces_saved_node_membership_and_attempt_constraints(
    repository_database: Database,
    execution_context: dict[str, UUID],
    case: str,
) -> None:
    context = execution_context
    run_id = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        ExecutionRepository(session).add_attempt(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="step",
            input_json={},
        )
    values: dict[str, Any] = {
        "workflow_run_id": run_id,
        "node_id": "finish",
        "attempt_number": 1,
        "input_json": {},
    }
    if case == "unknown_node":
        values["node_id"] = "private_nonexistent_node"
    elif case in {"duplicate_attempt", "overlapping_attempt"}:
        values["node_id"] = "step"
        if case == "overlapping_attempt":
            values["attempt_number"] = 2
    elif case == "number":
        values["attempt_number"] = 0
    elif case == "input_type":
        values["input_json"] = []
    elif case == "status":
        values["status"] = "succeeded"
    else:
        values["revision"] = 1
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        session.add(NodeRun(**values))
        session.flush()


@pytest.mark.parametrize("entity", ["run", "attempt"])
@pytest.mark.parametrize("field", ["identity", "input", "revision", "start_time", "output"])
def test_database_guards_identity_revision_and_unexplained_result_changes(
    repository_database: Database,
    execution_context: dict[str, UUID],
    entity: str,
    field: str,
) -> None:
    context = execution_context
    run_id = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        attempt_id = (
            ExecutionRepository(session)
            .add_attempt(
                run_id=run_id,
                owner_id=context["owner_a"],
                expected_run_revision=1,
                node_id="step",
                input_json={},
            )
            .id
        )
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        row = session.get(
            WorkflowRun if entity == "run" else NodeRun, run_id if entity == "run" else attempt_id
        )
        assert row is not None
        if field == "identity":
            if isinstance(row, WorkflowRun):
                row.workflow_version_id = context["version_b"]
            else:
                row.node_id = "finish"
        elif field == "input":
            row.input_json = {"changed": True}
        elif field == "revision":
            row.revision += 1
        elif field == "start_time":
            row.started_at = (
                None if entity == "run" else session.scalar(select(func.clock_timestamp()))
            )
        else:
            row.output_json = {"private": "unexplained-result"}
        session.flush()


@pytest.mark.parametrize("table", ["execution_events", "workflow_runs", "node_runs"])
@pytest.mark.parametrize("operation", ["delete", "truncate"])
def test_execution_history_is_not_deleted_by_ordinary_sql(
    repository_database: Database,
    execution_context: dict[str, UUID],
    table: str,
    operation: str,
) -> None:
    create_run(repository_database, execution_context, start=True)
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        if operation == "delete":
            model = {
                "workflow_runs": WorkflowRun,
                "node_runs": NodeRun,
                "execution_events": ExecutionEvent,
            }[table]
            session.execute(delete(model))
        else:
            schema = repository_database.engine.get_execution_options()["schema_translate_map"][
                None
            ]
            quoted = session.connection().dialect.identifier_preparer.quote_schema(schema)
            session.execute(text(f"TRUNCATE {quoted}.{table} CASCADE"))


def test_event_rows_are_immutable_and_cannot_attach_a_foreign_attempt(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    from app.modules.executions.state import EventType

    context = execution_context
    first = create_run(repository_database, context, start=True)
    second = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        attempt_id = (
            ExecutionRepository(session)
            .add_attempt(
                run_id=second,
                owner_id=context["owner_a"],
                expected_run_revision=1,
                node_id="step",
                input_json={},
            )
            .id
        )
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        session.execute(update(ExecutionEvent).values(event_payload={}))
    for values in [
        {
            "workflow_run_id": first,
            "node_run_id": attempt_id,
            "sequence": 3,
            "event_type": EventType.NODE_CREATED,
            "event_payload": {},
        },
        {
            "workflow_run_id": first,
            "sequence": 1,
            "event_type": EventType.RUN_CREATED,
            "event_payload": {},
        },
        {
            "workflow_run_id": first,
            "sequence": 0,
            "event_type": EventType.RUN_CREATED,
            "event_payload": {},
        },
        {
            "workflow_run_id": first,
            "sequence": 3,
            "event_type": EventType.NODE_CREATED,
            "event_payload": {},
        },
    ]:
        with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
            session.add(ExecutionEvent(**values))
            session.flush()


def test_attempt_membership_uses_frozen_version_and_parent_retry_links_are_exact(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    context = execution_context
    first_id = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        next_graph = deepcopy(GRAPH)
        next_graph["nodes"].append(
            {"id": "later", "type": "transform", "config": {"operation": "identity"}}
        )
        second_version = (
            WorkflowRepository(session)
            .append_version(
                workflow_id=context["workflow_a"],
                owner_id=context["owner_a"],
                expected_version=1,
                definition=next_graph,
            )
            .id
        )
        child = ExecutionRepository(session).create_run(
            workflow_id=context["workflow_a"],
            version_id=context["version_a"],
            owner_id=context["owner_a"],
            parent_run_id=first_id,
            input_json={},
        )
        assert child.parent_run_id == first_id
    with pytest.raises(ExecutionNotFoundError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).create_run(
            workflow_id=context["workflow_a"],
            version_id=second_version,
            owner_id=context["owner_a"],
            parent_run_id=first_id,
            input_json={},
        )
    with pytest.raises(ExecutionNotFoundError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).add_attempt(
            run_id=first_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="later",
            input_json={},
        )
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        session.add(
            NodeRun(workflow_run_id=first_id, node_id="later", attempt_number=1, input_json={})
        )
        session.flush()


@pytest.mark.parametrize("kind", ["terminal", "attempts", "different_nodes"])
def test_independent_connections_serialize_state_and_contiguous_event_allocation(
    repository_database: Database,
    execution_context: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    context = execution_context
    run_id = create_run(repository_database, context, start=True)
    barrier = Barrier(2, timeout=5)
    pids: set[int] = set()
    original = ExecutionRepository.lock_owned

    def synchronize(self, **kwargs):
        self.session.execute(text("SET LOCAL lock_timeout = '5s'"))
        self.session.execute(text("SET LOCAL statement_timeout = '8s'"))
        pids.add(int(self.session.scalar(text("SELECT pg_backend_pid()"))))
        cached = self.get_owned(**kwargs)
        assert cached is not None and cached.revision == 1
        barrier.wait()
        return original(self, **kwargs)

    monkeypatch.setattr(ExecutionRepository, "lock_owned", synchronize)

    def mutate(index: int) -> str:
        try:
            with repository_database.unit_of_work() as session:
                repository = ExecutionRepository(session)
                if kind == "terminal":
                    repository.transition_run(
                        run_id=run_id,
                        owner_id=context["owner_a"],
                        expected_revision=1,
                        target=RunStatus.CANCELLED if index else RunStatus.FAILED,
                        error_code=None if index else FailureCode.EXECUTION_FAILED,
                    )
                else:
                    repository.add_attempt(
                        run_id=run_id,
                        owner_id=context["owner_a"],
                        expected_run_revision=1,
                        node_id=("start" if index else "step")
                        if kind == "different_nodes"
                        else "step",
                        input_json={},
                    )
            return "committed"
        except ExecutionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(mutate, index) for index in (0, 1)]
        results = [future.result(timeout=12) for future in futures]
    assert len(pids) == 2
    assert sorted(results) == (
        ["committed", "committed"] if kind == "different_nodes" else ["committed", "conflict"]
    )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None
        expected = 4 if kind == "different_nodes" else 3
        events = ExecutionRepository(session).events_owned(
            run_id=run_id, owner_id=context["owner_a"]
        )
        assert run.event_sequence == expected
        assert [event.sequence for event in events] == list(range(1, expected + 1))
        assert run.revision == (2 if kind == "terminal" else 1)


def test_cached_attempt_is_refreshed_before_run_pause_policy(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    context = execution_context
    run_id = create_run(repository_database, context, start=True)
    with repository_database.unit_of_work() as session:
        repository = ExecutionRepository(session)
        attempt_id = repository.add_attempt(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            node_id="step",
            input_json={},
        ).id
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=attempt_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repository.transition_attempt(
            run_id=run_id,
            attempt_id=attempt_id,
            owner_id=context["owner_a"],
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.WAITING_APPROVAL,
        )
    with pytest.raises(ExecutionConflictError), repository_database.unit_of_work() as reader:
        cached = reader.get(NodeRun, attempt_id)
        assert cached is not None and cached.status == NodeStatus.WAITING_APPROVAL
        reader_pid = reader.scalar(text("SELECT pg_backend_pid()"))
        with repository_database.unit_of_work() as writer:
            assert writer.scalar(text("SELECT pg_backend_pid()")) != reader_pid
            ExecutionRepository(writer).transition_attempt(
                run_id=run_id,
                attempt_id=attempt_id,
                owner_id=context["owner_a"],
                expected_run_revision=1,
                expected_revision=2,
                target=NodeStatus.RUNNING,
            )
        ExecutionRepository(reader).transition_run(
            run_id=run_id,
            owner_id=context["owner_a"],
            expected_revision=1,
            target=RunStatus.WAITING_APPROVAL,
        )
    with repository_database.session() as session:
        run = session.get(WorkflowRun, run_id)
        assert run is not None and run.status == RunStatus.RUNNING and run.revision == 1


def test_archived_creation_and_wrong_saved_version_are_refused_without_new_history(
    repository_database: Database,
    execution_context: dict[str, UUID],
) -> None:
    context = execution_context
    with pytest.raises(ExecutionNotFoundError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).create_run(
            workflow_id=context["workflow_a"],
            version_id=context["version_b"],
            owner_id=context["owner_a"],
            input_json={},
        )
    with repository_database.unit_of_work() as session:
        workflows = WorkflowRepository(session)
        workflow = workflows.lock_owned(
            workflow_id=context["workflow_a"], owner_id=context["owner_a"]
        )
        assert workflow is not None
        workflows.archive(workflow)
    with pytest.raises(ExecutionConflictError), repository_database.unit_of_work() as session:
        ExecutionRepository(session).create_run(
            workflow_id=context["workflow_a"],
            version_id=context["version_a"],
            owner_id=context["owner_a"],
            input_json={},
        )
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 0
        assert session.scalar(select(func.count()).select_from(ExecutionEvent)) == 0
