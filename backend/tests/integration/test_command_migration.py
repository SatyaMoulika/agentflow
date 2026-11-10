"""Populated additive upgrade, immutable budgets/receipts and downgrade isolation."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration


def test_command_migration_preserves_populated_history_and_guards(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0003")
    owner = connection.scalar(
        text(
            """
            INSERT INTO users (email, display_name, password_hash) VALUES
            ('migration@commands.example.com', 'Owner', 'fixture') RETURNING id
            """
        )
    )
    other = connection.scalar(
        text(
            """
            INSERT INTO users (email, display_name, password_hash) VALUES
            ('other@commands.example.com', 'Other', 'fixture') RETURNING id
            """
        )
    )
    workflow = connection.scalar(
        text("INSERT INTO workflows (owner_id, name) VALUES (:owner, 'Retained') RETURNING id"),
        {"owner": owner},
    )
    version = connection.scalar(
        text(
            """
            INSERT INTO workflow_versions (workflow_id, created_by, version_number,
            definition_json) VALUES (:workflow, :owner, 1,
            '{"schema_version":"1.0","nodes":[],"edges":[]}') RETURNING id
            """
        ),
        {"workflow": workflow, "owner": owner},
    )
    run = connection.scalar(
        text(
            """
            INSERT INTO workflow_runs (workflow_id, workflow_version_id, input_json) VALUES
            (:workflow, :version, jsonb_build_object('retained', true)) RETURNING id
            """
        ),
        {"workflow": workflow, "version": version},
    )
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    row = connection.execute(text("SELECT id, max_attempts, input_json FROM workflow_runs")).one()
    assert tuple(row) == (run, 1, {"retained": True})
    connection.execute(
        text(
            """
            INSERT INTO run_commands (owner_id, key_digest, request_digest, run_id) VALUES
            (:owner, :key, :request, :run)
            """
        ),
        {"owner": owner, "key": "a" * 64, "request": "b" * 64, "run": run},
    )
    connection.commit()
    for sql, params in [
        ("UPDATE workflow_runs SET max_attempts=2", {}),
        ("UPDATE run_commands SET request_digest=:digest", {"digest": "c" * 64}),
        ("DELETE FROM run_commands", {}),
        ("TRUNCATE run_commands", {}),
        (
            """
            INSERT INTO run_commands (owner_id, key_digest, request_digest, run_id) VALUES
            (:owner, :key, :request, :run)
            """,
            {"owner": other, "key": "c" * 64, "request": "d" * 64, "run": run},
        ),
    ]:
        with pytest.raises(IntegrityError):
            connection.execute(text(sql), params)
        connection.rollback()
    command.downgrade(config, "0003")
    assert connection.scalar(text("SELECT id FROM workflow_runs")) == run
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT id FROM workflow_runs")) == run
