"""Durable, idempotent family logout with CSRF, rollback and cookie guarantees."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.infrastructure.database.models import RefreshSession, RefreshToken, User
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.refresh_repository import RefreshRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-logout-signing-key-at-least-32-bytes"
HEADERS = {"Origin": "https://test", "X-AgentFlow-Client": "web"}
PAYLOAD = {
    "email": "logout@example.com",
    "password": "private logout passphrase",
    "display_name": "Logout",
}
REFRESH, CSRF = "__Host-agentflow_refresh", "__Host-agentflow_csrf"


def proof(raw: str, csrf: str) -> dict[str, str]:
    return HEADERS | {"Cookie": f"{REFRESH}={raw}; {CSRF}={csrf}", "X-AgentFlow-CSRF": csrf}


def auth_app(database: Database, *, key: str | None = KEY) -> FastAPI:
    application = create_app(
        Settings(
            jwt_secret_key=SecretStr(key) if key else None, auth_allowed_origins=("https://test",)
        )
    )

    async def resource() -> Database:
        return database

    application.dependency_overrides[get_database_resource] = resource
    return application


@pytest.fixture
async def signed_in(
    repository_database: Database,
) -> AsyncIterator[tuple[AsyncClient, str, str, str]]:
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database)),
        base_url="https://test",
        headers=HEADERS,
    ) as client:
        assert (await client.post("/api/v1/auth/register", json=PAYLOAD)).status_code == 201
        logged_in = await client.post(
            "/api/v1/auth/login", json={"email": PAYLOAD["email"], "password": PAYLOAD["password"]}
        )
        assert logged_in.status_code == 200
        yield (
            client,
            client.cookies[REFRESH],
            client.cookies[CSRF],
            logged_in.json()["access_token"],
        )


async def test_logout_commits_revocation_clears_cookies_and_is_idempotent(
    signed_in: tuple[AsyncClient, str, str, str],
    repository_database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, raw, csrf, access = signed_in
    first = await client.post("/api/v1/auth/logout", headers=proof(raw, csrf))
    assert first.status_code == 204 and first.content == b""
    assert first.headers["cache-control"] == "no-store"
    assert first.headers["pragma"] == "no-cache"
    assert len(first.headers.get_list("set-cookie")) == 2
    assert all("Max-Age=0" in header for header in first.headers.get_list("set-cookie"))
    assert client.cookies.get(REFRESH) is None and client.cookies.get(CSRF) is None
    with repository_database.session() as session:
        revoked_at = session.scalars(select(RefreshSession)).one().revoked_at
        assert revoked_at is not None
    assert (await client.post("/api/v1/auth/logout", headers=proof(raw, csrf))).status_code == 204
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at == revoked_at
    assert (await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))).status_code == 401
    # Logout revokes refresh state, not the existing access JWT denylist-free design.
    assert (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    ).status_code == 200
    assert all(value not in caplog.text for value in [raw, csrf, access, PAYLOAD["password"]])
    assert any(
        r.__dict__.get("request_id") == first.headers["x-request-id"]
        for r in caplog.records
        if r.name == "agentflow.http"
    )


async def test_logout_with_consumed_pair_revokes_descendant_but_not_another_family(
    signed_in: tuple[AsyncClient, str, str, str],
    repository_database: Database,
) -> None:
    client, raw, csrf, _ = signed_in
    assert (await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))).status_code == 200
    child, child_csrf = client.cookies[REFRESH], client.cookies[CSRF]
    other = await client.post(
        "/api/v1/auth/login", json={"email": PAYLOAD["email"], "password": PAYLOAD["password"]}
    )
    assert other.status_code == 200
    other_raw, other_csrf = client.cookies[REFRESH], client.cookies[CSRF]
    response = await client.post(
        "/api/v1/auth/logout",
        headers=proof(raw, csrf),
        json={"all_sessions": True, "user_id": "ignored"},
    )
    assert response.status_code == 204
    assert (
        await client.post("/api/v1/auth/refresh", headers=proof(child, child_csrf))
    ).status_code == 401
    assert (
        await client.post("/api/v1/auth/refresh", headers=proof(other_raw, other_csrf))
    ).status_code == 200
    with repository_database.session() as session:
        assert sum(f.revoked_at is not None for f in session.scalars(select(RefreshSession))) == 1


async def test_forged_matching_csrf_pair_does_not_revoke_or_clear_cookie(
    signed_in: tuple[AsyncClient, str, str, str],
    repository_database: Database,
) -> None:
    client, raw, csrf, _ = signed_in
    rejected = await client.post("/api/v1/auth/logout", headers=proof(raw, "a" * 43))
    assert rejected.status_code == 403 and "set-cookie" not in rejected.headers
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at is None
    assert (await client.post("/api/v1/auth/refresh", headers=proof(raw, csrf))).status_code == 200


@pytest.mark.parametrize("state", ["expired", "revoked", "inactive", "deleted", "unknown"])
async def test_logout_unusable_or_unknown_credentials_remains_safe_204(
    signed_in: tuple[AsyncClient, str, str, str],
    repository_database: Database,
    state: str,
) -> None:
    client, raw, csrf, _ = signed_in
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
        elif state == "inactive":
            session.execute(update(User).values(is_active=False))
        elif state == "deleted":
            session.execute(delete(User))
    response = await client.post(
        "/api/v1/auth/logout", headers=proof("u" * 43 if state == "unknown" else raw, csrf)
    )
    assert response.status_code == 204 and response.content == b""
    with repository_database.session() as session:
        families = session.scalars(select(RefreshSession)).all()
        if state == "deleted":
            assert families == []
        else:
            assert (families[0].revoked_at is not None) == (state != "unknown")


@pytest.mark.parametrize("failure", ["storage", "unexpected"])
async def test_logout_failure_rolls_back_revocation_and_preserves_cookie_for_retry(
    signed_in: tuple[AsyncClient, str, str, str],
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, raw, csrf, _ = signed_in
    original = RefreshRepository.revoke_session

    def fail_after_flush(self, family, now):
        original(self, family, now)
        if failure == "storage":
            raise OperationalError("private-logout-driver", {}, RuntimeError(raw))
        raise RuntimeError("private-logout-internal")

    with monkeypatch.context() as patch:
        patch.setattr(RefreshRepository, "revoke_session", fail_after_flush)
        response = await client.post("/api/v1/auth/logout", headers=proof(raw, csrf))
    assert response.status_code == (503 if failure == "storage" else 500)
    assert "set-cookie" not in response.headers
    assert all(value not in response.text + caplog.text for value in [raw, csrf, "private-logout"])
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at is None
        assert session.scalars(select(RefreshToken)).one().consumed_at is None
    assert (await client.post("/api/v1/auth/logout", headers=proof(raw, csrf))).status_code == 204


async def test_logout_does_not_depend_on_signing_key_or_valid_access_jwt(
    signed_in: tuple[AsyncClient, str, str, str],
    repository_database: Database,
) -> None:
    _, raw, csrf, _ = signed_in
    async with AsyncClient(
        transport=ASGITransport(app=auth_app(repository_database, key=None)),
        base_url="https://test",
    ) as client:
        response = await client.post(
            "/api/v1/auth/logout",
            headers=proof(raw, csrf) | {"Authorization": "Bearer private-invalid-or-expired"},
        )
    assert response.status_code == 204
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at is not None
