"""Bounded authenticated event streaming; database sessions close between polls."""

import asyncio
from collections.abc import AsyncGenerator
from time import monotonic
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.core.tokens import AccessTokens, InvalidAccessTokenError
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import AuthenticationError, AuthStorageUnavailableError
from app.modules.auth.service import AuthService
from app.modules.executions.exceptions import (
    ExecutionNotFoundError,
    ExecutionStorageUnavailableError,
)
from app.modules.executions.schemas import ExecutionEventPage
from app.modules.executions.service import ExecutionService


async def stream_events(
    database: Database,
    run_id: UUID,
    owner_id: UUID,
    token: str,
    tokens: AccessTokens,
    initial: ExecutionEventPage,
    *,
    duration: float = 25,
    interval: float = 1.5,
) -> AsyncGenerator[str]:
    """Replay pages and renew authentication on each bounded polling iteration."""
    deadline = monotonic() + duration
    heartbeat = monotonic() + 10
    cursor = initial.next_after_sequence if not initial.items else initial.items[0].sequence - 1
    page = initial
    while monotonic() < deadline:
        try:
            if tokens.subject(token) != owner_id:
                return
            await run_in_threadpool(AuthService(database).current_user, owner_id)
            for event in page.items:
                if event.sequence > cursor:
                    yield (
                        f"id: {event.sequence}\nevent: execution\n"
                        f"data: {event.model_dump_json()}\n\n"
                    )
                    cursor = event.sequence
            if len(page.items) < 100:
                if monotonic() >= heartbeat:
                    yield ": heartbeat\n\n"
                    heartbeat = monotonic() + 10
                await asyncio.sleep(interval)
            page = await run_in_threadpool(
                ExecutionService(database).events,
                run_id=run_id,
                owner_id=owner_id,
                after_sequence=cursor,
                limit=100,
            )
        except (
            InvalidAccessTokenError,
            AuthenticationError,
            AuthStorageUnavailableError,
            ExecutionNotFoundError,
            ExecutionStorageUnavailableError,
        ):
            return
