"""The ownership boundary for application startup and shutdown."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.logging import configure_logging
from app.infrastructure.database.session import Database

logger = logging.getLogger("agentflow.lifecycle")


@asynccontextmanager
async def application_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Own the optional PostgreSQL pool; blocking operations run off the event loop."""
    configure_logging(application.state.settings.log_level)
    database: Database | None = None
    application.state.database = None
    try:
        if application.state.settings.database_url is not None:
            database = Database(application.state.settings.database_url)
            try:
                await run_in_threadpool(database.check_connection)
            except SQLAlchemyError:
                # Driver errors may contain usernames, hosts, and connection strings.
                raise RuntimeError(
                    "PostgreSQL startup check failed; verify database configuration."
                ) from None
            application.state.database = database
        logger.info(
            "Application startup",
            extra={"environment": application.state.settings.environment},
        )
        yield
    finally:
        if database is not None:
            await run_in_threadpool(database.dispose)
        application.state.database = None
        logger.info(
            "Application shutdown",
            extra={"environment": application.state.settings.environment},
        )
