"""A failed startup must release its pool and avoid exposing driver diagnostics."""

from collections.abc import Callable

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.main import create_app


@pytest.mark.anyio
async def test_startup_failure_disposes_pool_and_clears_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application = create_app(
        Settings(
            database_url=SecretStr("postgresql+psycopg://user:private-password@localhost/agentflow")
        )
    )
    disposed: list[Database] = []
    original_dispose = Database.dispose

    def failing_check(database: Database) -> None:
        raise OperationalError("SELECT 1", {}, RuntimeError("private-password"))

    def record_dispose(database: Database) -> None:
        disposed.append(database)
        original_dispose(database)

    monkeypatch.setattr(Database, "check_connection", failing_check)
    monkeypatch.setattr(Database, "dispose", record_dispose)

    async def run_fake_operation(operation: Callable[[], None]) -> None:
        # No actual I/O here: the real thread-pool boundary is tested with PostgreSQL.
        operation()

    monkeypatch.setattr("app.core.lifespan.run_in_threadpool", run_fake_operation)

    with pytest.raises(RuntimeError, match="PostgreSQL startup check failed") as error:
        async with application.router.lifespan_context(application):
            pytest.fail("Startup must not yield after a failed connection check")

    assert "private-password" not in str(error.value)
    assert error.value.__suppress_context__ is True
    assert len(disposed) == 1
    assert application.state.database is None
