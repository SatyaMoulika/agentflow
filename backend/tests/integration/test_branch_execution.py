"""Actual selected-route execution and atomic persisted skips against PostgreSQL."""

import asyncio
import threading
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import WorkflowRun
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.executions import runner
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import EventType
from app.modules.workflows.compiler import CompiledNode

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-branch-execution-key-at-least-32-bytes"


def literal(value: int | float) -> dict:
    return {"kind": "literal", "value": value}


def output(path: str) -> dict:
    return {"kind": "output", "path": path}


def calc(identifier: str, operation: str, *operands: dict) -> dict:
    return {
        "id": identifier,
        "type": "calculator",
        "config": {"operation": operation, "operands": list(operands)},
    }


def edge(source: str, target: str, handle: str = "default") -> dict:
    return {
        "id": f"{source}_{handle}_{target}",
        "source": source,
        "target": target,
        "source_handle": handle,
    }


def diamond() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "choose",
                "type": "condition",
                "config": {"field": "$.start.output.x", "operator": "greater_than", "value": 10},
            },
            calc("left", "multiply", output("$.start.output.x"), literal(2)),
            calc("right", "add", output("$.start.output.x"), literal(1)),
            {"id": "join", "type": "merge", "config": {}},
            {"id": "finish", "type": "end", "config": {}},
        ],
        "edges": [
            edge("start", "choose"),
            edge("choose", "left", "true"),
            edge("choose", "right", "false"),
            edge("left", "join"),
            edge("right", "join"),
            edge("join", "finish"),
        ],
    }


@pytest.fixture
def owner_id(repository_database: Database) -> UUID:
    with repository_database.unit_of_work() as session:
        return (
            UserRepository(session)
            .add(
                email="branch@example.com",
                display_name="Branch",
                password_hash="not-a-login-fixture",
            )
            .id
        )


def application(database: Database):
    app = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return database

    app.dependency_overrides[get_database_resource] = resource
    return app


