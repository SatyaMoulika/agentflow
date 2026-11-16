"""Gmail OAuth state and credentials use the disposable PostgreSQL test schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.pool import QueuePool

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.executions.schemas import RunCreateRequest
from app.modules.executions.service import ExecutionService
from app.modules.gmail import provider
from app.modules.gmail.models import GmailAuthorization, GmailConnection
from app.modules.gmail.service import (
    GmailAuthorizationRejected,
    GmailConnectionNotFound,
    GmailNotConfigured,
    GmailService,
)
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration


@pytest.fixture
def setup(repository_database: Database):
    with repository_database.unit_of_work() as session:
        repository = UserRepository(session)
        owners = [
            repository.add(
                email=f"{uuid4().hex}@example.com", display_name="Fixture", password_hash="test"
            ).id
            for _ in range(2)
        ]
    settings = Settings(
        gmail_client_id="fixture-client",
        gmail_client_secret=SecretStr("private-client-secret"),
        gmail_redirect_uri="http://localhost:5173/integrations/gmail/callback",
        connection_encryption_key=SecretStr(Fernet.generate_key().decode()),
    )
    return GmailService(repository_database, settings), owners


def state_for(service: GmailService, owner):
    return parse_qs(urlsplit(service.begin(owner)).query)["state"][0]


def test_missing_configuration_refuses_before_google_or_state_creation(setup):
    service, (owner, _) = setup
    service.settings = Settings()
    with pytest.raises(GmailNotConfigured):
        service.begin(owner)
    with service.database.session() as session:
        assert session.scalar(select(GmailAuthorization)) is None


def test_owner_bound_single_use_state_and_encrypted_revocable_refresh(setup, monkeypatch):
    service, (owner, foreign) = setup
    state = state_for(service, owner)
    calls = []
    pool = service.database.engine.pool
    assert isinstance(pool, QueuePool)
    baseline = pool.checkedout()

    def exchange(**kwargs):
        assert pool.checkedout() == baseline
        calls.append(1)
        return provider.OAuthToken(SecretStr("private-access"), SecretStr("private-refresh"), 3600)

    monkeypatch.setattr(provider, "exchange_code", exchange)
    with pytest.raises(GmailAuthorizationRejected):
        service.complete(foreign, state, SecretStr("private-code"))
    connection = service.complete(owner, state, SecretStr("private-code"))
    assert len(calls) == 1 and "private" not in str(connection.model_dump())
    assert service.list_connections(foreign) == [] and len(service.list_connections(owner)) == 1
    with service.database.session() as session:
        row = session.get(GmailConnection, connection.id)
        attempt = session.scalar(select(GmailAuthorization))
        assert (
            row
            and row.encrypted_refresh_token
            and "private-refresh" not in row.encrypted_refresh_token
        )
        assert attempt and attempt.consumed_at and attempt.encrypted_verifier is None
    with pytest.raises(GmailAuthorizationRejected):
        service.complete(owner, state, SecretStr("private-code"))
    with pytest.raises(GmailConnectionNotFound):
        service.revoke(foreign, connection.id)
    service.revoke(owner, connection.id)
    service.revoke(owner, connection.id)
    with service.database.session() as session:
        row = session.get(GmailConnection, connection.id)
        assert row and row.revoked_at and row.encrypted_refresh_token is None


def test_expired_and_concurrent_authorization_can_exchange_at_most_once(setup, monkeypatch):
    service, (owner, _) = setup
    state = state_for(service, owner)
    with service.database.unit_of_work() as session:
        attempt = session.scalar(select(GmailAuthorization))
        assert attempt
        attempt.created_at -= timedelta(minutes=20)
        attempt.expires_at -= timedelta(minutes=20)
    with pytest.raises(GmailAuthorizationRejected):
        service.complete(owner, state, SecretStr("private-code"))
    state = state_for(service, owner)
    calls = []

    def exchange(**kwargs):
        calls.append(1)
        return provider.OAuthToken(SecretStr("access"), SecretStr("refresh"), 3600)

    monkeypatch.setattr(provider, "exchange_code", exchange)

    def invoke():
        try:
            service.complete(owner, state, SecretStr("private-code"))
            return "accepted"
        except GmailAuthorizationRejected:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))
    assert sorted(results) == ["accepted", "rejected"] and len(calls) == 1


def test_failed_token_exchange_consumes_state(setup, monkeypatch):
    service, (owner, _) = setup
    state = state_for(service, owner)
    calls = []

    def fail(**kwargs):
        calls.append(1)
        raise provider.GmailProviderError("AUTHORIZATION_FAILED")

    monkeypatch.setattr(provider, "exchange_code", fail)
    with pytest.raises(provider.GmailProviderError):
        service.complete(owner, state, SecretStr("private-code"))
    with pytest.raises(GmailAuthorizationRejected):
        service.complete(owner, state, SecretStr("private-code"))
    assert len(calls) == 1 and service.list_connections(owner) == []


@pytest.mark.anyio
async def test_oauth_api_requires_ownership_and_never_exposes_credentials(setup, monkeypatch):
    service, (owner, foreign) = setup
    signing = SecretStr("fixture-only-signing-key-at-least-thirty-two-bytes")
    settings = service.settings.model_copy(update={"jwt_secret_key": signing})
    application = create_app(settings)

    async def database():
        return service.database

    application.dependency_overrides[get_database_resource] = database
    tokens = AccessTokens(
        secret=signing, issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    owner_headers = {"Authorization": f"Bearer {tokens.issue(owner)}"}
    foreign_headers = {"Authorization": f"Bearer {tokens.issue(foreign)}"}
    monkeypatch.setattr(
        provider,
        "exchange_code",
        lambda **kwargs: provider.OAuthToken(
            SecretStr("private-access"), SecretStr("private-refresh"), 3600
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="https://test"
    ) as client:
        assert (await client.post("/api/v1/gmail/authorize")).status_code == 401
        start = await client.post("/api/v1/gmail/authorize", headers=owner_headers)
        assert start.status_code == 200 and start.headers["cache-control"] == "no-store"
        state = parse_qs(urlsplit(start.json()["url"]).query)["state"][0]
        body = {"state": state, "code": "private-code"}
        assert (
            await client.post("/api/v1/gmail/complete", json=body, headers=foreign_headers)
        ).status_code == 409
        done = await client.post("/api/v1/gmail/complete", json=body, headers=owner_headers)
        assert done.status_code == 201 and done.headers["cache-control"] == "no-store"
        assert "private" not in done.text and "secret" not in done.text
        assert (
            await client.post("/api/v1/gmail/complete", json=body, headers=owner_headers)
        ).status_code == 409
        assert (await client.get("/api/v1/gmail/connections", headers=foreign_headers)).json() == []
        path = f"/api/v1/gmail/connections/{done.json()['id']}"
        monkeypatch.setattr(
            provider,
            "refresh_access_token",
            lambda **kwargs: provider.OAuthToken(SecretStr("private-access"), None, 3600),
        )
        monkeypatch.setattr(provider, "list_message_ids", lambda token: ["fixture123"])
        assert (await client.get(path + "/messages", headers=foreign_headers)).status_code == 404
        listing = await client.get(path + "/messages", headers=owner_headers)
        assert listing.status_code == 200 and listing.json() == ["fixture123"]
        assert listing.headers["cache-control"] == "no-store" and "private" not in listing.text
        assert (await client.delete(path, headers=foreign_headers)).status_code == 404
        assert (await client.delete(path, headers=owner_headers)).status_code == 204
        assert (await client.get(path + "/messages", headers=owner_headers)).status_code == 404


def test_manual_gmail_read_runs_classification_with_owned_connection(setup, monkeypatch):
    service, (owner, foreign) = setup
    state = state_for(service, owner)
    monkeypatch.setattr(
        provider,
        "exchange_code",
        lambda **kwargs: provider.OAuthToken(SecretStr("access"), SecretStr("refresh"), 3600),
    )
    connection = service.complete(owner, state, SecretStr("code"))
    calls = []
    pool = service.database.engine.pool
    assert isinstance(pool, QueuePool)
    baseline = pool.checkedout()

    def refresh(**kwargs):
        assert pool.checkedout() == baseline
        calls.append("refresh")
        return provider.OAuthToken(SecretStr("access"), None, 3600)

    def read(token, message_id):
        assert pool.checkedout() == baseline and message_id == "fixture123"
        calls.append("read")
        return {"payload": {"mimeType": "text/plain", "body": {"data": "aGVsbG8"}}}

    monkeypatch.setattr(provider, "refresh_access_token", refresh)
    monkeypatch.setattr(provider, "read_message", read)
    monkeypatch.setattr(
        "app.modules.executions.runner.complete",
        lambda settings, prompt, **kwargs: {"model": "fixture", "content": '{"label":"billing"}'},
    )
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "read",
                "type": "gmail_read",
                "config": {"connection_id": str(connection.id), "message_id_field": "message_id"},
            },
            {
                "id": "classify",
                "type": "classify",
                "config": {"input_field": "text", "labels": ["billing", "other"]},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "read"},
            {"id": "b", "source": "read", "target": "classify"},
            {"id": "c", "source": "classify", "target": "end"},
        ],
    }
    with service.database.unit_of_work() as session:
        repository = WorkflowRepository(session)
        workflow = repository.add(owner_id=owner, name="Fixture Gmail workflow")
        version = repository.append_version(
            workflow_id=workflow.id, owner_id=owner, expected_version=0, definition=graph
        )
        workflow_id, version_id = workflow.id, version.id
    result = ExecutionService(service.database, service.settings).create_and_execute(
        workflow_id=workflow_id,
        owner_id=owner,
        data=RunCreateRequest(workflow_version_id=version_id, input={"message_id": "fixture123"}),
    )
    assert result.status == "succeeded" and result.output == {
        "model": "fixture",
        "label": "billing",
    }
    assert calls == ["refresh", "read"] and result.execution_mode == "synchronous"
    with pytest.raises(GmailConnectionNotFound):
        service.read_message(foreign, connection.id, "fixture123")
    service.revoke(owner, connection.id)
    with pytest.raises(GmailConnectionNotFound):
        service.read_message(owner, connection.id, "fixture123")
    assert calls == ["refresh", "read"]


def test_revocation_during_refresh_blocks_mailbox_read(setup, monkeypatch):
    service, (owner, _) = setup
    state = state_for(service, owner)
    monkeypatch.setattr(
        provider,
        "exchange_code",
        lambda **kwargs: provider.OAuthToken(SecretStr("access"), SecretStr("refresh"), 3600),
    )
    connection = service.complete(owner, state, SecretStr("code"))

    def refresh(**kwargs):
        service.revoke(owner, connection.id)
        return provider.OAuthToken(SecretStr("access"), None, 3600)

    def forbidden(*args, **kwargs):
        pytest.fail("A revoked connection must not fetch a message")

    monkeypatch.setattr(provider, "refresh_access_token", refresh)
    monkeypatch.setattr(provider, "read_message", forbidden)
    with pytest.raises(GmailConnectionNotFound):
        service.read_message(owner, connection.id, "fixture123")


@pytest.mark.anyio
async def test_ai_edit_refuses_gmail_workflow_before_provider_call(setup, monkeypatch):
    service, (owner, _) = setup
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "read",
                "type": "gmail_read",
                "config": {"connection_id": str(uuid4()), "message_id_field": "message_id"},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "read"},
            {"id": "b", "source": "read", "target": "end"},
        ],
    }
    with service.database.unit_of_work() as session:
        repository = WorkflowRepository(session)
        workflow = repository.add(owner_id=owner, name="Fixture")
        version = repository.append_version(
            workflow_id=workflow.id, owner_id=owner, expected_version=0, definition=graph
        )
        workflow_id, version_id = workflow.id, version.id
    signing = SecretStr("fixture-only-signing-key-at-least-thirty-two-bytes")
    app = create_app(service.settings.model_copy(update={"jwt_secret_key": signing}))

    async def database():
        return service.database

    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported Gmail proposal must not call the provider")

    app.dependency_overrides[get_database_resource] = database
    monkeypatch.setattr("app.api.v1.workflows.generate", forbidden)
    tokens = AccessTokens(
        secret=signing, issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        result = await client.post(
            f"/api/v1/workflows/{workflow_id}/edit-proposal",
            headers={"Authorization": f"Bearer {tokens.issue(owner)}"},
            json={"base_version_id": str(version_id), "prompt": "Edit this workflow"},
        )
    assert (
        result.status_code == 422 and result.json()["error"]["code"] == "GMAIL_PROPOSAL_UNAVAILABLE"
    )
