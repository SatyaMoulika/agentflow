"""Real database constraints and a non-destructive 0002/0001 migration round trip."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.database.models import RefreshSession, RefreshToken, User
from app.infrastructure.database.session import Database
from app.modules.auth.refresh_repository import RefreshRepository
from app.modules.auth.repository import UserRepository

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(
    "bad", ["expiry", "hash", "csrf", "second-live", "duplicate-hash", "missing-user"]
)
def test_refresh_schema_rejects_invalid_state(repository_database: Database, bad: str) -> None:
    now = datetime.now(UTC)
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        user = UserRepository(session).add(
            email="constraints@example.com", password_hash="fixture", display_name="Constraints"
        )
        repository = RefreshRepository(session)
        family = repository.create_session(user.id, now + timedelta(days=7))
        if bad == "expiry":
            family.expires_at = now - timedelta(days=1)
            session.flush()
        elif bad == "missing-user":
            repository.create_session(uuid4(), now + timedelta(days=7))
        else:
            repository.add_token(
                family.id,
                "invalid" if bad == "hash" else "a" * 64,
                "invalid" if bad == "csrf" else "b" * 64,
            )
            if bad == "second-live":
                repository.add_token(family.id, "c" * 64, "d" * 64)
            elif bad == "duplicate-hash":
                other = repository.create_session(user.id, now + timedelta(days=7))
                repository.add_token(other.id, "a" * 64, "e" * 64)
    with repository_database.session() as session:
        assert session.scalars(select(RefreshSession)).all() == []
        assert session.scalars(select(RefreshToken)).all() == []


def test_0002_downgrade_preserves_users_and_reupgrade_has_no_drift(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0001")
    with Session(connection) as session, session.begin():
        user = User(
            email="migration-refresh@example.com", password_hash="fixture", display_name="Migration"
        )
        session.add(user)
        session.flush()
        user_id = user.id
    command.upgrade(config, "0002")
    with Session(connection) as session, session.begin():
        family = RefreshSession(user_id=user_id, expires_at=datetime.now(UTC) + timedelta(days=7))
        session.add(family)
        session.flush()
        session.add(RefreshToken(session_id=family.id, token_hash="a" * 64, csrf_hash="b" * 64))
    command.downgrade(config, "0001")
    assert "refresh_tokens" not in inspect(connection).get_table_names()
    assert connection.execute(select(User.id)).scalar_one() == user_id
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.execute(select(User.id)).scalar_one() == user_id
    assert connection.execute(select(RefreshSession)).all() == []