@pytest.fixture
async def client(repository_database: Database, owner_id: UUID) -> AsyncIterator[AsyncClient]:
    token = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    ).issue(owner_id)
    async with AsyncClient(
        transport=ASGITransport(app=application(repository_database)),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield client


async def save(client: AsyncClient, graph: dict) -> dict:
    created = await client.post(
        "/api/v1/workflows", json={"name": "Actual branching", "definition": graph}
    )
    assert created.status_code == 201, created.text
    return created.json()


async def start(client: AsyncClient, workflow: dict, data: dict):
    return await client.post(
        f"/api/v1/workflows/{workflow['id']}/runs",
        json={"workflow_version_id": workflow["current_version_id"], "input": data},
    )


@pytest.mark.parametrize(
    ("value", "chosen", "unchosen", "expected"),
    [(11, "left", "right", 22), (4, "right", "left", 5)],
)
async def test_only_selected_branch_is_resolved_and_executed_with_real_results_and_skips(
    client: AsyncClient,
    repository_database: Database,
    owner_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
    value: int,
    chosen: str,
    unchosen: str,
    expected: int,
) -> None:
    graph = diamond()
    for item in graph["nodes"]:
        if item["id"] == unchosen:
            item["config"] = {
                "operation": "divide",
                "operands": [output("$.start.output.private_missing"), literal(0)],
            }
    workflow = await save(client, graph)
    validation = await client.post(f"/api/v1/workflows/{workflow['id']}/validate", json={})
    assert validation.json()["valid"] and validation.json()["execution_ready"]
    execute = runner.execute_node
    visited = []
    baseline = repository_database.engine.pool.checkedout()  # type: ignore[attr-defined]

    def checked(node: CompiledNode, data: dict, **kwargs) -> dict:
        assert node.id != unchosen
        assert repository_database.engine.pool.checkedout() == baseline  # type: ignore[attr-defined]
        visited.append(node.id)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", checked)
    response = await start(client, workflow, {"x": value})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded" and body["output"] == {"result": expected}
    assert visited == ["start", "choose", chosen, "join", "finish"]
    rows = {row["node_id"]: row for row in body["node_runs"]}
    assert rows["choose"]["output"] == {"result": value > 10}
    assert rows["join"]["input"] == rows["join"]["output"] == {"result": expected}
    skipped = rows[unchosen]
    assert (
        skipped["status"] == "skipped"
        and skipped["attempt_number"] == 1
        and skipped["revision"] == 1
    )
    assert skipped["input"] == {} and skipped["output"] is None and skipped["error_code"] is None
    assert (
        skipped["started_at"] is None
        and skipped["completed_at"] is not None
        and skipped["duration_ms"] == 0
    )
    assert all(
        row["status"] == "succeeded" for identifier, row in rows.items() if identifier != unchosen
    )
    assert body["event_sequence"] == 20
    with repository_database.session() as session:
        events = ExecutionRepository(session).events_owned(
            run_id=UUID(body["id"]), owner_id=owner_id
        )
        assert [event.sequence for event in events] == list(range(1, 21))
        assert "private_missing" not in str([event.event_payload for event in events])
    assert (await client.get(response.headers["location"])).json() == body


def nested_graph() -> dict:
    graph = diamond()
    graph["nodes"][1]["config"] = {"field": "$.start.output.A", "operator": "equals", "value": True}
    graph["nodes"].extend(
        [
            {
                "id": "inner",
                "type": "condition",
                "config": {"field": "$.start.output.B", "operator": "equals", "value": True},
            },
            {
                "id": "early",
                "type": "end",
                "config": {},
                "input_mapping": {"original": "$.start.output.x"},
            },
        ]
    )
    graph["edges"] = [
        edge("start", "choose"),
        edge("choose", "left", "true"),
        edge("choose", "inner", "false"),
        edge("inner", "right", "true"),
        edge("inner", "early", "false"),
        edge("left", "join"),
        edge("right", "join"),
        edge("join", "finish"),
    ]
    graph[
        "nodes"
    ].reverse()  # Execution order is the selected route, independent of definition order.
    return graph


@pytest.mark.parametrize(
    ("a", "b", "active", "expected"),
    [
        (True, False, {"start", "choose", "left", "join", "finish"}, {"result": 8}),
        (False, True, {"start", "choose", "inner", "right", "join", "finish"}, {"result": 5}),
        (False, False, {"start", "choose", "inner", "early"}, {"original": 4}),
    ],
)
async def test_nested_branches_early_end_and_shared_merge_are_not_over_skipped(
    client: AsyncClient, a: bool, b: bool, active: set[str], expected: dict
) -> None:
    workflow = await save(client, nested_graph())
    response = await start(client, workflow, {"x": 4, "A": a, "B": b})
    assert response.status_code == 201 and response.json()["status"] == "succeeded"
    body = response.json()
    assert body["output"] == expected
    rows = {row["node_id"]: row for row in body["node_runs"]}
    assert {
        identifier for identifier, row in rows.items() if row["status"] == "succeeded"
    } == active
    assert {identifier for identifier, row in rows.items() if row["status"] == "skipped"} == set(
        rows
    ) - active
    assert len(rows) == 8
    assert body["event_sequence"] == 3 + len(active) * 3 + (8 - len(active)) * 2


async def test_two_condition_handles_can_reach_the_same_merge_once(client: AsyncClient) -> None:
    graph = diamond()
    graph["nodes"] = [item for item in graph["nodes"] if item["id"] not in {"left", "right"}]
    graph["edges"] = [
        edge("start", "choose"),
        edge("choose", "join", "true"),
        edge("choose", "join", "false"),
        edge("join", "finish"),
    ]
    workflow = await save(client, graph)
    response = await start(client, workflow, {"x": 3})
    assert response.status_code == 201 and response.json()["output"] == {"result": False}
    assert len(response.json()["node_runs"]) == 4
    assert all(row["status"] == "succeeded" for row in response.json()["node_runs"])
    assert response.json()["event_sequence"] == 15


@pytest.mark.parametrize(("x", "result", "selected"), [(9, 10, "low"), (10, 11, "high")])
async def test_calculated_result_drives_later_condition_and_end_mapping(
    client: AsyncClient, x: int, result: int, selected: str
) -> None:
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            calc("sum", "add", output("$.start.output.x"), literal(1)),
            {
                "id": "test",
                "type": "condition",
                "config": {"field": "$.sum.output.result", "operator": "greater_than", "value": 10},
            },
            *[
                {
                    "id": identifier,
                    "type": "end",
                    "config": {},
                    "input_mapping": {"total": "$.sum.output.result"},
                }
                for identifier in ("low", "high")
            ],
        ],
        "edges": [
            edge("start", "sum"),
            edge("sum", "test"),
            edge("test", "high", "true"),
            edge("test", "low", "false"),
        ],
    }
    workflow = await save(client, graph)
    response = await start(client, workflow, {"x": x})
    assert response.status_code == 201 and response.json()["output"] == {"total": result}
    assert {
        row["node_id"] for row in response.json()["node_runs"] if row["status"] == "succeeded"
    } == {"start", "sum", "test", selected}


