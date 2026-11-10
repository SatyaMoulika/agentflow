"""Real concurrent command replay, bounded attempts and cancellation fences."""

import asyncio
import json
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
from app.infrastructure.database.models import (
    ExecutionEvent,
    NodeRun,
    RunCommand,
    Workflow,
    WorkflowRun,
)
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.executions import runner
from app.modules.executions.exceptions import ExecutionStorageUnavailableError
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import FailureCode, NodeStatus, RunStatus
from app.modules.workflows.compiler import CompiledNode

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "commands-test-signing-key-at-least-32-characters"
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "step", "type": "transform", "config": {"operation": "identity"}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "step"},
        {"id": "e2", "source": "step", "target": "end"},
    ],
}

GROQ_GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "ai", "type": "groq", "config": {"instruction": "Reply", "input_field": "message"}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "ai"},
        {"id": "e2", "source": "ai", "target": "end"},
    ],
}


@pytest.fixture
def owners(repository_database: Database) -> dict[str, UUID]:
    with repository_database.unit_of_work() as session:
        return {
            name: UserRepository(session)
            .add(email=f"{name}@commands.example.com", password_hash="fixture", display_name=name)
            .id
            for name in ("a", "b")
        }


def auth(owner: UUID) -> dict[str, str]:
    token = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    ).issue(owner)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client(
    repository_database: Database, owners: dict[str, UUID]
) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return repository_database

    app.dependency_overrides[get_database_resource] = resource
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test", headers=auth(owners["a"])
    ) as client:
        yield client


async def saved(
    client: AsyncClient, graph: dict | None = None, headers: dict | None = None
) -> dict:
    result = await client.post(
        "/api/v1/workflows",
        json={"name": "Command graph", "definition": graph or GRAPH},
        headers=headers,
    )
    assert result.status_code == 201, result.text
    return result.json()


async def execute(client: AsyncClient, workflow: dict, key: str | None = None, **data: Any):
    return await client.post(
        f"/api/v1/workflows/{workflow['id']}/runs",
        json={
            "workflow_version_id": workflow["current_version_id"],
            "input": {"private": "payload"},
            **data,
        },
        headers={"Idempotency-Key": key} if key is not None else {},
    )


async def test_generated_proposal_is_read_only_until_explicit_create_and_run(
    client: AsyncClient, repository_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    proposal = {
        "status": "ready",
        "message": "Review",
        "name": "Support reply",
        "description": "Support",
        "definition": GROQ_GRAPH,
        "sample_input": {"message": "Hi"},
    }
    monkeypatch.setattr(
        "app.modules.workflows.generation.complete",
        lambda *args, **kwargs: {"content": json.dumps(proposal), "model": "test-model"},
    )
    monkeypatch.setattr(
        runner, "complete", lambda settings, prompt: {"model": "test-model", "content": "Hello"}
    )
    generated = await client.post("/api/v1/workflows/generate", json={"prompt": "Draft a reply"})
    assert generated.status_code == 200
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(Workflow)) == 0
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 0
    candidate = generated.json()
    created = await client.post(
        "/api/v1/workflows",
        json={
            "name": candidate["name"],
            "description": candidate["description"],
            "definition": candidate["definition"],
        },
    )
    assert created.status_code == 201
    result = await execute(client, created.json(), input=candidate["sample_input"])
    assert result.status_code == 201 and result.json()["status"] == "succeeded"
    assert result.json()["output"] == {"model": "test-model", "content": "Hello"}


