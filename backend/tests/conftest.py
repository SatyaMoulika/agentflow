"""Isolate settings and select the test runtime."""

import logging
import os
from collections.abc import Iterator

import pytest

from app.core.config import Settings


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run PostgreSQL integration tests; requires isolated TEST_DATABASE_URL.",
    )
    parser.addoption(
        "--redis-integration",
        action="store_true",
        default=False,
        help="Run isolated real Redis/Celery tests; requires TEST_REDIS_URL.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("integration") and not config.getoption("--integration"):
            item.add_marker(pytest.mark.skip(reason="Use --integration with isolated PostgreSQL"))
        if item.get_closest_marker("redis_integration") and not config.getoption(
            "--redis-integration"
        ):
            item.add_marker(pytest.mark.skip(reason="Use --redis-integration with isolated Redis"))


@pytest.fixture(autouse=True)
def isolated_logging(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Capture AgentFlow without altering unrelated root loggers or later tests."""
    logger = logging.getLogger("agentflow")
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagation = logger.propagate
    logger.handlers = [caplog.handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield
    finally:
        for handler in logger.handlers:
            if handler not in original_handlers and handler is not caplog.handler:
                handler.close()
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagation


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a developer's environment or private .env affect the tests."""
    for key in tuple(os.environ):
        if key.upper().startswith(("AGENTFLOW_", "CELERY_")) or key.upper() == "GROQ_API_KEY":
            monkeypatch.delenv(key)
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def anyio_backend() -> str:
    """Use the already-installed AnyIO pytest support with asyncio only."""
    return "asyncio"
