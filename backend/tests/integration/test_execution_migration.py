"""0003 can be reversed in disposable storage without losing the existing auth/workflow rows."""

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.infrastructure.database.models import RefreshSession, RefreshToken, User
from app.modules.executions.repository import ExecutionRepository
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration


def test_0003_populated_roundtrip_preserves_existing_auth_and_workflow_data(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0002")
    with Session(connection) as session, session.begin():
        user = User(
            email="migration-executions@example.com",
            password_hash="fixture",
            display_name="Migration",
        )
        session.add(user)
        session.flush()
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=user.id, name="Retained workflow")
        version = workflows.append_version(
            workflow_id=workflow.id,
            owner_id=user.id,
            expected_version=0,
            definition={"schema_version": "1.0", "nodes": [], "edges": []},
        )
        family = RefreshSession(user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=7))
        session.add(family)
        session.flush()
        session.add(RefreshToken(session_id=family.id, token_hash="a" * 64, csrf_hash="b" * 64))
        owner_id, workflow_id, version_id = user.id, workflow.id, version.id
    command.upgrade(config, "head")
    command.check(config)
    connection.commit()
    with Session(connection) as session, session.begin():
        ExecutionRepository(session).create_run(
            workflow_id=workflow_id,
            version_id=version_id,
            owner_id=owner_id,
            input_json={"test": True},
        )
    command.downgrade(config, "0002")
    assert "workflow_runs" not in inspect(connection).get_table_names()
    assert connection.execute(select(User.id)).scalar_one() == owner_id
    assert connection.execute(select(RefreshToken.token_hash)).scalar_one() == "a" * 64
    assert (
        connection.execute(text("SELECT current_version_id FROM workflows")).scalar_one()
        == version_id
    )
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM pg_proc "
                "WHERE pronamespace = current_schema()::regnamespace "
                "AND proname IN ('guard_workflow_run_state', 'guard_node_run_state', "
                "'reject_execution_event_mutation', 'reject_execution_history_deletion')"
            )
        )
        == 0
    )
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT count(*) FROM workflow_runs")) == 0
    assert connection.execute(select(User.id)).scalar_one() == owner_id
