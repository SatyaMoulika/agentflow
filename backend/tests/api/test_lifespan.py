"""Exercise actual ASGI lifespan events as well as context unwinding."""

import logging

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_asgi_startup_and_shutdown_surround_requests(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = create_app(Settings(environment="testing"))
    caplog.set_level(logging.INFO, logger="agentflow.lifecycle")

    async with LifespanManager(application) as manager:
        assert [record.message for record in caplog.records] == ["Application startup"]
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/v1/health")).status_code == 200

    records = [record for record in caplog.records if record.name == "agentflow.lifecycle"]
    assert [record.message for record in records] == ["Application startup", "Application shutdown"]
    assert [record.__dict__["environment"] for record in records] == ["testing", "testing"]


async def test_request_failure_does_not_end_application_lifetime(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = create_app()
    caplog.set_level(logging.INFO, logger="agentflow.lifecycle")

    @application.get("/test-failure", include_in_schema=False)
    async def failing_route() -> None:
        raise RuntimeError("test failure")

    async with LifespanManager(application) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            assert (await client.get("/test-failure")).status_code == 500
            assert (await client.get("/api/v1/health")).status_code == 200
        assert "Application shutdown" not in caplog.messages

    assert caplog.messages.count("Application shutdown") == 1


async def test_lifespan_finally_runs_when_context_exits_with_an_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = create_app()
    caplog.set_level(logging.INFO, logger="agentflow.lifecycle")

    with pytest.raises(RuntimeError, match="interrupted context"):
        async with application.router.lifespan_context(application):
            raise RuntimeError("interrupted context")

    assert caplog.messages == ["Application startup", "Application shutdown"]
