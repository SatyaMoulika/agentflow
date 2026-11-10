"""Actual pure-node HTTP runs, immutable snapshots, failures and committed history."""

import asyncio
import json
import socket
import threading
from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import pytest
import uvicorn
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import NodeRun, User, WorkflowRun
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.executions import runner, service
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import EventType
from app.modules.workflows.compiler import CompiledNode
from app.modules.workflows.repository import WorkflowRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-linear-execution-key-at-least-32-bytes"
GRAPH: dict[str, Any] = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "step",
            "type": "transform",
            "config": {"operation": "pick_fields", "fields": ["CustomerID", "items"]},
        },
        {"id": "finish", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "step"},
        {"id": "e2", "source": "step", "target": "finish"},
    ],
}
INPUT = {
    "CustomerID": 12,
    "items": [None, False, {"UnitPrice": 3.5}],
    "omit": "private-business-input",
}
OUTPUT = {"CustomerID": 12, "items": [None, False, {"UnitPrice": 3.5}]}


@pytest.fixture
def owners(repository_database: Database) -> dict[str, UUID]:
    with repository_database.unit_of_work() as session:
        return {
            label: UserRepository(session)
            .add(
                email=f"{label}@runner.example.com",
                password_hash="not-a-login-fixture",
                display_name=label,
            )
            .id
            for label in ("a", "b")
        }


def authorization(owner_id: UUID) -> dict[str, str]:
    tokens = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    return {"Authorization": f"Bearer {tokens.issue(owner_id)}"}


@pytest.fixture
async def client(
    repository_database: Database, owners: dict[str, UUID]
) -> AsyncIterator[AsyncClient]:
    application = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return repository_database

    application.dependency_overrides[get_database_resource] = resource
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers=authorization(owners["a"]),
    ) as client:
        yield client


def saved(database: Database, owner_id: UUID, graph: dict | None = None) -> tuple[UUID, UUID]:
    with database.unit_of_work() as session:
        repository = WorkflowRepository(session)
        workflow = repository.add(owner_id=owner_id, name="Real pure workflow")
        version = repository.append_version(
            workflow_id=workflow.id,
            owner_id=owner_id,
            expected_version=0,
            definition=graph or GRAPH,
        )
        return workflow.id, version.id


def count_runs(database: Database) -> int:
    with database.session() as session:
        return session.scalar(select(func.count()).select_from(WorkflowRun)) or 0


async def start(client: AsyncClient, workflow_id: UUID, version_id: UUID, input_data: Any = None):
    return await client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={
            "workflow_version_id": str(version_id),
            "input": INPUT if input_data is None else input_data,
        },
    )


async def test_event_api_pages_owner_history_without_business_input(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    run = (await start(client, workflow_id, version_id)).json()
    path = f"/api/v1/runs/{run['id']}/events"
    first = await client.get(path, params={"limit": 2})
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert [event["sequence"] for event in first.json()["items"]] == [1, 2]
    assert first.json()["next_after_sequence"] == 2
    second = await client.get(path, params={"after_sequence": 2})
    assert [event["sequence"] for event in second.json()["items"]] == list(range(3, 13))
    assert second.json()["next_after_sequence"] == 12
    assert "private-business-input" not in first.text + second.text
    empty = await client.get(path, params={"after_sequence": 12})
    assert empty.json() == {"items": [], "next_after_sequence": 12}
    foreign = await client.get(path, headers=authorization(owners["b"]))
    missing = await client.get(f"/api/v1/runs/{uuid4()}/events")
    assert foreign.status_code == missing.status_code == 404


async def test_event_stream_replays_only_owned_events_after_cursor(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.executions.event_stream import stream_events

    def short_stream(*args, **kwargs):
        return stream_events(*args, **kwargs, duration=0.02, interval=0.005)

    monkeypatch.setattr("app.api.v1.runs.stream_events", short_stream)
    workflow_id, version_id = saved(repository_database, owners["a"])
    run = (await start(client, workflow_id, version_id)).json()
    path = f"/api/v1/runs/{run['id']}/events/stream"
    first = await client.get(path)
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert first.headers["cache-control"] == "no-store"
    assert [line for line in first.text.splitlines() if line.startswith("id: ")] == [
        f"id: {number}" for number in range(1, 13)
    ]
    assert "private-business-input" not in first.text
    resumed = await client.get(path, headers={"Last-Event-ID": "10"})
    assert [line for line in resumed.text.splitlines() if line.startswith("id: ")] == [
        "id: 11",
        "id: 12",
    ]
    foreign = await client.get(path, headers=authorization(owners["b"]))
    assert foreign.status_code == 404
    invalid = await client.get(path, headers={"Last-Event-ID": "private"})
    assert invalid.status_code == 422 and "private" not in invalid.text


async def test_real_http_stream_emits_before_connection_closes(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    run = (await start(client, workflow_id, version_id)).json()
    application = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return repository_database

    application.dependency_overrides[get_database_resource] = resource
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, lifespan="off", log_config=None))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                await asyncio.sleep(0.01)
        async with AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5) as real_client:
            async with real_client.stream(
                "GET",
                f"/api/v1/runs/{run['id']}/events/stream",
                headers=authorization(owners["a"]),
            ) as response:
                assert response.status_code == 200
                assert response.headers["x-accel-buffering"] == "no"
                async with asyncio.timeout(3):
                    line = await anext(response.aiter_lines())
                assert line == "id: 1"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        listener.close()


