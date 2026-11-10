"""Event replay closes when a session expires without leaking token contents."""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest

from app.core.tokens import AccessTokens, InvalidAccessTokenError
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import AuthenticationError
from app.modules.executions.event_stream import stream_events
from app.modules.executions.schemas import ExecutionEventPage, ExecutionEventResponse
from app.modules.executions.state import EventType

pytestmark = pytest.mark.anyio


async def test_stream_revalidates_token_and_stops_at_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid4()

    class Tokens:
        count = 0

        def subject(self, token: str):
            self.count += 1
            if self.count > 1:
                raise InvalidAccessTokenError()
            return owner

    class Auth:
        def __init__(self, database):
            pass

        def current_user(self, user_id):
            return None

    class Events:
        def __init__(self, database):
            pass

        def events(self, **kwargs):
            return ExecutionEventPage(items=[], next_after_sequence=kwargs["after_sequence"])

    monkeypatch.setattr("app.modules.executions.event_stream.AuthService", Auth)
    monkeypatch.setattr("app.modules.executions.event_stream.ExecutionService", Events)
    page = ExecutionEventPage(
        items=[
            ExecutionEventResponse(
                sequence=1,
                node_run_id=None,
                event_type=EventType.RUN_CREATED,
                payload={"status": "queued"},
                created_at=datetime.now(UTC),
            )
        ],
        next_after_sequence=1,
    )
    tokens = Tokens()
    frames = [
        frame
        async for frame in stream_events(
            cast(Database, None),
            uuid4(),
            owner,
            "private-token",
            cast(AccessTokens, tokens),
            page,
            duration=1,
            interval=0.001,
        )
    ]
    assert len(frames) == 1 and frames[0].startswith("id: 1\nevent: execution\n")
    assert "private-token" not in frames[0] and tokens.count == 2


async def test_stream_stops_when_account_is_deactivated(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = uuid4()

    class Tokens:
        def subject(self, token: str):
            return owner

    class Auth:
        checks = 0

        def __init__(self, database):
            pass

        def current_user(self, user_id):
            Auth.checks += 1
            if Auth.checks == 2:
                raise AuthenticationError()

    class Events:
        def __init__(self, database):
            pass

        def events(self, **kwargs):
            return ExecutionEventPage(items=[], next_after_sequence=kwargs["after_sequence"])

    monkeypatch.setattr("app.modules.executions.event_stream.AuthService", Auth)
    monkeypatch.setattr("app.modules.executions.event_stream.ExecutionService", Events)
    page = ExecutionEventPage(items=[], next_after_sequence=0)
    frames = [
        frame
        async for frame in stream_events(
            cast(Database, None),
            uuid4(),
            owner,
            "token",
            cast(AccessTokens, Tokens()),
            page,
            duration=1,
            interval=0.001,
        )
    ]
    assert frames == [] and Auth.checks == 2


async def test_stream_replays_more_than_one_page_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = uuid4()
    now = datetime.now(UTC)

    def event(number: int) -> ExecutionEventResponse:
        return ExecutionEventResponse(
            sequence=number,
            node_run_id=None,
            event_type=EventType.RUN_CREATED,
            payload={"status": "queued"},
            created_at=now,
        )

    class Tokens:
        def subject(self, token: str):
            return owner

    class Auth:
        def __init__(self, database):
            pass

        def current_user(self, user_id):
            return None

    class Events:
        def __init__(self, database):
            pass

        def events(self, **kwargs):
            assert kwargs["after_sequence"] == 100
            return ExecutionEventPage(items=[event(101)], next_after_sequence=101)

    monkeypatch.setattr("app.modules.executions.event_stream.AuthService", Auth)
    monkeypatch.setattr("app.modules.executions.event_stream.ExecutionService", Events)
    page = ExecutionEventPage(
        items=[event(number) for number in range(1, 101)], next_after_sequence=100
    )
    generator = stream_events(
        cast(Database, None),
        uuid4(),
        owner,
        "token",
        cast(AccessTokens, Tokens()),
        page,
        duration=1,
        interval=0.001,
    )
    frames = [await anext(generator) for _ in range(101)]
    await generator.aclose()
    assert [int(frame.splitlines()[0][4:]) for frame in frames] == list(range(1, 102))
