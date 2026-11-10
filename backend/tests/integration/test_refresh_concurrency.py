"""Independent connections serialize cached token state at the family boundary."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, get_ident

import pytest
from pydantic import SecretStr
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection

from app.core.refresh_tokens import RefreshCredentials
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import RefreshSession, RefreshToken
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import RefreshRejectedError
from app.modules.auth.refresh_repository import RefreshRepository
from app.modules.auth.schemas import LoginRequest, RegisterRequest
from app.modules.auth.service import AuthResult, AuthService

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("race", ["same-token", "ancestor-replay"])
def test_concurrent_rotation_or_replay_revokes_family_without_two_usable_descendants(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    race: str,
) -> None:
    tokens = AccessTokens(
        secret=SecretStr("test-refresh-concurrency-key-at-least-32-bytes"),
        issuer="agentflow",
        audience="agentflow-api",
        ttl_seconds=900,
    )
    service = AuthService(repository_database)
    data = {
        "email": "race@example.com",
        "display_name": "Race",
        "password": "private concurrency passphrase",
    }
    service.register(RegisterRequest.model_validate(data))
    initial = service.login(
        LoginRequest.model_validate({"email": data["email"], "password": data["password"]}),
        tokens,
        604800,
    )
    current = service.refresh(initial.credentials, tokens) if race == "ancestor-replay" else initial
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
            barrier.wait()  # Both cached the token before either locks its family.
        return result

    def rotate(credentials: RefreshCredentials) -> AuthResult | None:
        try:
            return AuthService(repository_database).refresh(credentials, tokens)
        except RefreshRejectedError:
            return None

    with monkeypatch.context() as patch:
        patch.setattr(RefreshRepository, "find_token", synchronize)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(rotate, credentials)
                for credentials in (initial.credentials, current.credentials)
            ]
            results = [future.result(timeout=12) for future in futures]
    assert len(pids) == 2
    successes = [result for result in results if result is not None]
    assert len(successes) == 1 if race == "same-token" else len(successes) <= 1
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).one().revoked_at is not None
        rows = session.scalars(select(RefreshToken)).all()
        assert sum(row.consumed_at is None for row in rows) == 1
        assert len(rows) == (2 if race == "same-token" else 2 + len(successes))
    for result in successes:
        with pytest.raises(RefreshRejectedError):
            service.refresh(result.credentials, tokens)
