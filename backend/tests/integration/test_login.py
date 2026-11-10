"""Login and authenticated identity through real hashing, signatures and PostgreSQL."""

from threading import get_ident
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import QueuePool

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.security import verify_password
from app.infrastructure.database.models import User
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-signing-key-not-a-deployment-secret-12345"
PASSWORD = "  Exact private login passphrase  "
PAYLOAD = {"email": "  Moulika@Example.COM  ", "display_name": "Moulika", "password": PASSWORD}


def auth_app(database: Database) -> FastAPI:
    application = create_app(
        Settings(jwt_secret_key=SecretStr(KEY), auth_allowed_origins=("https://test",))
    )

    async def resource() -> Database:
        return database

    application.dependency_overrides[get_database_resource] = resource
    return application


def assert_unauthenticated(response) -> None:
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "error": {
            "code": "UNAUTHENTICATED",
            "message": "Authentication is required.",
            "details": None,
        },
        "request_id": response.headers["x-request-id"],
    }


async def test_register_login_me_and_two_users_keep_distinct_identities(
    repository_database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    application = auth_app(repository_database)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Origin": "https://test", "X-AgentFlow-Client": "web"},
    ) as client:
        registered = await client.post("/api/v1/auth/register", json=PAYLOAD)
        assert registered.status_code == 201
        await client.post("/api/v1/auth/register", json=PAYLOAD | {"email": "second@example.com"})
        first = await client.post(
            "/api/v1/auth/login", json={"email": "moulika@example.com", "password": PASSWORD}
        )
        second = await client.post(
            "/api/v1/auth/login", json={"email": "second@example.com", "password": PASSWORD}
        )
        assert first.status_code == second.status_code == 200
        body = first.json()
        assert set(body) == {"access_token", "csrf_token", "token_type", "expires_in", "user"}
        assert body["token_type"] == "bearer" and body["expires_in"] == 900
        assert body["user"] == registered.json()
        assert first.headers["cache-control"] == "no-store"
        assert first.headers["pragma"] == "no-cache"
        assert len(first.headers.get_list("set-cookie")) == 2
        token = body["access_token"]
        me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        other = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"}
        )
        assert me.status_code == other.status_code == 200
        assert me.json() == registered.json()
        assert me.headers["cache-control"] == "no-store"
        assert other.json()["id"] != me.json()["id"]
        assert PASSWORD not in first.text + me.text + caplog.text
        assert token not in me.text + caplog.text
        assert "$argon2" not in first.text + me.text + caplog.text
        records = [r for r in caplog.records if r.name == "agentflow.http"]
        assert any(r.__dict__["request_id"] == me.headers["x-request-id"] for r in records)


async def test_wrong_unknown_and_inactive_credentials_have_identical_safe_responses(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    observed: list[str | None] = []
    pool = repository_database.engine.pool
    assert isinstance(pool, QueuePool)
    baseline_connections = pool.checkedout()
    main_thread = get_ident()

    def observe_verify(password: SecretStr, encoded_hash: str | None) -> bool:
        assert get_ident() != main_thread
        assert pool.checkedout() == baseline_connections
        observed.append(encoded_hash)
        return verify_password(password, encoded_hash)

    application = auth_app(repository_database)
    monkeypatch.setattr("app.modules.auth.service.verify_password", observe_verify)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Origin": "https://test", "X-AgentFlow-Client": "web"},
    ) as client:
        registered = await client.post("/api/v1/auth/register", json=PAYLOAD)
        for email, password in [
            ("moulika@example.com", PASSWORD.strip()),
            ("unknown@example.com", PASSWORD),
        ]:
            assert_unauthenticated(
                await client.post("/api/v1/auth/login", json={"email": email, "password": password})
            )
        with repository_database.unit_of_work() as session:
            session.execute(
                update(User).where(User.id == UUID(registered.json()["id"])).values(is_active=False)
            )
        assert_unauthenticated(
            await client.post(
                "/api/v1/auth/login", json={"email": "moulika@example.com", "password": PASSWORD}
            )
        )
    assert len(observed) == 3 and observed[0] is not None and observed[1] is None
    assert PASSWORD not in caplog.text