async def test_json_parser_workflow_executes_and_preserves_keys(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    graph = deepcopy(GRAPH)
    graph["nodes"][1] = {"id": "step", "type": "json_parser", "config": {"input_field": "raw"}}
    workflow_id, version_id = saved(repository_database, owners["a"], graph)
    response = await start(client, workflow_id, version_id, {"raw": '{"CustomerID":42}'})
    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"
    assert response.json()["output"] == {"CustomerID": 42}
    failed = await start(client, workflow_id, version_id, {"raw": '{"secret":1,"secret":2}'})
    assert failed.json()["status"] == "failed"
    assert failed.json()["node_runs"][1]["error_code"] == "EXECUTION_FAILED"


async def test_edit_proposal_is_owned_read_only_and_bound_to_saved_version(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    calls = []

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        calls.append(prompt)
        return {
            "model": "test-model",
            "content": json.dumps(
                {
                    "status": "ready",
                    "message": "Review",
                    "name": "Proposal",
                    "description": "",
                    "definition": GRAPH,
                    "sample_input": {},
                }
            ),
        }

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    path = f"/api/v1/workflows/{workflow_id}/edit-proposal"
    body = {"base_version_id": str(version_id), "prompt": "Change the workflow"}
    foreign = await client.post(path, json=body, headers=authorization(owners["b"]))
    assert foreign.status_code == 404 and not calls
    stale = await client.post(path, json={**body, "base_version_id": str(uuid4())})
    assert stale.status_code == 409 and not calls
    result = await client.post(path, json=body)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["base_version_id"] == str(version_id)
    assert result.json()["base_version_number"] == 1
    assert result.json()["definition"] == GRAPH
    assert len(calls) == 1 and '"CustomerID"' in calls[0]
    current = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert current.json()["current_version_id"] == str(version_id)
    assert current.json()["current_version_number"] == 1


async def test_edit_proposal_cannot_overwrite_a_version_saved_during_generation(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        with repository_database.unit_of_work() as session:
            WorkflowRepository(session).append_version(
                workflow_id=workflow_id, owner_id=owners["a"], expected_version=1, definition=GRAPH
            )
        return {
            "model": "test-model",
            "content": json.dumps(
                {
                    "status": "ready",
                    "message": "Review",
                    "name": "Proposal",
                    "description": "",
                    "definition": GRAPH,
                    "sample_input": {},
                }
            ),
        }

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    result = await client.post(
        f"/api/v1/workflows/{workflow_id}/edit-proposal",
        json={"base_version_id": str(version_id), "prompt": "Change the workflow"},
    )
    assert result.status_code == 200 and result.json()["base_version_number"] == 1
    save = await client.patch(
        f"/api/v1/workflows/{workflow_id}",
        json={"expected_version": 1, "definition": result.json()["definition"]},
    )
    assert save.status_code == 409
    current = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert current.json()["current_version_number"] == 2


async def test_real_run_outputs_attempts_events_and_history_survive_a_fresh_app(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    caplog: pytest.LogCaptureFixture,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    response = await start(client, workflow_id, version_id)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "succeeded" and body["revision"] == 2
    assert body["input"] == INPUT and body["output"] == OUTPUT and body["error_code"] is None
    assert body["workflow_version_id"] == body["version"]["id"] == str(version_id)
    assert body["version"]["definition"] == GRAPH
    assert body["event_sequence"] == 12 and body["parent_run_id"] is None
    assert body["created_at"] <= body["started_at"] <= body["completed_at"]
    assert body["completed_at"].endswith("Z")
    assert [
        (row["node_id"], row["status"], row["attempt_number"]) for row in body["node_runs"]
    ] == [(kind, "succeeded", 1) for kind in ("start", "step", "finish")]
    assert body["node_runs"][0]["output"] == INPUT
    assert body["node_runs"][1]["input"] == INPUT
    assert body["node_runs"][2]["input"] == OUTPUT
    assert all(row["duration_ms"] >= 0 and row["revision"] == 2 for row in body["node_runs"])
    assert response.headers["location"] == f"/api/v1/runs/{body['id']}"
    assert response.headers["cache-control"] == "no-store"
    with repository_database.session() as session:
        events = ExecutionRepository(session).events_owned(
            run_id=UUID(body["id"]), owner_id=owners["a"]
        )
        assert [row.sequence for row in events] == list(range(1, 13))
        assert "private-business-input" not in str([row.event_payload for row in events])
    assert "private-business-input" not in caplog.text and "UnitPrice" not in caplog.text
    assert (await client.get(response.headers["location"])).json() == body
    fresh = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return repository_database

    fresh.dependency_overrides[get_database_resource] = resource
    async with AsyncClient(
        transport=ASGITransport(app=fresh),
        base_url="https://test",
        headers=authorization(owners["a"]),
    ) as restarted:
        assert (await restarted.get(response.headers["location"])).json() == body


async def test_mappings_replace_incoming_and_can_use_an_earlier_dominator(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    graph = deepcopy(GRAPH)
    graph["nodes"][1]["config"] = {"operation": "identity"}
    graph["nodes"][1]["input_mapping"] = {"Invoice.Amount": "$.start.output.invoice.Amount"}
    graph["nodes"][2]["input_mapping"] = {
        "Result": "$.step.output",
        "Original": "$.start.output.invoice.Amount",
    }
    graph["nodes"].reverse()
    workflow_id, version_id = saved(repository_database, owners["a"], graph)
    response = await start(
        client, workflow_id, version_id, {"invoice": {"Amount": 20}, "discard": True}
    )
    assert response.status_code == 201
    assert response.json()["output"] == {"Result": {"Invoice.Amount": 20}, "Original": 20}
    assert [row["node_id"] for row in response.json()["node_runs"]] == ["start", "step", "finish"]


@pytest.mark.parametrize("mapping_failure", [False, True])
async def test_runtime_failure_is_persisted_and_does_not_execute_downstream(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    mapping_failure: bool,
) -> None:
    graph = deepcopy(GRAPH)
    if mapping_failure:
        graph["nodes"][1]["input_mapping"] = {"CustomerID": "$.start.output.private_missing"}
    workflow_id, version_id = saved(repository_database, owners["a"], graph)
    response = await start(client, workflow_id, version_id, {"CustomerID": 12})
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed" and body["output"] is None
    assert body["error_code"] == ("INPUT_MAPPING_FAILED" if mapping_failure else "EXECUTION_FAILED")
    assert [row["node_id"] for row in body["node_runs"]] == ["start", "step"]
    failed = body["node_runs"][-1]
    assert failed["status"] == "failed" and failed["error_code"] == body["error_code"]
    assert failed["output"] is None
    if mapping_failure:
        assert failed["input"] == {} and failed["started_at"] is None and failed["duration_ms"] == 0
    assert (await client.get(response.headers["location"])).json() == body


async def test_unexpected_executor_bug_has_static_failure_without_raw_exception(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    execute = runner.execute_node

    def broken(node: CompiledNode, data: dict, **kwargs) -> dict:
        if node.id == "step":
            raise RuntimeError("private-executor-detail")
        return execute(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", broken)
    response = await start(client, workflow_id, version_id)
    assert response.status_code == 201 and response.json()["status"] == "failed"
    assert response.json()["error_code"] == "INTERNAL_FAILURE"
    assert "private-executor-detail" not in response.text + caplog.text


@pytest.mark.parametrize("kind", ["llm", "invalid"])
async def test_nonexecutable_saved_versions_are_refused_before_creating_a_run(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID], kind: str
) -> None:
    graph = deepcopy(GRAPH)
    if kind == "llm":
        graph["nodes"][1].update(type=kind, config={"private": "private-unsupported-config"})
    else:
        graph["edges"] = []
    workflow_id, version_id = saved(repository_database, owners["a"], graph)
    validation = await client.post(f"/api/v1/workflows/{workflow_id}/validate", json={})
    assert validation.json()["execution_ready"] is False
    assert validation.json()["valid"] is (kind in {"condition", "calculator"})
    response = await start(client, workflow_id, version_id)
    assert (
        response.status_code == 422
        and response.json()["error"]["code"] == "WORKFLOW_NOT_EXECUTABLE"
    )
    assert "private-unsupported-config" not in response.text
    assert count_runs(repository_database) == 0


async def test_run_ownership_version_membership_and_inactive_users_are_enforced(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    workflow_a, version_a = saved(repository_database, owners["a"])
    workflow_b, version_b = saved(repository_database, owners["b"])
    created = await start(client, workflow_a, version_a)
    path = created.headers["location"]
    missing = await client.get(f"/api/v1/runs/{uuid4()}")
    unowned = await client.get(path, headers=authorization(owners["b"]))
    assert missing.status_code == unowned.status_code == 404
    assert missing.json()["error"] == unowned.json()["error"]
    for workflow_id, version_id in (
        (workflow_b, version_b),
        (workflow_a, version_b),
        (workflow_a, uuid4()),
    ):
        denied = await start(client, workflow_id, version_id)
        assert denied.status_code == 404
    assert count_runs(repository_database) == 1
    with repository_database.unit_of_work() as session:
        user = session.get(User, owners["a"])
        assert user is not None
        user.is_active = False
    assert (await client.get(path)).status_code == 401
    assert (await start(client, workflow_a, version_a)).status_code == 401
    assert count_runs(repository_database) == 1


async def test_exact_version_runs_after_pointer_change_and_archive_preserves_reads(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    newer = deepcopy(GRAPH)
    newer["nodes"][1]["config"] = {"operation": "identity"}
    with repository_database.unit_of_work() as session:
        new_version = WorkflowRepository(session).append_version(
            workflow_id=workflow_id, owner_id=owners["a"], expected_version=1, definition=newer
        )
        new_id = new_version.id
    response = await start(client, workflow_id, version_id)
    assert response.status_code == 201 and response.json()["output"] == OUTPUT
    assert response.json()["version"]["id"] == str(version_id)
    current = await start(client, workflow_id, new_id)
    assert current.status_code == 201 and current.json()["output"] == INPUT
    assert (await client.delete(f"/api/v1/workflows/{workflow_id}")).status_code == 204
    assert (await start(client, workflow_id, version_id)).status_code == 409
    assert (await client.get(response.headers["location"])).json() == response.json()
    assert count_runs(repository_database) == 2


@pytest.mark.parametrize("archive_during_compile", [False, True])
async def test_compile_uses_copied_snapshot_and_creation_rechecks_archive_in_transaction(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    archive_during_compile: bool,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    compile_original = service.compile_workflow

    def compile_and_change(definition: dict):
        # This independent transaction would block if compilation held the workflow lock.
        with repository_database.unit_of_work() as session:
            repository = WorkflowRepository(session)
            if archive_during_compile:
                workflow = repository.lock_owned(workflow_id=workflow_id, owner_id=owners["a"])
                assert workflow is not None
                repository.archive(workflow)
            else:
                newer = deepcopy(GRAPH)
                newer["nodes"][1]["config"] = {"operation": "identity"}
                repository.append_version(
                    workflow_id=workflow_id,
                    owner_id=owners["a"],
                    expected_version=1,
                    definition=newer,
                )
        return compile_original(definition)

    monkeypatch.setattr(service, "compile_workflow", compile_and_change)
    response = await start(client, workflow_id, version_id)
    if archive_during_compile:
        assert response.status_code == 409 and count_runs(repository_database) == 0
    else:
        assert response.status_code == 201 and response.json()["output"] == OUTPUT
        assert response.json()["workflow_version_id"] == str(version_id)


async def test_executors_run_in_worker_thread_without_checked_out_operation_sessions(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    main_thread = threading.get_ident()
    baseline = repository_database.engine.pool.checkedout()  # type: ignore[attr-defined]
    execute = runner.execute_node
    visited = []

    def checked(node: CompiledNode, data: dict, **kwargs) -> dict:
        assert threading.get_ident() != main_thread
        assert repository_database.engine.pool.checkedout() == baseline  # type: ignore[attr-defined]
        visited.append(node.id)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", checked)
    response = await start(client, workflow_id, version_id)
    assert response.status_code == 201 and response.json()["status"] == "succeeded"
    assert visited == ["start", "step", "finish"]


@pytest.mark.parametrize("failure_stage", ["create", "result"])
async def test_storage_failure_rolls_back_event_and_state_and_exposes_known_run_location(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_stage: str,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    event_original = ExecutionRepository._event
    injected = False

    def failing_event(self, run, event_type, payload, node_run_id=None):
        nonlocal injected
        event = event_original(self, run, event_type, payload, node_run_id)
        result_event = False
        if event_type == EventType.NODE_STATUS_CHANGED and payload.get("to_status") == "succeeded":
            row = self.session.get(NodeRun, node_run_id)
            result_event = row is not None and row.node_id == "step"
        if not injected and (
            (failure_stage == "create" and event_type == EventType.RUN_CREATED)
            or (failure_stage == "result" and result_event)
        ):
            injected = True
            raise OperationalError("private-query", {}, Exception("private-driver"))
        return event

    monkeypatch.setattr(ExecutionRepository, "_event", failing_event)
    response = await start(client, workflow_id, version_id)
    assert injected and response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-query" not in response.text + caplog.text
    assert "private-driver" not in response.text + caplog.text
    if failure_stage == "create":
        assert count_runs(repository_database) == 0 and "location" not in response.headers
    else:
        assert count_runs(repository_database) == 1
        retained = await client.get(response.headers["location"])
        body = retained.json()
        assert retained.status_code == 200 and body["status"] == "running"
        assert body["output"] is None and body["error_code"] is None
        assert body["event_sequence"] == 7
        assert body["node_runs"][-1]["status"] == "running"
        assert body["node_runs"][-1]["output"] is None
        with repository_database.session() as session:
            events = ExecutionRepository(session).events_owned(
                run_id=UUID(body["id"]), owner_id=owners["a"]
            )
            assert [row.sequence for row in events] == list(range(1, 8))
    recovered = await start(client, workflow_id, version_id)
    assert recovered.status_code == 201 and recovered.json()["status"] == "succeeded"


async def test_read_failure_has_safe_503_and_recovers_without_mutating_history(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    created = await start(client, workflow_id, version_id)
    original = ExecutionRepository.lock_owned

    def unavailable(*args, **kwargs):
        raise OperationalError("private-query", {}, Exception("private-driver"))

    monkeypatch.setattr(ExecutionRepository, "lock_owned", unavailable)
    response = await client.get(created.headers["location"])
    assert response.status_code == 503
    assert response.headers["location"] == created.headers["location"]
    assert "private-" not in response.text
    monkeypatch.setattr(ExecutionRepository, "lock_owned", original)
    assert (await client.get(created.headers["location"])).json() == created.json()


async def test_distinct_concurrent_posts_create_independent_runs_without_idempotency_claims(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id, version_id = saved(repository_database, owners["a"])
    execute = runner.execute_node
    barrier = threading.Barrier(2, timeout=10)

    def concurrent(node: CompiledNode, data: dict, **kwargs) -> dict:
        if node.type == "manual":
            barrier.wait()
        return execute(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", concurrent)
    responses = await asyncio.gather(
        start(client, workflow_id, version_id),
        start(client, workflow_id, version_id, INPUT | {"CustomerID": 99}),
    )
    assert all(
        response.status_code == 201 and response.json()["status"] == "succeeded"
        for response in responses
    )
    assert len({response.json()["id"] for response in responses}) == 2
    assert {response.json()["output"]["CustomerID"] for response in responses} == {12, 99}
    assert all(response.json()["event_sequence"] == 12 for response in responses)
    assert count_runs(repository_database) == 2
