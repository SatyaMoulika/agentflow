"""Logout and rotation serialize on one family even with different token generations."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident

import pytest
from pydantic import SecretStr
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection

from app.core.tokens import AccessTokens
from app.infrastructure.database.models import RefreshSession, RefreshToken
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import RefreshRejectedError
from app.modules.auth.refresh_repository import RefreshRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import AuthResult, AuthService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("generation", ["current", "consumed-ancestor"])
def test_logout_racing_refresh_leaves_no_usable_descendant(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    generation: str,
) -> None:
    tokens = AccessTokens(
        secret=SecretStr("test-only-logout-race-key-at-least-32-bytes"),
        issuer="agentflow",
        audience="agentflow-api",
        ttl_seconds=900,
    )
    service = AuthService(repository_database)
    data = {
        "email": "logout-race@example.com",
        "display_name": "Race",
        "password": "private logout race passphrase",
    }
    service.register(RegisterRequest.model_validate(data))
    initial = service.login(
        LoginRequest.model_validate({"email": data["email"], "password": data["password"]}),
        tokens,
        604800,
    )
    current = (
        service.refresh(initial.credentials, tokens)
        if generation == "consumed-ancestor"
        else initial
    )
    barrier = Barrier(2, timeout=5)
    seen: set[int] = set()
    pids: set[int] = set()
    original = RefreshRepository.find_token

    def deadlines(connection: Connection) -> None:
        connection.exec_driver_sql("SET LOCAL lock_timeout = '5s'")
        connection.exec_driver_sql("SET LOCAL statement_timeout = '8s'")

    event.listen(repository_database.engine, "begin", deadlines)

    def synchronize(self: RefreshRepository, digest: str) -> RefreshToken | None:
        result = original(self, digest)
        ident = get_ident()
        if ident not in seen:
            seen.add(ident)
            pids.add(int(self.session.scalar(text("SELECT pg_backend_pid()"))))
            barrier.wait()
        return result

    def rotate() -> AuthResult | None:
        try:
            return AuthService(repository_database).refresh(current.credentials, tokens)
        except RefreshRejectedError:
            return None

    with monkeypatch.context() as patch:
        patch.setattr(RefreshRepository, "find_token", synchronize)
        with ThreadPoolExecutor(max_workers=2) as executor:
            logout = executor.submit(AuthService(repository_database).logout, initial.credentials)
            refresh = executor.submit(rotate)
            assert logout.result(timeout=12) is None
            replacement = refresh.result(timeout=12)
    assert len(pids) == 2
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at is not None
        assert sum(t.consumed_at is None for t in session.scalars(select(RefreshToken))) == 1
    if replacement is not None:
        with pytest.raises(RefreshRejectedError):
            service.refresh(replacement.credentials, tokens)
    with pytest.raises(RefreshRejectedError):
        service.refresh(current.credentials, tokens)
