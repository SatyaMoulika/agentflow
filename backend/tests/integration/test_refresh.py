"""Persisted refresh rotation, cookie CSRF binding, replay and failure atomicity."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.refresh_tokens import token_digest
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import RefreshSession, RefreshToken, User
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.refresh_repository import RefreshRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-refresh-signing-key-longer-than-32-bytes"
HEADERS = {"Origin": "https://test", "X-AgentFlow-Client": "web"}
PAYLOAD = {
    "email": "refresh@example.com",
    "display_name": "Refresh",
    "password": "private refresh passphrase",
}
REFRESH = "__Host-agentflow_refresh"
CSRF = "__Host-agentflow_csrf"


def auth_app(database: Database, *, secure: bool = True) -> FastAPI:
    application = create_app(
        Settings(
            jwt_secret_key=SecretStr(KEY),
            auth_allowed_origins=("https://test",),
            refresh_cookie_secure=secure,
        )
    )

    async def resource() -> Database:
        return database

    application.dependency_overrides[get_database_resource] = resource
    return application


async def login(client: AsyncClient) -> tuple[str, str, str]:
    assert (await client.post("/api/v1/auth/register", json=PAYLOAD)).status_code == 201
    response = await client.post(
        "/api/v1/auth/login", json={"email": PAYLOAD["email"], "password": PAYLOAD["password"]}
    )
    assert response.status_code == 200
    raw = client.cookies[REFRESH]
    csrf = client.cookies[CSRF]
    assert response.json()["csrf_token"] == csrf
    assert raw not in response.text
    return raw, csrf, response.json()["access_token"]


def proof(raw: str, csrf: str) -> dict[str, str]:
    return HEADERS | {"Cookie": f"{REFRESH}={raw}; {CSRF}={csrf}", "X-AgentFlow-CSRF": csrf}


async def test_login_stores_only_digests_and_refresh_rotates_pair_without_extending_expiry(
    repository_database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, old_access = await login(client)
        with repository_database.session() as session:
            family = session.scalars(select(RefreshSession)).one()
            family_id, deadline = family.id, family.expires_at
            row = session.scalars(select(RefreshToken)).one()
            assert row.token_hash == token_digest(SecretStr(raw))
            assert row.csrf_hash == token_digest(SecretStr(csrf))
            assert row.consumed_at is None
        response = await client.post("/api/v1/auth/refresh", headers={"X-AgentFlow-CSRF": csrf})
        assert response.status_code == 200
        new_raw, new_csrf = client.cookies[REFRESH], client.cookies[CSRF]
        assert new_raw != raw and new_csrf != csrf
        assert response.json()["access_token"] != old_access
        assert response.json()["csrf_token"] == new_csrf
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["pragma"] == "no-cache"
        cookie_headers = response.headers.get_list("set-cookie")
        assert len(cookie_headers) == 2
        assert "HttpOnly" in cookie_headers[0] and "HttpOnly" not in cookie_headers[1]
        for header in cookie_headers:
            assert "Secure" in header and "SameSite=strict" in header and "Path=/" in header
            assert "Domain=" not in header
        assert new_raw not in response.text
        with repository_database.session() as session:
            stored = session.get(RefreshSession, family_id)
            assert (
                stored is not None and stored.expires_at == deadline and stored.revoked_at is None
            )
            rows = session.scalars(select(RefreshToken)).all()
            assert len(rows) == 2 and sum(row.consumed_at is None for row in rows) == 1
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {response.json()['access_token']}"},
        )
        assert me.status_code == 200
        assert all(
            value not in caplog.text
            for value in [raw, csrf, new_raw, new_csrf, old_access, PAYLOAD["password"], "$argon2"]
        )


async def test_replay_commits_family_revocation_and_does_not_revoke_other_login(
    repository_database: Database,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, _ = await login(client)
        rotated = await client.post("/api/v1/auth/refresh", headers={"X-AgentFlow-CSRF": csrf})
        assert rotated.status_code == 200
        child, child_csrf = client.cookies[REFRESH], client.cookies[CSRF]
        other = await client.post(
            "/api/v1/auth/login", json={"email": PAYLOAD["email"], "password": PAYLOAD["password"]}
        )
        assert other.status_code == 200
        other_raw, other_csrf = client.cookies[REFRESH], client.cookies[CSRF]
        replay = await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        assert replay.status_code == 401
        assert all("Max-Age=0" in h for h in replay.headers.get_list("set-cookie"))
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof(child, child_csrf))
        ).status_code == 401
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof(other_raw, other_csrf))
        ).status_code == 200
    with repository_database.session() as session:
        families = session.scalars(select(RefreshSession)).all()
        assert len(families) == 2 and sum(f.revoked_at is not None for f in families) == 1


async def test_csrf_bound_to_token_and_rejected_request_does_not_consume_or_revoke(
    repository_database: Database,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, _ = await login(client)
        # A forged cookie/header pair matches itself but not the server-side binding.
        rejected = await client.post("/api/v1/auth/refresh", headers=proof(raw, "a" * 43))
        assert rejected.status_code == 403 and "set-cookie" not in rejected.headers
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        ).status_code == 200
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at is None
        assert session.scalar(select(func.count()).select_from(RefreshToken)) == 2


@pytest.mark.parametrize("state", ["expired", "revoked", "inactive"])
async def test_unusable_family_is_rejected_and_does_not_rotate(
    repository_database: Database,
    state: str,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, _ = await login(client)
        now = datetime.now(UTC)
        with repository_database.unit_of_work() as session:
            if state == "expired":
                session.execute(
                    update(RefreshSession).values(
                        created_at=now - timedelta(days=2), expires_at=now - timedelta(days=1)
                    )
                )
            elif state == "revoked":
                session.execute(update(RefreshSession).values(revoked_at=now))
            else:
                session.execute(update(User).values(is_active=False))
        response = await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        assert response.status_code == 401
        with repository_database.session() as session:
            assert session.scalar(select(func.count()).select_from(RefreshToken)) == 1
            assert session.scalars(select(RefreshToken)).one().consumed_at is None
            if state == "inactive":
                assert session.scalars(select(RefreshSession)).one().revoked_at is not None


async def test_unknown_well_formed_token_does_not_revoke_an_existing_family(
    repository_database: Database,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, _ = await login(client)
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof("a" * 43, csrf))
        ).status_code == 401
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        ).status_code == 200


@pytest.mark.parametrize("failure", ["insert", "sign"])
async def test_replacement_failure_rolls_back_consumption_and_retry_uses_original_cookie(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, _ = await login(client)

        def fail(*args, **kwargs):
            raise RuntimeError("private-refresh-failure")

        with monkeypatch.context() as patch:
            if failure == "insert":
                patch.setattr(RefreshRepository, "add_token", fail)
            else:
                patch.setattr(AccessTokens, "issue", fail)
            response = await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        assert response.status_code == 500
        assert "private-refresh-failure" not in response.text
        assert "set-cookie" not in response.headers
        with repository_database.session() as session:
            assert session.scalars(select(RefreshToken)).one().consumed_at is None
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        ).status_code == 200


async def test_storage_failure_returns_safe_503_without_discarding_cookie(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        raw, csrf, _ = await login(client)

        def unavailable(*args, **kwargs):
            raise OperationalError("private-refresh-driver", {}, RuntimeError(raw))

        with monkeypatch.context() as patch:
            patch.setattr(RefreshRepository, "find_token", unavailable)
            response = await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        assert response.status_code == 503 and "set-cookie" not in response.headers
        assert all(
            value not in caplog.text + response.text
            for value in [raw, csrf, "private-refresh-driver"]
        )
        assert (
            await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))
        ).status_code == 200


async def test_login_session_failure_rolls_back_and_never_emits_cookies(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        await client.post("/api/v1/auth/register", json=PAYLOAD)

        def fail(*args, **kwargs):
            raise RuntimeError("private-session-insert")

        with monkeypatch.context() as patch:
            patch.setattr(RefreshRepository, "add_token", fail)
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": PAYLOAD["email"], "password": PAYLOAD["password"]},
            )
        assert response.status_code == 500 and "set-cookie" not in response.headers
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(RefreshSession)) == 0
        assert session.scalar(select(func.count()).select_from(RefreshToken)) == 0


async def test_explicit_development_http_cookies_can_rotate(repository_database: Database) -> None:
    application = auth_app(repository_database, secure=False)
    # Explicit dev HTTP choice, never permitted with production configuration.
    application.state.settings = Settings(
        jwt_secret_key=SecretStr(KEY),
        refresh_cookie_secure=False,
        auth_allowed_origins=("http://test",),
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://test",
        headers={"Origin": "http://test", "X-AgentFlow-Client": "web"},
    ) as client:
        await client.post("/api/v1/auth/register", json=PAYLOAD)
        response = await client.post(
            "/api/v1/auth/login", json={"email": PAYLOAD["email"], "password": PAYLOAD["password"]}
        )
        assert response.status_code == 200
        assert client.cookies.get("agentflow_refresh") and client.cookies.get("agentflow_csrf")
        assert all(
            "Secure" not in h and "__Host-" not in h
            for h in response.headers.get_list("set-cookie")
        )
        rotated = await client.post(
            "/api/v1/auth/refresh", headers={"X-AgentFlow-CSRF": response.json()["csrf_token"]}
        )
        assert rotated.status_code == 200
