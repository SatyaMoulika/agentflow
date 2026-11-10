"""Owner-scoped agent API execution, atomic history, replay and cancellation in isolated schemas."""

import json
from copy import deepcopy
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import ExecutionEvent, WorkflowDispatch
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.executions import groq_provider
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import EventType
from app.modules.workflows.repository import WorkflowRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "isolated-agent-auth-key-with-at-least-32-bytes"
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "agent",
            "type": "agent",
            "config": {
                "instruction": "Use the calculator.",
                "input_field": "message",
                "max_tool_rounds": 1,
            },
        },
        {"id": "finish", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "a", "source": "start", "target": "agent"},
        {"id": "b", "source": "agent", "target": "finish"},
    ],
}


@pytest.fixture
async def prepared(repository_database, test_database_url):
    with repository_database.unit_of_work() as session:
        users = UserRepository(session)
        owner = users.add(
            email="agent-owner@example.com", display_name="Owner", password_hash="fixture"
        )
        other = users.add(
            email="agent-other@example.com", display_name="Other", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Calculator agent")
        version = workflows.append_version(
            workflow_id=workflow.id,
            owner_id=owner.id,
            expected_version=0,
            definition=deepcopy(GRAPH),
        )
        owner_id, other_id, workflow_id, version_id = owner.id, other.id, workflow.id, version.id
    settings = Settings(
        database_url=test_database_url,
        jwt_secret_key=SecretStr(KEY),
        groq_api_key=SecretStr("synthetic-agent-groq-key"),
        background_execution_enabled=True,
        redis_url=SecretStr("redis://127.0.0.1:1/15"),
    )
    app = create_app(settings)

    async def resource():
        return repository_database

    app.dependency_overrides[get_database_resource] = resource
    tokens = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    headers = {
        "Authorization": f"Bearer {tokens.issue(owner_id)}",
        "Idempotency-Key": "agent-command",
    }
    other_headers = {"Authorization": f"Bearer {tokens.issue(other_id)}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test", headers=headers
    ) as client:
        yield client, repository_database, workflow_id, version_id, owner_id, other_headers


def install(monkeypatch, database, replies, *, during=None):
    calls = []
    original = httpx.Client
    baseline = database.engine.pool.checkedout()

    def handle(request):
        # API/agent cancellation checks must close their transactions before provider I/O.
        assert database.engine.pool.checkedout() == baseline
        calls.append(json.loads(request.content))
        if during is not None:
            during()
        item = replies[len(calls) - 1]
        if item == "rate_limit":
            return httpx.Response(429, headers={"Retry-After": "4"})
        message = (
            {"content": "5"}
            if item is None
            else {
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{len(calls)}",
                        "type": "function",
                        "function": item,
                    }
                ],
            }
        )
        return httpx.Response(
            200,
            json={
                "model": "synthetic-model",
                "choices": [
                    {"message": message, "finish_reason": "stop" if item is None else "tool_calls"}
                ],
                "usage": {"total_tokens": 6},
            },
        )

    monkeypatch.setattr(
        groq_provider.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    return calls


async def start(prepared, *, foreign=False):
    client, _, workflow_id, version_id, _, other_headers = prepared
    return await client.post(
        f"/api/v1/workflows/{workflow_id}/runs",
        json={
            "workflow_version_id": str(version_id),
            "input": {"message": "Add 2 and 3.", "PrivateBusinessKey": "not sent to provider"},
            "max_attempts": 3,
        },
        **({"headers": other_headers} if foreign else {}),
    )


async def test_agent_api_executes_synchronously_and_replays_exact_history(prepared, monkeypatch):
    client, database, _, _, _, other_headers = prepared
    calls = install(
        monkeypatch,
        database,
        [{"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'}, None],
    )
    assert (await start(prepared, foreign=True)).status_code == 404 and calls == []
    created = await start(prepared)
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "succeeded" and run["execution_mode"] == "synchronous"
    assert run["output"]["tool_calls"][0]["result"] == 5
    attempt = next(node for node in run["node_runs"] if node["node_id"] == "agent")
    assert attempt["agent"]["tool_rounds"] == 1 and len(attempt["agent"]["provider_calls"]) == 2
    assert len(calls) == 2 and "PrivateBusinessKey" not in json.dumps(calls)
    assert (await start(prepared)).json() == run and len(calls) == 2
    path = f"/api/v1/runs/{run['id']}"
    assert (await client.get(path)).json() == run
    assert (await client.get(path, headers=other_headers)).status_code == 404
    assert (await client.post(path + "/retry", json={})).status_code == 409
    with database.session() as session:
        assert session.get(WorkflowDispatch, UUID(run["id"])) is None
        events = session.scalars(
            select(ExecutionEvent).where(ExecutionEvent.workflow_run_id == UUID(run["id"]))
        ).all()
        agent_event = next(event for event in events if "agent" in event.event_payload)
        assert agent_event.event_type == EventType.NODE_STATUS_CHANGED
        assert agent_event.event_payload["to_status"] == "succeeded"
        assert "PrivateBusinessKey" not in json.dumps(agent_event.event_payload)


@pytest.mark.parametrize(
    "replies,reason,code,count",
    [
        ([{"name": "http", "arguments": "{}"}], "unknown_tool", "EXECUTION_FAILED", 1),
        (
            [{"name": "calculator", "arguments": '{"operation":"add","operands":[true,3]}'}],
            "invalid_arguments",
            "EXECUTION_FAILED",
            1,
        ),
        (
            [{"name": "calculator", "arguments": '{"operation":"divide","operands":[2,0]}'}],
            "tool_failed",
            "EXECUTION_FAILED",
            1,
        ),
        (
            [{"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'}] * 2,
            "iteration_limit",
            "EXECUTION_FAILED",
            2,
        ),
        (["rate_limit"], "provider_failure", "PROVIDER_RATE_LIMITED", 1),
    ],
)
async def test_agent_failures_keep_specific_history_and_never_auto_retry(
    prepared, monkeypatch, replies, reason, code, count
):
    client, database, _, _, _, _ = prepared
    calls = install(monkeypatch, database, replies)
    response = await start(prepared)
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "failed" and run["error_code"] == code
    attempts = [row for row in run["node_runs"] if row["node_id"] == "agent"]
    assert len(attempts) == 1 and attempts[0]["agent"]["failure_reason"] == reason
    assert len(calls) == count
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json() == run
    assert (await client.post(f"/api/v1/runs/{run['id']}/retry", json={})).status_code == 409


async def test_cancellation_after_first_model_call_prevents_tool_and_followup(
    prepared, monkeypatch
):
    _, database, _, _, owner_id, _ = prepared

    def cancel():
        with database.session() as session:
            from app.infrastructure.database.models import WorkflowRun

            run_id = session.scalar(select(WorkflowRun.id))
        ExecutionService(database).cancel(run_id=run_id, owner_id=owner_id)

    calls = install(
        monkeypatch,
        database,
        [{"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'}],
        during=cancel,
    )
    run = (await start(prepared)).json()
    assert run["status"] == "cancelled" and run["output"] is None and len(calls) == 1
    agent = next(row for row in run["node_runs"] if row["node_id"] == "agent")
    assert agent["status"] == "cancelled" and agent["output"] is None


async def test_agent_result_and_metadata_roll_back_together_on_storage_failure(
    prepared, monkeypatch
):
    _, database, _, _, owner_id, _ = prepared
    calls = install(monkeypatch, database, [None])
    original = ExecutionRepository._event

    def fail(self, run, kind, payload, *args, **kwargs):
        original(self, run, kind, payload, *args, **kwargs)
        if "agent" in payload:
            self.session.flush()
            raise OperationalError("synthetic storage failure", None, Exception())

    monkeypatch.setattr(ExecutionRepository, "_event", fail)
    response = await start(prepared)
    assert response.status_code == 503 and len(calls) == 1
    run_id = UUID(response.headers["Location"].rsplit("/", 1)[-1])
    detail = ExecutionService(database).get(run_id=run_id, owner_id=owner_id)
    agent = next(row for row in detail.node_runs if row.node_id == "agent")
    assert agent.status == "running" and agent.output is None and agent.agent is None