async def test_groq_workflow_records_actual_output_and_replay_is_not_repeated(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def complete(settings: Settings, prompt: str) -> dict[str, str]:
        calls.append(prompt)
        return {"model": "test-model", "content": "Provider answer"}

    monkeypatch.setattr(runner, "complete", complete)
    workflow = await saved(client, GROQ_GRAPH)
    first = await execute(
        client, workflow, "groq-once", input={"message": "Hello", "private": "ignored"}
    )
    replay = await execute(
        client, workflow, "groq-once", input={"message": "Hello", "private": "ignored"}
    )
    assert first.status_code == 201 and first.json() == replay.json()
    assert first.json()["status"] == "succeeded"
    assert first.json()["output"] == {"model": "test-model", "content": "Provider answer"}
    assert calls == ["Reply\n\nHello"]
    assert any(
        node["node_id"] == "ai" and node["status"] == "succeeded"
        for node in first.json()["node_runs"]
    )


async def test_groq_failure_has_no_automatic_or_full_workflow_retry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def failed(settings: Settings, prompt: str) -> dict[str, str]:
        calls.append(prompt)
        raise runner.GroqError(429)

    monkeypatch.setattr(runner, "complete", failed)
    workflow = await saved(client, GROQ_GRAPH)
    response = await execute(
        client, workflow, "groq-fail", input={"message": "Hello"}, max_attempts=3
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "PROVIDER_RATE_LIMITED"
    assert calls == ["Reply\n\nHello"]
    retry = await client.post(f"/api/v1/runs/{response.json()['id']}/retry", json={})
    assert retry.status_code == 422
    assert len(calls) == 1


async def test_groq_rejects_missing_input_without_calling_provider(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def complete(settings: Settings, prompt: str) -> dict[str, str]:
        calls.append(prompt)
        return {"model": "test-model", "content": "Unexpected"}

    monkeypatch.setattr(runner, "complete", complete)
    workflow = await saved(client, GROQ_GRAPH)
    response = await execute(client, workflow, input={"wrong_field": "Hello"})
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "EXECUTION_FAILED"
    assert calls == []


async def test_replay_canonical_body_conflicts_and_archived_history(
    client: AsyncClient, repository_database: Database
) -> None:
    workflow = await saved(client)
    first = await execute(client, workflow, "key-one", input={"a": 1, "b": False})
    again = await execute(client, workflow, "key-one", input={"b": False, "a": 1})
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    for data in [{"input": {"a": True, "b": False}}, {"max_attempts": 2}]:
        assert (await execute(client, workflow, "key-one", **data)).status_code == 409
    await client.delete(f"/api/v1/workflows/{workflow['id']}")
    assert (
        await execute(client, workflow, "key-one", input={"a": 1, "b": False})
    ).json() == first.json()
    assert (await execute(client, workflow, "new-key")).status_code == 409
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 1
        receipt = session.scalar(select(RunCommand))
        assert receipt is not None and receipt.key_digest != "key-one"
        assert receipt.run_id == UUID(first.json()["id"])


async def test_keys_are_owner_scoped_but_not_workflow_scoped(
    client: AsyncClient, owners: dict[str, UUID]
) -> None:
    workflow = await saved(client)
    other_workflow = await saved(client)
    first = await execute(client, workflow, "same-key")
    assert (await execute(client, other_workflow, "same-key")).status_code == 409
    other = await saved(client, headers=auth(owners["b"]))
    response = await client.post(
        f"/api/v1/workflows/{other['id']}/runs",
        json={"workflow_version_id": other["current_version_id"], "input": {"private": "payload"}},
        headers={**auth(owners["b"]), "Idempotency-Key": "same-key"},
    )
    assert response.status_code == 201 and response.json()["id"] != first.json()["id"]


async def test_concurrent_duplicate_returns_committed_run_without_second_execution(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = await saved(client)
    entered, release = threading.Event(), threading.Event()
    original = runner.execute_node
    calls = []

    def paused(node: CompiledNode, data: dict, **kwargs):
        calls.append(node.id)
        if node.id == "start":
            entered.set()
            assert release.wait(10)
        return original(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", paused)
    pending = asyncio.create_task(execute(client, workflow, "concurrent"))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        duplicate = await execute(client, workflow, "concurrent")
        assert duplicate.status_code == 201 and duplicate.json()["status"] == "running"
    finally:
        release.set()
    first = await pending
    assert first.json()["id"] == duplicate.json()["id"]
    assert calls == ["start", "step", "end"]


@pytest.mark.parametrize("crash", [False, True])
async def test_cancellation_wins_against_inflight_result_or_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, crash: bool
) -> None:
    workflow = await saved(client)
    entered, release = threading.Event(), threading.Event()
    original = runner.execute_node

    def paused(node: CompiledNode, data: dict, **kwargs):
        entered.set()
        assert release.wait(10)
        if crash:
            raise RuntimeError("private error")
        return original(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", paused)
    pending = asyncio.create_task(execute(client, workflow, "cancel-race", max_attempts=3))
    try:
        assert await asyncio.to_thread(entered.wait, 10)
        current = (await client.get("/api/v1/runs")).json()["items"][0]
        path = f"/api/v1/runs/{current['id']}/cancel"
        cancel = await client.post(path)
        assert cancel.status_code == 200 and cancel.json()["status"] == "cancelled"
        assert (await client.post(path)).json() == cancel.json()
    finally:
        release.set()
    completed = await pending
    assert completed.status_code == 201 and completed.json() == cancel.json()
    assert len(completed.json()["node_runs"]) == 1
    assert completed.json()["node_runs"][0]["status"] == "cancelled"
    assert completed.json()["output"] is None


@pytest.mark.parametrize("exhaust", [False, True])
async def test_bounded_transient_attempts_preserve_history(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    exhaust: bool,
    repository_database: Database,
) -> None:
    workflow = await saved(client)
    original = runner.execute_node
    count = 0

    def flaky(node: CompiledNode, data: dict, **kwargs):
        nonlocal count
        if node.id == "step":
            count += 1
            if exhaust or count == 1:
                raise NodeExecutionError(FailureCode.DEADLINE_EXCEEDED)
        return original(node, data, **kwargs)

    monkeypatch.setattr(runner, "execute_node", flaky)
    result = await execute(client, workflow, max_attempts=3)
    assert result.status_code == 201
    run = result.json()
    assert run["max_attempts"] == 3
    assert run["status"] == ("failed" if exhaust else "succeeded")
    attempts = [row for row in run["node_runs"] if row["node_id"] == "step"]
    assert [row["attempt_number"] for row in attempts] == ([1, 2, 3] if exhaust else [1, 2])
    assert attempts[0]["status"] == "failed" and attempts[0]["error_code"] == "DEADLINE_EXCEEDED"
    assert attempts[-1]["status"] == ("failed" if exhaust else "succeeded")
    with repository_database.session() as session:
        events = session.scalars(
            select(ExecutionEvent)
            .where(ExecutionEvent.workflow_run_id == UUID(run["id"]))
            .order_by(ExecutionEvent.sequence)
        ).all()
        assert [event.sequence for event in events] == list(range(1, run["event_sequence"] + 1))


@pytest.mark.parametrize("mapping", [False, True])
async def test_deterministic_failures_do_not_retry(client: AsyncClient, mapping: bool) -> None:
    graph = deepcopy(GRAPH)
    if mapping:
        graph["nodes"][1]["input_mapping"] = {"x": "$.start.output.missing"}
    else:
        graph["nodes"][1]["config"] = {"operation": "pick_fields", "fields": ["missing"]}
    workflow = await saved(client, graph)
    run = (await execute(client, workflow, max_attempts=3)).json()
    assert run["status"] == "failed"
    assert run["error_code"] == ("INPUT_MAPPING_FAILED" if mapping else "EXECUTION_FAILED")
    assert len([n for n in run["node_runs"] if n["node_id"] == "step"]) == 1


async def test_retry_uses_original_snapshot_input_and_lineage(client: AsyncClient) -> None:
    graph = deepcopy(GRAPH)
    graph["nodes"][1]["config"] = {"operation": "pick_fields", "fields": ["missing"]}
    workflow = await saved(client, graph)
    first = (await execute(client, workflow)).json()
    assert first["status"] == "failed"
    await client.patch(
        f"/api/v1/workflows/{workflow['id']}", json={"definition": GRAPH, "expected_version": 1}
    )
    path = f"/api/v1/runs/{first['id']}/retry"
    again = await client.post(
        path, json={"max_attempts": 2}, headers={"Idempotency-Key": "retry-key"}
    )
    assert again.status_code == 201
    child = again.json()
    assert child["id"] != first["id"] and child["parent_run_id"] == first["id"]
    assert child["version"] == first["version"] and child["input"] == first["input"]
    assert child["status"] == "failed" and child["max_attempts"] == 2
    assert (await client.get(f"/api/v1/runs/{first['id']}")).json() == first
    await client.delete(f"/api/v1/workflows/{workflow['id']}")
    assert (
        await client.post(path, json={"max_attempts": 2}, headers={"Idempotency-Key": "retry-key"})
    ).json() == child
    assert (await client.post(path, json={})).status_code == 409


async def test_commands_reject_success_and_other_owner(
    client: AsyncClient, owners: dict[str, UUID]
) -> None:
    workflow = await saved(client)
    run = (await execute(client, workflow)).json()
    for suffix in ("retry", "cancel"):
        path = f"/api/v1/runs/{run['id']}/{suffix}"
        assert (await client.post(path, json={})).status_code == 409
        assert (await client.post(path, json={}, headers=auth(owners["b"]))).status_code == 404


async def test_storage_failure_keeps_receipt_without_reexecuting(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, repository_database: Database
) -> None:
    workflow = await saved(client)

    def broken(*args, **kwargs):
        raise OperationalError("private SQL", {}, Exception("private driver"))

    monkeypatch.setattr(runner.WorkflowRunner, "run", broken)
    failed = await execute(client, workflow, "retained")
    assert failed.status_code == 503 and "private" not in failed.text
    replay = await execute(client, workflow, "retained")
    assert replay.status_code == 201 and replay.json()["status"] == "queued"
    assert failed.headers["location"] == replay.headers["location"]
    assert (await client.post(f"{replay.headers['location']}/cancel")).json()[
        "status"
    ] == "cancelled"
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 1


def test_cancel_rollback_keeps_attempt_and_run_active(
    repository_database: Database, owners: dict[str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.workflows.repository import WorkflowRepository

    with repository_database.unit_of_work() as session:
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owners["a"], name="Cancellation rollback")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owners["a"], expected_version=0, definition=GRAPH
        )
        repo = ExecutionRepository(session)
        run = repo.create_run(
            workflow_id=workflow.id, version_id=version.id, owner_id=owners["a"], input_json={}
        )
        repo.transition_run(
            run_id=run.id, owner_id=owners["a"], expected_revision=0, target=RunStatus.RUNNING
        )
        attempt = repo.add_attempt(
            run_id=run.id,
            owner_id=owners["a"],
            expected_run_revision=1,
            node_id="start",
            input_json={},
        )
        repo.transition_attempt(
            run_id=run.id,
            owner_id=owners["a"],
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        run_id, attempt_id, sequence = run.id, attempt.id, run.event_sequence
    original = ExecutionRepository._event

    def fail_after_flush(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise OperationalError("private", {}, Exception())

    monkeypatch.setattr(ExecutionRepository, "_event", fail_after_flush)
    with pytest.raises(ExecutionStorageUnavailableError):
        ExecutionService(repository_database).cancel(run_id=run_id, owner_id=owners["a"])
    with repository_database.session() as session:
        retained = session.get(WorkflowRun, run_id)
        node = session.get(NodeRun, attempt_id)
        assert (
            retained is not None
            and retained.status == RunStatus.RUNNING
            and retained.event_sequence == sequence
        )
        assert node is not None and node.status == NodeStatus.RUNNING


def test_simultaneous_first_commands_commit_one_receipt_and_execute_once(
    repository_database: Database, owners: dict[str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from app.modules.executions import service
    from app.modules.executions.schemas import RunCreateRequest
    from app.modules.workflows.repository import WorkflowRepository

    with repository_database.unit_of_work() as session:
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owners["a"], name="Concurrent creation")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owners["a"], expected_version=0, definition=GRAPH
        )
        workflow_id, version_id = workflow.id, version.id
    gate = threading.Barrier(2)
    compile_original, run_original = service.compile_workflow, runner.WorkflowRunner.run
    calls = []

    def compile_together(*args, **kwargs):
        result = compile_original(*args, **kwargs)
        gate.wait(timeout=10)
        return result

    def count_run(self, **kwargs):
        calls.append(kwargs["run_id"])
        return run_original(self, **kwargs)

    monkeypatch.setattr(service, "compile_workflow", compile_together)
    monkeypatch.setattr(runner.WorkflowRunner, "run", count_run)

    def create():
        return ExecutionService(repository_database).create_and_execute(
            workflow_id=workflow_id,
            owner_id=owners["a"],
            data=RunCreateRequest(workflow_version_id=version_id, input={}),
            idempotency_key="race",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create), pool.submit(create)
        results = [first.result(15), second.result(15)]
    assert results[0].id == results[1].id
    assert calls == [results[0].id]
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(RunCommand)) == 1
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 1


async def test_receipt_failure_rolls_back_entire_creation(
    client: AsyncClient, repository_database: Database
) -> None:
    from sqlalchemy import event

    workflow = await saved(client)

    def fail_receipt(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO") and "run_commands" in statement:
            raise OperationalError("private receipt", {}, Exception())

    event.listen(repository_database.engine, "before_cursor_execute", fail_receipt)
    try:
        failed = await execute(client, workflow, "atomic")
        assert failed.status_code == 503 and "location" not in failed.headers
    finally:
        event.remove(repository_database.engine, "before_cursor_execute", fail_receipt)
    with repository_database.session() as session:
        for table in (WorkflowRun, RunCommand, ExecutionEvent):
            assert session.scalar(select(func.count()).select_from(table)) == 0
    assert (await execute(client, workflow, "atomic")).json()["status"] == "succeeded"