@pytest.mark.parametrize("change", ["disable", "delete"])
async def test_me_checks_current_account_state_after_token_was_issued(
    repository_database: Database, change: str
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers={"Origin": "https://test", "X-AgentFlow-Client": "web"},
    ) as client:
        registered = await client.post("/api/v1/auth/register", json=PAYLOAD)
        logged_in = await client.post(
            "/api/v1/auth/login", json={"email": "moulika@example.com", "password": PASSWORD}
        )
        token = logged_in.json()["access_token"]
        with repository_database.unit_of_work() as session:
            user_id = UUID(registered.json()["id"])
            statement = (
                delete(User).where(User.id == user_id)
                if change == "delete"
                else update(User).where(User.id == user_id).values(is_active=False)
            )
            session.execute(statement)
        assert_unauthenticated(
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        )


@pytest.mark.parametrize("invalid", ["expired", "tampered", "refresh", "missing-user"])
async def test_me_rejects_invalid_credentials_through_the_http_boundary(
    repository_database: Database, invalid: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers={"Origin": "https://test", "X-AgentFlow-Client": "web"},
    ) as client:
        await client.post("/api/v1/auth/register", json=PAYLOAD)
        logged_in = await client.post(
            "/api/v1/auth/login", json={"email": "moulika@example.com", "password": PASSWORD}
        )
        original = logged_in.json()["access_token"]
        claims = jwt.decode(original, KEY, algorithms=["HS256"], audience="agentflow-api")
        if invalid == "expired":
            claims.update(iat=1, nbf=1, exp=901)
        elif invalid == "refresh":
            claims["token_type"] = "refresh"
        elif invalid == "missing-user":
            claims["sub"] = str(uuid4())
        token = jwt.encode(
            claims,
            KEY if invalid != "tampered" else KEY + "wrong",
            algorithm="HS256",
            headers={"typ": "at+jwt"},
        )
        response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert_unauthenticated(response)
        assert token not in response.text + caplog.text


@pytest.mark.parametrize("change", ["disable", "password"])
async def test_login_rechecks_password_and_active_state_after_verification(
    repository_database: Database, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    def disable_during_verify(password: SecretStr, encoded_hash: str | None) -> bool:
        verified = verify_password(password, encoded_hash)
        with repository_database.unit_of_work() as session:
            values = {"is_active": False} if change == "disable" else {"password_hash": "changed"}
            session.execute(update(User).values(**values))
        return verified

    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers={"Origin": "https://test", "X-AgentFlow-Client": "web"},
    ) as client:
        await client.post("/api/v1/auth/register", json=PAYLOAD)
        monkeypatch.setattr("app.modules.auth.service.verify_password", disable_during_verify)
        assert_unauthenticated(
            await client.post(
                "/api/v1/auth/login", json={"email": "moulika@example.com", "password": PASSWORD}
            )
        )


@pytest.mark.parametrize("endpoint", ["login", "me"])
async def test_auth_storage_failure_is_safe_and_requests_recover(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers={"Origin": "https://test", "X-AgentFlow-Client": "web"},
    ) as client:
        await client.post("/api/v1/auth/register", json=PAYLOAD)
        logged_in = await client.post(
            "/api/v1/auth/login", json={"email": "moulika@example.com", "password": PASSWORD}
        )
        token = logged_in.json()["access_token"]
        method = "get_by_email" if endpoint == "login" else "get_by_id"
        original = getattr(UserRepository, method)

        def unavailable(*args, **kwargs):
            raise OperationalError("private-driver-detail", {}, RuntimeError(PASSWORD))

        monkeypatch.setattr(UserRepository, method, unavailable)

        async def request():
            if endpoint == "login":
                return await client.post(
                    "/api/v1/auth/login",
                    json={"email": "moulika@example.com", "password": PASSWORD},
                )
            return await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

        response = await request()
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert response.json()["request_id"] == response.headers["x-request-id"]
        assert "private-driver-detail" not in response.text + caplog.text
        assert PASSWORD not in response.text + caplog.text
        assert token not in response.text + caplog.text
        monkeypatch.setattr(UserRepository, method, original)
        assert (await request()).status_code == 200