@pytest.mark.parametrize(
    ("value", "operation", "expected_code"),
    [
        (0, "divide", "EXECUTION_FAILED"),
        ("2", "add", "EXECUTION_FAILED"),
        (True, "add", "EXECUTION_FAILED"),
        (None, "add", "EXECUTION_FAILED"),
        (1_000_000_000_001, "add", "EXECUTION_FAILED"),
        (1_000_000_000_000, "add", "EXECUTION_FAILED"),
        ("missing", "add", "INPUT_MAPPING_FAILED"),
    ],
)
async def test_numeric_failures_are_persisted_without_downstream_or_fake_skips(
    client: AsyncClient, value: Any, operation: str, expected_code: str
) -> None:
    operands = (
        [literal(1), output("$.start.output.x")]
        if operation == "divide"
        else [output("$.start.output.x"), literal(1)]
    )
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            calc("math", operation, *operands),
            {"id": "finish", "type": "end", "config": {}},
        ],
        "edges": [edge("start", "math"), edge("math", "finish")],
    }
    workflow = await save(client, graph)
    response = await start(client, workflow, {} if value == "missing" else {"x": value})
    body = response.json()
    assert response.status_code == 201 and body["status"] == "failed"
    assert body["output"] is None and body["error_code"] == expected_code
    assert [row["node_id"] for row in body["node_runs"]] == ["start", "math"]
    assert body["node_runs"][-1]["error_code"] == expected_code
    assert body["node_runs"][-1]["output"] is None
    if expected_code == "INPUT_MAPPING_FAILED":
        assert body["node_runs"][-1]["input"] == {} and body["node_runs"][-1]["started_at"] is None


@pytest.mark.parametrize("value", ["2", True, {}, []])
async def test_invalid_ordered_condition_value_stops_before_either_arm(
    client: AsyncClient, value: Any
) -> None:
    workflow = await save(client, diamond())
    response = await start(client, workflow, {"x": value})
    assert response.status_code == 201 and response.json()["status"] == "failed"
    assert response.json()["error_code"] == "EXECUTION_FAILED"
    assert [row["node_id"] for row in response.json()["node_runs"]] == ["start", "choose"]


