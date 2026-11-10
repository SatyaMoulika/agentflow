"""Configured startup, liveness independence, and real database pool cleanup."""

import socket

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_configured_lifespan_connects_and_releases_pool(test_database_url: SecretStr) -> None:
    application = create_app(Settings(database_url=test_database_url))
    closed: list[bool] = []

    async with LifespanManager(application) as manager:
        database = application.state.database
        assert isinstance(database, Database)
        with database.session() as session:
            assert session.scalar(text("SELECT 1")) == 1

        def on_close(connection: object, connection_record: object) -> None:
            closed.append(True)

        event.listen(database.engine, "close", on_close)
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/health")
            assert response.json() == {"status": "ok", "service": "agentflow"}

    assert closed == [True]
    assert application.state.database is None


async def test_unavailable_database_fails_startup_with_safe_message(
    test_database_url: SecretStr,
) -> None:
    # An unused local port creates a genuine refused PostgreSQL connection.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = make_url(test_database_url.get_secret_value()).set(port=port)
    application = create_app(
        Settings(database_url=SecretStr(url.render_as_string(hide_password=False)))
    )

    with pytest.raises(RuntimeError, match="PostgreSQL startup check failed") as error:
        async with application.router.lifespan_context(application):
            pytest.fail("Unavailable PostgreSQL must prevent configured startup")

    assert application.state.database is None
    assert url.password is not None
    assert url.password not in str(error.value)
