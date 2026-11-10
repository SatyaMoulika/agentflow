"""Protected connections, ownership, actual run history and additive migrations."""

import json
from collections.abc import AsyncIterator
from typing import cast
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.engine import Connection as SqlConnection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import QueuePool

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import Connection
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.connections.service import AuthorizedConnection, ConnectionService
from app.modules.executions import runner
from app.modules.executions.groq_provider import GroqError
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import FailureCode
from app.modules.workflows.repository import WorkflowRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-connections-signing-key-at-least-32-bytes"
PRIVATE = "private-test-connection-credential"


@pytest.fixture
def owners(repository_database: Database) -> tuple[UUID, UUID]:
    with repository_database.unit_of_work() as session:
        repository = UserRepository(session)
        identities = [
            repository.add(
                email=f"{name}@connections.example.com",
                display_name=name,
                password_hash="test-fixture",
            ).id
            for name in ("one", "two")
        ]
        return identities[0], identities[1]


def auth(owner: UUID) -> dict[str, str]:
    tokens = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    return {"Authorization": f"Bearer {tokens.issue(owner)}"}


@pytest.fixture
async def client(
    repository_database: Database, owners: tuple[UUID, UUID], test_database_url: SecretStr
) -> AsyncIterator[AsyncClient]:
    application = create_app(
        Settings(
            jwt_secret_key=SecretStr(KEY),
            connection_encryption_key=SecretStr(Fernet.generate_key().decode()),
            database_url=test_database_url,
            redis_url=SecretStr("redis://127.0.0.1:16380/15"),
            background_execution_enabled=True,
        )
    )

    async def resource() -> Database:
        return repository_database

    application.dependency_overrides[get_database_resource] = resource
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="https://test", headers=auth(owners[0])
    ) as client:
        yield client


async def create(client: AsyncClient, **changes) -> dict:
    response = await client.post(
        "/api/v1/connections",
        json={
            "name": "Status",
            "endpoint_url": "https://api.example.com/status",
            "auth_type": "bearer",
            "secret": PRIVATE,
        }
        | changes,
    )
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["location"].endswith(response.json()["id"])
    assert PRIVATE not in response.text and "secret" not in response.json()
    return response.json()


def saved(database: Database, owner: UUID, connection: str) -> tuple[UUID, UUID]:
    definition = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {"id": "read", "type": "http", "config": {"connection_id": connection}},
            {"id": "finish", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "read"},
            {"id": "b", "source": "read", "target": "finish"},
        ],
    }
    with database.unit_of_work() as session:
        repository = WorkflowRepository(session)
        workflow = repository.add(owner_id=owner, name="HTTP workflow")
        version = repository.append_version(
            workflow_id=workflow.id, owner_id=owner, expected_version=0, definition=definition
        )
        return workflow.id, version.id


async def test_create_list_and_revoke_are_owned_and_never_return_ciphertext_or_secret(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    caplog,
) -> None:
    row = await create(client)
    with repository_database.session() as session:
        token = session.scalar(
            select(Connection.encrypted_secret).where(Connection.id == UUID(row["id"]))
        )
        assert token is not None and PRIVATE not in token
    page = await client.get("/api/v1/connections")
    assert page.json()["total"] == 1 and page.json()["items"] == [row]
    assert PRIVATE not in page.text + caplog.text and token not in page.text
    foreign_headers = auth(owners[1])
    assert (await client.get("/api/v1/connections", headers=foreign_headers)).json()["total"] == 0
    for identity in (row["id"], str(uuid4())):
        for method in (client.get, client.delete):
            response = await method(f"/api/v1/connections/{identity}", headers=foreign_headers)
            assert response.status_code == 404
    for _ in range(2):
        response = await client.delete(f"/api/v1/connections/{row['id']}")
        assert response.status_code == 204 and not response.content
    revoked = await client.get(f"/api/v1/connections/{row['id']}")
    assert revoked.json()["revoked_at"] is not None
    with repository_database.session() as session:
        retained = session.get(Connection, UUID(row["id"]))
        assert retained is not None and retained.encrypted_secret is None


