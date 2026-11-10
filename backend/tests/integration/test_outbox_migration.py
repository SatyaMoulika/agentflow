"""Additive migration preserves prior history; outbox rows are retained."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def test_outbox_upgrade_preserves_data_and_guards_history(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0004")
    owner = connection.scalar(
        text(
            "INSERT INTO users (email, display_name, password_hash) "
            "VALUES ('outbox@example.com', 'Owner', 'fixture') RETURNING id"
        )
    )
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    message_id = connection.scalar(text("INSERT INTO outbox_messages DEFAULT VALUES RETURNING id"))
    connection.commit()
    for sql in [
        "UPDATE outbox_messages SET kind='unsafe'",
        "DELETE FROM outbox_messages",
        "TRUNCATE outbox_messages",
        "UPDATE outbox_messages SET attempts=-1",
    ]:
        with pytest.raises(IntegrityError):
            connection.execute(text(sql))
        connection.rollback()
    assert connection.scalar(text("SELECT id FROM outbox_messages")) == message_id
    connection.commit()
    command.downgrade(config, "0004")
    assert "outbox_messages" not in inspect(connection).get_table_names()
    assert connection.scalar(text("SELECT id FROM users")) == owner
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT id FROM users")) == owner
