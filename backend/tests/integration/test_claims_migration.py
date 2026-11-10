"""Claims migration is additive to populated existing accounts."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

pytestmark = pytest.mark.integration


def test_claim_upgrade_and_disposable_downgrade_preserve_existing_rows(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0005")
    owner = connection.scalar(
        text(
            "INSERT INTO users (email, display_name, password_hash) "
            "VALUES ('claim-migration@example.com', 'Owner', 'fixture') RETURNING id"
        )
    )
    message = connection.scalar(text("INSERT INTO outbox_messages DEFAULT VALUES RETURNING id"))
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT id FROM users")) == owner
    assert connection.scalar(text("SELECT id FROM outbox_messages")) == message
    connection.commit()
    command.downgrade(config, "0005")
    assert "run_claims" not in inspect(connection).get_table_names()
    assert connection.scalar(text("SELECT id FROM users")) == owner
    assert connection.scalar(text("SELECT id FROM outbox_messages")) == message
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