async def test_http_workflow_stores_real_results_outside_transactions_and_is_idempotent(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await create(client)
    workflow, version = saved(repository_database, owners[0], connection["id"])
    calls = []
    baseline = cast(QueuePool, repository_database.engine.pool).checkedout()

    def execute(value: AuthorizedConnection):
        assert cast(QueuePool, repository_database.engine.pool).checkedout() == baseline
        assert value.secret is not None and value.secret.get_secret_value() == PRIVATE
        assert value.endpoint_url == "https://api.example.com/status"
        calls.append(1)
        return {"status_code": 200, "body": {"CustomerID": 42}}

    monkeypatch.setattr(runner, "get_json", execute)
    payload = {
        "workflow_version_id": str(version),
        "input": {"BusinessKey": 123},
        "max_attempts": 3,
    }
    headers = {"Idempotency-Key": "connection-run"}
    response = await client.post(
        f"/api/v1/workflows/{workflow}/runs", json=payload, headers=headers
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "succeeded" and run["execution_mode"] == "synchronous"
    assert run["output"] == {"status_code": 200, "body": {"CustomerID": 42}}
    assert PRIVATE not in response.text
    repeat = await client.post(f"/api/v1/workflows/{workflow}/runs", json=payload, headers=headers)
    assert repeat.json()["id"] == run["id"] and calls == [1]
    assert (await client.get(f"/api/v1/runs/{run['id']}")).json() == run
    events = await client.get(f"/api/v1/runs/{run['id']}/events")
    sequences = [item["sequence"] for item in events.json()["items"]]
    assert sequences == list(range(1, run["event_sequence"] + 1))
    assert PRIVATE not in events.text


@pytest.mark.parametrize("state", ["revoked", "unowned", "missing"])
async def test_unavailable_connections_fail_once_and_are_never_called_or_retried(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    connection = await create(client)
    identity = connection["id"]
    if state == "revoked":
        await client.delete(f"/api/v1/connections/{identity}")
    if state == "missing":
        identity = str(uuid4())
    owner = owners[1] if state == "unowned" else owners[0]
    workflow, version = saved(repository_database, owner, identity)

    def forbidden(*args):
        pytest.fail("An unauthorized connection must never perform network I/O")

    monkeypatch.setattr(runner, "get_json", forbidden)
    response = await client.post(
        f"/api/v1/workflows/{workflow}/runs",
        headers=auth(owner),
        json={"workflow_version_id": str(version), "input": {}, "max_attempts": 3},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "failed" and run["error_code"] == "CONNECTION_UNAVAILABLE"
    assert len([item for item in run["node_runs"] if item["node_id"] == "read"]) == 1
    assert (
        await client.post(f"/api/v1/runs/{run['id']}/retry", headers=auth(owner), json={})
    ).status_code == 422


async def test_http_timeout_is_not_automatically_replayed(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = await create(client)
    workflow, version = saved(repository_database, owners[0], connection["id"])
    calls = []

    def timeout(value):
        calls.append(1)
        raise NodeExecutionError(FailureCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(runner, "get_json", timeout)
    response = await client.post(
        f"/api/v1/workflows/{workflow}/runs",
        json={
            "workflow_version_id": str(version),
            "input": {},
            "max_attempts": 3,
        },
    )
    assert response.status_code == 201 and calls == [1]
    assert response.json()["error_code"] == "DEADLINE_EXCEEDED"
    assert len([row for row in response.json()["node_runs"] if row["node_id"] == "read"]) == 1


async def test_cancel_during_http_call_cannot_be_overwritten_by_its_response(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.database.models import WorkflowRun

    connection = await create(client)
    workflow, version = saved(repository_database, owners[0], connection["id"])

    def execute(value):
        with repository_database.session() as session:
            run_id = session.scalar(
                select(WorkflowRun.id).where(WorkflowRun.workflow_id == workflow)
            )
        assert run_id is not None
        ExecutionService(repository_database).cancel(run_id=run_id, owner_id=owners[0])
        return {"status_code": 200, "body": {"late": True}}

    monkeypatch.setattr(runner, "get_json", execute)
    response = await client.post(
        f"/api/v1/workflows/{workflow}/runs",
        json={
            "workflow_version_id": str(version),
            "input": {},
        },
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "cancelled" and run["output"] is None
    attempt = next(row for row in run["node_runs"] if row["node_id"] == "read")
    assert attempt["status"] == "cancelled" and attempt["output"] is None


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE connections SET endpoint_url='https://other.example.com/' WHERE id=:id",
        "UPDATE connections SET owner_id=:other WHERE id=:id",
        "UPDATE connections SET encrypted_secret='replacement' WHERE id=:id",
        "DELETE FROM connections WHERE id=:id",
        "TRUNCATE connections",
    ],
)
async def test_connection_identity_and_history_are_guarded_in_postgresql(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    statement: str,
    migrated_connection: SqlConnection,
) -> None:
    row = await create(client)
    schema = migrated_connection.scalar(text("SELECT current_schema()"))
    statement = statement.replace("connections", f'"{schema}".connections')
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        session.execute(text(statement), {"id": UUID(row["id"]), "other": owners[1]})
    assert (await client.get(f"/api/v1/connections/{row['id']}")).json() == row


def test_additive_connection_migration_preserves_users_and_refuses_history_downgrade(
    migration_environment: tuple[SqlConnection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0008")
    user = connection.scalar(
        text(
            "INSERT INTO users (email, display_name, password_hash) "
            "VALUES ('migration@connections.example.com','Owner','fixture') RETURNING id"
        )
    )
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT id FROM users")) == user
    connection.commit()
    command.downgrade(config, "0008")
    assert connection.scalar(text("SELECT id FROM users")) == user
    connection.commit()
    command.upgrade(config, "head")
    connection.execute(
        text(
            "INSERT INTO connections (owner_id,name,endpoint_url,auth_type) "
            "VALUES (:owner,'Public','https://example.com/','none')"
        ),
        {"owner": user},
    )
    connection.commit()
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0008")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"
    assert connection.scalar(text("SELECT count(*) FROM connections")) == 1


def http_proposal(identity: str) -> dict:
    return {
        "status": "ready",
        "message": "Review the authorized endpoint.",
        "name": "Status",
        "description": "Read status",
        "sample_input": {},
        "definition": {
            "schema_version": "1.0",
            "nodes": [
                {"id": "start", "type": "manual", "config": {}},
                {"id": "read", "type": "http", "config": {"connection_id": identity}},
                {"id": "finish", "type": "end", "config": {}},
            ],
            "edges": [
                {"id": "a", "source": "start", "target": "read"},
                {"id": "b", "source": "read", "target": "finish"},
            ],
        },
    }


async def test_selected_owned_catalog_is_read_only_and_does_not_decrypt_or_call_endpoints(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch,
) -> None:
    from app.infrastructure.database.models import Workflow

    selected = await create(client)
    hidden = await create(
        client, name="Do not share this connection", endpoint_url="https://hidden.example.com/"
    )
    baseline = cast(QueuePool, repository_database.engine.pool).checkedout()
    calls = []

    def complete(settings, prompt, *, json_mode=False):
        assert cast(QueuePool, repository_database.engine.pool).checkedout() == baseline
        assert selected["id"] in prompt and selected["endpoint_url"] in prompt
        assert hidden["id"] not in prompt and hidden["endpoint_url"] not in prompt
        assert PRIVATE not in prompt
        calls.append(1)
        return {"model": "test-model", "content": json.dumps(http_proposal(selected["id"]))}

    def forbidden(*args, **kwargs):
        pytest.fail("Planning must not decrypt credentials or call an endpoint")

    monkeypatch.setattr("app.modules.workflows.generation.complete", complete)
    monkeypatch.setattr("app.modules.connections.service.decrypt", forbidden)
    monkeypatch.setattr(runner, "get_json", forbidden)
    response = await client.post(
        "/api/v1/workflows/generate",
        json={
            "prompt": "Read the selected status endpoint",
            "connection_ids": [selected["id"]],
        },
    )
    assert response.status_code == 200 and response.json()["status"] == "ready" and calls == [1]
    assert response.json()["connections"] == [
        {"id": selected["id"], "name": "Status", "endpoint_url": selected["endpoint_url"]}
    ]
    assert PRIVATE not in response.text
    with repository_database.session() as session:
        assert session.scalar(select(Workflow.id)) is None


@pytest.mark.parametrize("state", ["unowned", "revoked", "missing", "duplicate"])
async def test_invalid_planner_selection_is_rejected_before_provider_call(
    client: AsyncClient,
    owners: tuple[UUID, UUID],
    state: str,
    monkeypatch,
) -> None:
    selected = await create(client)
    if state == "revoked":
        await client.delete(f"/api/v1/connections/{selected['id']}")
    identities = [str(uuid4()) if state == "missing" else selected["id"]]
    if state == "duplicate":
        identities *= 2

    def forbidden(*args, **kwargs):
        pytest.fail("Unauthorized catalog selections must not consume provider quota")

    monkeypatch.setattr("app.modules.workflows.generation.complete", forbidden)
    response = await client.post(
        "/api/v1/workflows/generate",
        headers=auth(owners[1] if state == "unowned" else owners[0]),
        json={"prompt": "Read status", "connection_ids": identities},
    )
    assert response.status_code == (422 if state == "duplicate" else 404)


async def test_model_cannot_use_an_owned_but_unselected_connection(
    client: AsyncClient, monkeypatch
) -> None:
    selected = await create(client)
    monkeypatch.setattr(
        "app.modules.workflows.generation.complete",
        lambda *a, **kw: {
            "model": "test-model",
            "content": json.dumps(http_proposal(selected["id"])),
        },
    )
    response = await client.post("/api/v1/workflows/generate", json={"prompt": "Read status"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "GENERATION_INVALID"


async def test_revocation_during_generation_rejects_the_result(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch,
) -> None:
    selected = await create(client)

    def complete(settings, *args, **kwargs):
        ConnectionService(repository_database, settings).revoke(owners[0], UUID(selected["id"]))
        return {"model": "test-model", "content": json.dumps(http_proposal(selected["id"]))}

    monkeypatch.setattr("app.modules.workflows.generation.complete", complete)
    response = await client.post(
        "/api/v1/workflows/generate",
        json={
            "prompt": "Read status",
            "connection_ids": [selected["id"]],
        },
    )
    assert response.status_code == 404


async def test_edit_rechecks_saved_and_new_bindings_without_saving_a_version(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch,
) -> None:
    original = await create(client)
    replacement = await create(
        client, name="Replacement", endpoint_url="https://replacement.example.com/"
    )
    workflow, version = saved(repository_database, owners[0], original["id"])
    monkeypatch.setattr(
        "app.modules.workflows.generation.complete",
        lambda *a, **kw: {
            "model": "test-model",
            "content": json.dumps(http_proposal(replacement["id"])),
        },
    )
    url = f"/api/v1/workflows/{workflow}/edit-proposal"
    data = {"base_version_id": str(version), "prompt": "Change the HTTP connection"}
    denied = await client.post(url, json=data)
    assert denied.status_code == 502
    allowed = await client.post(url, json=data | {"connection_ids": [replacement["id"]]})
    assert allowed.status_code == 200
    assert {row["id"] for row in allowed.json()["connections"]} == {
        original["id"],
        replacement["id"],
    }
    current = await client.get(f"/api/v1/workflows/{workflow}")
    assert current.json()["current_version_id"] == str(version)


@pytest.mark.parametrize("failure", [False, True])
async def test_provider_metadata_is_retained_in_events_without_changing_business_output(
    client: AsyncClient,
    repository_database: Database,
    owners: tuple[UUID, UUID],
    monkeypatch,
    failure,
) -> None:
    from copy import deepcopy

    from app.infrastructure.database.models import ExecutionEvent

    definition = deepcopy(http_proposal(str(uuid4()))["definition"])
    definition["nodes"][1] = {
        "id": "read",
        "type": "groq",
        "config": {"instruction": "Reply", "input_field": "message"},
    }
    with repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        workflow = repo.add(owner_id=owners[0], name="Provider metadata")
        version = repo.append_version(
            workflow_id=workflow.id, owner_id=owners[0], expected_version=0, definition=definition
        )
        workflow_id, version_id = workflow.id, version.id
    metadata = {
        "provider": "groq",
        "requested_model": "requested-model",
        "model": "reported-model",
        "duration_ms": 12,
        "usage": {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7},
    }
    if failure:
        metadata.update(error_code="PROVIDER_RATE_LIMITED", retry_after_seconds=2)
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        if failure:
            raise GroqError(429, metadata=metadata, retry_after=2)
        return {"model": "reported-model", "content": "Synthetic reply", "metadata": metadata}

    monkeypatch.setattr(runner, "complete", complete)
    command = {
        "workflow_version_id": str(version_id),
        "input": {"message": "Synthetic"},
        "max_attempts": 3,
    }
    headers = {"Idempotency-Key": "provider-metadata"}
    response = await client.post(
        f"/api/v1/workflows/{workflow_id}/runs", json=command, headers=headers
    )
    assert response.status_code == 201 and calls == [1]
    run = response.json()
    assert run["output"] == (
        None if failure else {"model": "reported-model", "content": "Synthetic reply"}
    )
    assert run["error_code"] == ("PROVIDER_RATE_LIMITED" if failure else None)
    row = next(node for node in run["node_runs"] if node["node_id"] == "read")
    assert row["provider"]["usage"]["total_tokens"] == 7
    assert row["provider"]["model"] == "reported-model"
    replay = await client.post(
        f"/api/v1/workflows/{workflow_id}/runs", json=command, headers=headers
    )
    assert replay.json() == run and calls == [1]
    with repository_database.session() as session:
        event = session.scalar(
            select(ExecutionEvent).where(
                ExecutionEvent.node_run_id == UUID(row["id"]),
                ExecutionEvent.event_payload.op("?")("provider"),
            )
        )
        assert event is not None and event.event_payload["provider"] == metadata
