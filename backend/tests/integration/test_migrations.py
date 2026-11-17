"""The full migration path works on empty PostgreSQL schemas and matches ORM metadata."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.infrastructure.database.models import User, Workflow, WorkflowVersion

pytestmark = pytest.mark.integration


def test_upgrade_downgrade_reupgrade_and_metadata_drift(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    assert inspect(connection).get_table_names() == []
    connection.commit()

    command.upgrade(config, "head")
    assert set(inspect(connection).get_table_names()) == {
        "alembic_version",
        "users",
        "workflows",
        "workflow_versions",
        "refresh_sessions",
        "refresh_tokens",
        "workflow_runs",
        "node_runs",
        "execution_events",
        "run_commands",
        "outbox_messages",
        "run_claims",
        "workflow_dispatches",
        "node_retries",
        "connections",
        "agent_invocations",
        "gmail_authorizations",
        "gmail_connections",
    }
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0013"
    connection.commit()
    command.check(config)
    connection.commit()

    # Exercise the circular reference and mutation guard with populated tables,
    # not just empty DDL. A downgrade is explicitly destructive to these rows.
    with Session(connection) as session, session.begin():
        user = User(
            email="migration@example.com", password_hash="test-only-hash", display_name="Test"
        )
        workflow = Workflow(owner=user, name="Migration probe")
        session.add(workflow)
        session.flush()
        version = WorkflowVersion(
            workflow=workflow,
            creator=user,
            version_number=1,
            definition_json={"schema_version": "1.0", "nodes": [], "edges": []},
        )
        session.add(version)
        session.flush()
        workflow.current_version_id = version.id

    command.downgrade(config, "base")
    assert inspect(connection).get_table_names() == ["alembic_version"]
    assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM pg_proc WHERE pronamespace = current_schema()::regnamespace "
                "AND proname IN ('reject_workflow_version_mutation', 'set_updated_at')"
            )
        )
        == 0
    )
    connection.commit()

    command.upgrade(config, "head")
    command.check(config)
    assert set(inspect(connection).get_table_names()) == {
        "alembic_version",
        "users",
        "workflows",
        "workflow_versions",
        "refresh_sessions",
        "refresh_tokens",
        "workflow_runs",
        "node_runs",
        "execution_events",
        "run_commands",
        "outbox_messages",
        "run_claims",
        "workflow_dispatches",
        "node_retries",
        "connections",
        "agent_invocations",
        "gmail_authorizations",
        "gmail_connections",
    }


def test_migration_creates_named_indexes_and_same_workflow_foreign_key(
    migrated_connection: Connection,
) -> None:
    inspector = inspect(migrated_connection)
    indexes = {index["name"] for index in inspector.get_indexes("workflows")}
    assert {"ix_workflows_owner_updated_id", "ix_workflows_owner_status_updated_id"} <= indexes
    assert "ix_workflow_versions_created_by" in {
        index["name"] for index in inspector.get_indexes("workflow_versions")
    }
    pointer = next(
        fk
        for fk in inspector.get_foreign_keys("workflows")
        if fk["name"] == "fk_workflows_current_version"
    )
    assert pointer["constrained_columns"] == ["id", "current_version_id"]
    assert pointer["referred_columns"] == ["workflow_id", "id"]
    assert pointer.get("options", {}).get("ondelete") == "RESTRICT"