async def test_final_skip_failure_rolls_back_end_result_skips_and_completion_together(
    client: AsyncClient,
    repository_database: Database,
    owner_id: UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = await save(client, diamond())
    original = ExecutionRepository._event
    injected = False

    def fail_skip(self, run, event_type, payload, node_run_id=None):
        nonlocal injected
        event = original(self, run, event_type, payload, node_run_id)
        if (
            not injected
            and event_type == EventType.NODE_STATUS_CHANGED
            and payload.get("to_status") == "skipped"
        ):
            injected = True
            raise OperationalError("private-skip-query", {}, Exception("private-skip-driver"))
        return event

    monkeypatch.setattr(ExecutionRepository, "_event", fail_skip)
    response = await start(client, workflow, {"x": 11})
    assert injected and response.status_code == 503
    assert "private-skip" not in response.text
    retained = await client.get(response.headers["location"])
    body = retained.json()
    assert retained.status_code == 200 and body["status"] == "running" and body["output"] is None
    assert body["event_sequence"] == 16
    rows = {row["node_id"]: row for row in body["node_runs"]}
    assert rows["finish"]["status"] == "running" and rows["finish"]["output"] is None
    assert "right" not in rows and all(row["status"] != "skipped" for row in rows.values())
    with repository_database.session() as session:
        events = ExecutionRepository(session).events_owned(
            run_id=UUID(body["id"]), owner_id=owner_id
        )
        assert [event.sequence for event in events] == list(range(1, 17))
    recovered = await start(client, workflow, {"x": 11})
    assert recovered.status_code == 201 and recovered.json()["status"] == "succeeded"
    assert (
        next(row for row in recovered.json()["node_runs"] if row["node_id"] == "right")["status"]
        == "skipped"
    )


async def test_branch_local_output_reference_after_merge_remains_invalid_before_execution(
    client: AsyncClient, repository_database: Database
) -> None:
    graph = diamond()
    next(item for item in graph["nodes"] if item["id"] == "join")["input_mapping"] = {
        "unsafe": "$.left.output.result"
    }
    workflow = await save(client, graph)
    report = await client.post(f"/api/v1/workflows/{workflow['id']}/validate", json={})
    assert report.json()["valid"] is False and report.json()["execution_ready"] is False
    response = await start(client, workflow, {"x": 11})
    assert (
        response.status_code == 422
        and response.json()["error"]["code"] == "WORKFLOW_NOT_EXECUTABLE"
    )
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 0


async def test_branch_history_remains_bound_to_old_version_after_new_save_and_archive(
    client: AsyncClient,
) -> None:
    graph = diamond()
    workflow = await save(client, graph)
    old = await start(client, workflow, {"x": 11})
    assert old.status_code == 201 and old.json()["output"] == {"result": 22}
    newer = deepcopy(graph)
    next(item for item in newer["nodes"] if item["id"] == "left")["config"]["operands"][1][
        "value"
    ] = 4
    saved = await client.patch(
        f"/api/v1/workflows/{workflow['id']}", json={"definition": newer, "expected_version": 1}
    )
    assert saved.status_code == 200
    current = await start(client, saved.json(), {"x": 11})
    assert current.status_code == 201 and current.json()["output"] == {"result": 44}
    assert (await client.delete(f"/api/v1/workflows/{workflow['id']}")).status_code == 204
    assert (await client.get(old.headers["location"])).json() == old.json()
    assert old.json()["version"]["definition"] == graph
    assert (await start(client, workflow, {"x": 11})).status_code == 409


async def test_concurrent_runs_take_different_routes_without_sharing_outputs_or_skips(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = await save(client, diamond())
    execute = runner.execute_node
    barrier = threading.Barrier(2, timeout=10)

    def concurrent(node: CompiledNode, data: dict, **kwargs) -> dict:
        if node.type == "manual":
            barrier.wait()
        return execute(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", concurrent)
    first, second = await asyncio.gather(
        start(client, workflow, {"x": 11}), start(client, workflow, {"x": 4})
    )
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["output"] == {"result": 22} and second.json()["output"] == {"result": 5}
    for response, skipped in ((first, "right"), (second, "left")):
        assert response.json()["status"] == "succeeded" and response.json()["event_sequence"] == 20
        assert {
            row["node_id"] for row in response.json()["node_runs"] if row["status"] == "skipped"
        } == {skipped}
