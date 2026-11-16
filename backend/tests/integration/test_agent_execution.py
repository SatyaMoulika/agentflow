"""Owner-scoped agent API execution, atomic history, replay and cancellation in isolated schemas."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import ExecutionEvent, WorkflowDispatch
from app.main import create_app
from app.modules.agents import http_tools
from app.modules.auth.repository import UserRepository
from app.modules.executions import groq_provider
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import EventType, FailureCode
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
async def prepared(agent_database, test_database_url):
    repository_database = agent_database
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
        connection_encryption_key=SecretStr(Fernet.generate_key().decode()),
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


async def connection(prepared, **changes):
    response = await prepared[0].post(
        "/api/v1/connections",
        json={
            "name": "Agent status",
            "endpoint_url": "https://api.example.com/status",
            **changes,
        },
    )
    assert response.status_code == 201
    return response.json()


def bind(prepared, identities, *, rounds=3, pause=False):
    client, database, workflow_id, _, owner_id, headers = prepared
    graph = deepcopy(GRAPH)
    graph["nodes"][1]["config"].update(
        connection_ids=identities, max_tool_rounds=rounds, pause_after_tools=pause
    )
    with database.unit_of_work() as session:
        current = WorkflowRepository(session).get_owned(workflow_id=workflow_id, owner_id=owner_id)
        assert current is not None and current.current_version is not None
        version = WorkflowRepository(session).append_version(
            workflow_id=workflow_id,
            owner_id=owner_id,
            expected_version=current.current_version.version_number,
            definition=graph,
        )
        version_id = version.id
    return client, database, workflow_id, version_id, owner_id, headers


def http_reply(identity, **extra):
    return {"name": "http_get", "arguments": json.dumps({"connection_id": identity, **extra})}


def http_transport(monkeypatch, database, *, during=None, failure=None):
    calls = []
    baseline = database.engine.pool.checkedout()

    def get(connection, **kwargs):
        assert database.engine.pool.checkedout() == baseline
        assert 0 < kwargs["timeout_seconds"] <= 60 and kwargs["max_response_bytes"] == 16384
        calls.append(connection)
        if during:
            during()
        if failure:
            raise NodeExecutionError(failure)
        return {"status_code": 200, "body": {"CustomerID": 42, "UnitPrice": 7}}

    monkeypatch.setattr(http_tools, "get_json", get)
    return calls


async def test_http_agent_consumes_binding_and_persists_history_without_credentials(
    prepared, monkeypatch
):
    _, database, _, _, _, _ = prepared
    selected = await connection(
        prepared, auth_type="bearer", secret="private-agent-http-credential"
    )
    hidden = await connection(
        prepared, name="Unselected", endpoint_url="https://hidden.example.com/"
    )
    bound = bind(prepared, [selected["id"]])
    provider = install(monkeypatch, database, [http_reply(selected["id"]), None])
    http_calls = http_transport(monkeypatch, database)
    created = await start(bound)
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "succeeded" and run["execution_mode"] == "synchronous"
    assert run["output"]["tool_calls"][0] == {
        "id": "call_1",
        "tool": "http_get",
        "connection_id": selected["id"],
        "status_code": 200,
        "body": {"CustomerID": 42, "UnitPrice": 7},
    }
    assert (
        len(http_calls) == 1
        and http_calls[0].secret.get_secret_value() == "private-agent-http-credential"
    )
    sent = json.dumps(provider)
    assert (
        "private-agent-http-credential" not in sent
        and hidden["id"] not in sent
        and hidden["endpoint_url"] not in sent
    )
    assert "PrivateBusinessKey" not in sent
    assert json.loads(provider[1]["messages"][-1]["content"])["body"]["CustomerID"] == 42
    attempt = next(row for row in run["node_runs"] if row["node_id"] == "agent")
    assert attempt["agent"]["http_calls"] == [
        {"connection_id": selected["id"], "status_code": 200, "error_code": None}
    ]
    assert attempt["agent"]["http_tool_attempts"] == attempt["agent"]["tool_rounds"] == 1
    assert (await start(bound)).json() == run
    assert len(provider) == 2 and len(http_calls) == 1
    with database.session() as session:
        events = session.scalars(
            select(ExecutionEvent).where(ExecutionEvent.workflow_run_id == UUID(run["id"]))
        ).all()
        event = next(row for row in events if "agent" in row.event_payload)
        assert event.event_payload["agent"]["http_calls"] == [
            {"connection_id": selected["id"], "status_code": 200}
        ]
        assert "private-agent-http-credential" not in json.dumps(
            [row.event_payload for row in events]
        )


@pytest.mark.parametrize("state", ["missing", "unowned", "revoked"])
async def test_invalid_http_agent_bindings_fail_before_network_or_decryption(
    prepared, monkeypatch, state
):
    client, database, _, _, _, other = prepared
    selected = await connection(prepared)
    identity = selected["id"]
    if state == "missing":
        identity = str(uuid4())
    elif state == "unowned":
        result = await client.post(
            "/api/v1/connections",
            headers=other,
            json={"name": "Other owner", "endpoint_url": "https://other.example.com/"},
        )
        assert result.status_code == 201
        identity = result.json()["id"]
    else:
        assert (await client.delete(f"/api/v1/connections/{identity}")).status_code == 204
    bound = bind(prepared, [identity])
    provider = install(monkeypatch, database, [])
    http_calls = http_transport(monkeypatch, database)
    monkeypatch.setattr(
        "app.modules.connections.service.decrypt",
        lambda *args: pytest.fail("Catalog must not decrypt"),
    )
    result = await start(bound)
    run = result.json()
    assert result.status_code == 201 and run["error_code"] == "CONNECTION_UNAVAILABLE"
    assert provider == http_calls == []
    attempt = next(row for row in run["node_runs"] if row["node_id"] == "agent")
    assert attempt["agent"]["failure_reason"] == "connection_unavailable"
    assert attempt["agent"]["http_tool_attempts"] == 0


def revoke(database, identity):
    from sqlalchemy import func

    from app.modules.connections.models import Connection

    with database.unit_of_work() as session:
        row = session.get(Connection, UUID(identity))
        row.revoked_at = session.scalar(select(func.clock_timestamp()))
        row.encrypted_secret = None


async def test_revocation_while_model_selects_http_blocks_endpoint(prepared, monkeypatch):
    client, database, _, _, _, _ = prepared
    selected = await connection(prepared)
    bound = bind(prepared, [selected["id"]])
    provider = install(
        monkeypatch,
        database,
        [http_reply(selected["id"])],
        during=lambda: revoke(database, selected["id"]),
    )
    http_calls = http_transport(monkeypatch, database)
    run = (await start(bound)).json()
    assert run["error_code"] == "CONNECTION_UNAVAILABLE" and len(provider) == 1 and http_calls == []
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json() == run


async def test_revocation_after_http_result_stops_next_model_turn(prepared, monkeypatch):
    _, database, _, _, _, _ = prepared
    selected = await connection(prepared)
    bound = bind(prepared, [selected["id"]])
    provider = install(monkeypatch, database, [http_reply(selected["id"])])
    http_calls = http_transport(
        monkeypatch, database, during=lambda: revoke(database, selected["id"])
    )
    run = (await start(bound)).json()
    assert run["error_code"] == "CONNECTION_UNAVAILABLE" and len(provider) == len(http_calls) == 1
    attempt = next(row for row in run["node_runs"] if row["node_id"] == "agent")
    assert attempt["agent"]["http_calls"] == [
        {"connection_id": selected["id"], "status_code": 200, "error_code": None}
    ]
    assert attempt["output"] is None


@pytest.mark.parametrize(
    "failure",
    [
        FailureCode.HTTP_TARGET_BLOCKED,
        FailureCode.HTTP_REQUEST_FAILED,
        FailureCode.DEADLINE_EXCEEDED,
    ],
)
async def test_http_agent_network_failures_persist_and_never_replay(prepared, monkeypatch, failure):
    _, database, _, _, _, _ = prepared
    selected = await connection(prepared)
    bound = bind(prepared, [selected["id"]])
    provider = install(monkeypatch, database, [http_reply(selected["id"])])
    http_calls = http_transport(monkeypatch, database, failure=failure)
    run = (await start(bound)).json()
    assert run["error_code"] == failure.value and len(provider) == len(http_calls) == 1
    attempt = next(row for row in run["node_runs"] if row["node_id"] == "agent")
    assert attempt["agent"]["failure_reason"] == "http_failure"
    assert attempt["agent"]["http_calls"] == [
        {"connection_id": selected["id"], "status_code": None, "error_code": failure.value}
    ]
    assert (await start(bound)).json() == run and len(http_calls) == 1


async def test_cancellation_during_http_prevents_result_and_next_provider_call(
    prepared, monkeypatch
):
    _, database, _, _, owner_id, _ = prepared
    selected = await connection(prepared)
    bound = bind(prepared, [selected["id"]])

    def cancel():
        from app.infrastructure.database.models import WorkflowRun

        with database.session() as session:
            run_id = session.scalar(select(WorkflowRun.id))
        ExecutionService(database).cancel(run_id=run_id, owner_id=owner_id)

    provider = install(monkeypatch, database, [http_reply(selected["id"])])
    http_calls = http_transport(monkeypatch, database, during=cancel)
    run = (await start(bound)).json()
    assert run["status"] == "cancelled" and run["output"] is None
    assert len(provider) == len(http_calls) == 1


def paused_attempt(run):
    return next(
        row for row in run["node_runs"] if (row.get("checkpoint") or {}).get("status") == "paused"
    )


async def resume(client, run, attempt=None, **kwargs):
    row = paused_attempt(run) if attempt is None else attempt
    return await client.post(
        f"/api/v1/runs/{run['id']}/agent-resume",
        json={"node_run_id": row["id"], "checkpoint_id": row["checkpoint"]["checkpoint_id"]},
        **kwargs,
    )


async def test_durable_calculator_pause_survives_new_database_and_app(prepared, monkeypatch):
    from app.infrastructure.database.session import Database

    client, database, _, _, _, _ = prepared
    bound = bind(prepared, [], rounds=1, pause=True)
    calls = install(
        monkeypatch,
        database,
        [
            {"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'},
            None,
        ],
    )
    run = (await start(bound)).json()
    row = paused_attempt(run)
    assert run["status"] == row["status"] == "running" and run["output"] is None
    assert row["agent"]["tool_rounds"] == 1 and len(calls) == 1
    assert [item["node_id"] for item in run["node_runs"]] == ["start", "agent"]
    # Recreate both the process-local engine and the API application. Continuation
    # must read PostgreSQL state, not a graph object/saver retained by the first request.
    settings = Settings(
        database_url=SecretStr(database.engine.url.render_as_string(hide_password=False)),
        jwt_secret_key=SecretStr(KEY),
        groq_api_key=SecretStr("synthetic-agent-groq-key"),
    )
    assert settings.database_url is not None
    fresh = Database(settings.database_url)
    fresh.engine = fresh.engine.execution_options(**database.engine.get_execution_options())
    fresh.session_factory.configure(bind=fresh.engine)
    app = create_app(settings)

    async def resource():
        return fresh

    app.dependency_overrides[get_database_resource] = resource
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="https://test",
            headers={"Authorization": client.headers["Authorization"]},
        ) as other:
            assert (await other.get(f"/api/v1/runs/{run['id']}")).json() == run
            result = await resume(other, run)
            assert result.status_code == 200
            done = result.json()
            assert done["status"] == "succeeded" and len(calls) == 2
            agent = next(item for item in done["node_runs"] if item["id"] == row["id"])
            assert agent["attempt_number"] == 1 and agent["checkpoint"]["resume_count"] == 1
            assert agent["checkpoint"]["thread_id"] == row["checkpoint"]["thread_id"]
            assert agent["checkpoint"]["status"] == "completed"
            assert len(agent["agent"]["provider_calls"]) == 2
            assert done["output"]["tool_calls"][0]["result"] == 5
            assert (await resume(other, run, row)).status_code == 409 and len(calls) == 2
            events = (await other.get(f"/api/v1/runs/{run['id']}/events")).json()["items"]
            assert sum(item["event_type"] == "agent.checkpointed" for item in events) == 1
            assert sum(item["event_type"] == "agent.resumed" for item in events) == 1
            assert [item["sequence"] for item in events] == list(range(1, len(events) + 1))
    finally:
        fresh.dispose()


@pytest.mark.parametrize("revoke", [False, True])
async def test_paused_http_is_not_repeated_and_revocation_blocks_next_model(
    prepared,
    monkeypatch,
    revoke,
):
    client, database, _, _, _, _ = prepared
    selected = await connection(prepared)
    bound = bind(prepared, [selected["id"]], pause=True)
    calls = install(monkeypatch, database, [http_reply(selected["id"]), None])
    http_calls = http_transport(monkeypatch, database)
    run = (await start(bound)).json()
    row = paused_attempt(run)
    assert len(calls) == len(http_calls) == 1
    if revoke:
        assert (await client.delete(f"/api/v1/connections/{selected['id']}")).status_code == 204
    done = (await resume(client, run)).json()
    assert len(http_calls) == 1
    agent = next(item for item in done["node_runs"] if item["id"] == row["id"])
    assert agent["agent"]["tool_rounds"] == 1
    assert agent["agent"]["http_tool_attempts"] == 1
    if revoke:
        assert done["error_code"] == "CONNECTION_UNAVAILABLE" and len(calls) == 1
        assert len(agent["agent"]["provider_calls"]) == 1
    else:
        assert done["status"] == "succeeded" and len(calls) == 2
        assert done["output"]["tool_calls"][0]["body"]["CustomerID"] == 42
    assert (await resume(client, run, row)).status_code == 409


async def test_owner_stale_and_cancelled_pauses_never_resume(prepared, monkeypatch):
    client, database, _, _, owner_id, foreign = prepared
    bound = bind(prepared, [], pause=True)
    calls = install(
        monkeypatch,
        database,
        [
            {"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'},
        ],
    )
    run = (await start(bound)).json()
    row = paused_attempt(run)
    assert (await resume(client, run, headers=foreign)).status_code == 404
    stale = deepcopy(row)
    stale["checkpoint"]["checkpoint_id"] = str(uuid4())
    assert (await resume(client, run, stale)).status_code == 409
    missing = deepcopy(row)
    missing["id"] = str(uuid4())
    assert (await resume(client, run, missing)).status_code == 404
    assert (
        await client.post(
            f"/api/v1/runs/{run['id']}/agent-resume",
            json={
                "node_run_id": row["id"],
                "checkpoint_id": row["checkpoint"]["checkpoint_id"],
                "input": {},
            },
        )
    ).status_code == 422
    cancelled = ExecutionService(database).cancel(run_id=UUID(run["id"]), owner_id=owner_id)
    assert cancelled.status == "cancelled"
    assert cancelled.node_runs[-1].checkpoint is not None
    assert cancelled.node_runs[-1].checkpoint.status == "cancelled"
    assert (await resume(client, run, row)).status_code == 409 and len(calls) == 1


async def test_running_invocation_is_not_a_recovery_grant(prepared, monkeypatch):
    from app.modules.agents.models import AgentInvocation
    from app.modules.agents.schemas import AgentResumeRequest
    from app.modules.executions.exceptions import ExecutionConflictError

    client, database, _, _, owner_id, _ = prepared
    refused = []

    def during():
        with database.session() as session:
            invocation = session.scalar(select(AgentInvocation))
            run_id, attempt_id = invocation.workflow_run_id, invocation.node_run_id
        with pytest.raises(ExecutionConflictError):
            ExecutionService(database).resume_agent(
                run_id=run_id,
                owner_id=owner_id,
                data=AgentResumeRequest(node_run_id=attempt_id, checkpoint_id=str(uuid4())),
            )
        refused.append(True)

    calls = install(monkeypatch, database, [None], during=during)
    run = (await start(prepared)).json()
    assert run["status"] == "succeeded" and refused == [True] and len(calls) == 1


async def test_missing_checkpoint_storage_refuses_before_provider(prepared, monkeypatch):
    from app.modules.agents.checkpoints import checkpoint_schema

    _, database, _, _, _, _ = prepared
    with database.engine.begin() as session:
        schema = checkpoint_schema(database)
        assert schema.startswith("test_")
        session.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
    calls = install(monkeypatch, database, [])
    result = await start(prepared)
    assert result.status_code == 503 and calls == []
    assert result.headers["location"].startswith("/api/v1/runs/")


async def test_concurrent_resume_consumes_only_one_checkpoint(prepared, monkeypatch):
    import asyncio

    client, database, _, _, _, _ = prepared
    bound = bind(prepared, [], pause=True)
    calls = install(
        monkeypatch,
        database,
        [
            {"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'},
            None,
        ],
    )
    run = (await start(bound)).json()
    results = await asyncio.gather(resume(client, run), resume(client, run))
    assert sorted(item.status_code for item in results) == [200, 409]
    assert len(calls) == 2
    result = next(item.json() for item in results if item.status_code == 200)
    assert result["status"] == "succeeded"
    assert len([row for row in result["node_runs"] if row["node_id"] == "agent"]) == 1


async def test_invocation_identity_history_and_migration_are_retained(
    prepared,
    monkeypatch,
    migration_environment,
):
    from alembic import command
    from sqlalchemy import delete, update
    from sqlalchemy.exc import IntegrityError

    from app.modules.agents.checkpoints import setup_checkpoints
    from app.modules.agents.models import AgentInvocation

    client, database, _, _, _, _ = prepared
    calls = install(
        monkeypatch,
        database,
        [
            {"name": "calculator", "arguments": '{"operation":"add","operands":[2,3]}'},
        ],
    )
    run = (await start(bind(prepared, [], pause=True))).json()
    row = paused_attempt(run)
    for statement in [
        update(AgentInvocation).values(thread_id=uuid4()),
        update(AgentInvocation).values(status="completed"),
        delete(AgentInvocation),
    ]:
        with pytest.raises(IntegrityError), database.unit_of_work() as session:
            session.execute(statement)
    connection, config = migration_environment
    connection.rollback()
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0010")
    connection.rollback()
    setup_checkpoints(database)  # Maintained saver setup is repeatable and preserves data.
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json() == run
    assert len(calls) == 1 and row["checkpoint"]["status"] == "paused"
