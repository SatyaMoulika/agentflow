"""Provider outcomes preserve prior runs and cannot be downgraded out of history."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.auth.repository import UserRepository
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import FailureCode, NodeStatus, RunStatus
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration


def test_provider_upgrade_preserves_history_and_refuses_a_lossy_downgrade(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0009")
    with Session(connection) as session, session.begin():
        owner = UserRepository(session).add(
            email="provider-migration@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Provider migration")
        version = workflows.append_version(
            workflow_id=workflow.id,
            owner_id=owner.id,
            expected_version=0,
            definition={
                "schema_version": "1.0",
                "nodes": [
                    {"id": "start", "type": "manual", "config": {}},
                    {
                        "id": "ai",
                        "type": "groq",
                        "config": {"instruction": "Reply", "input_field": "message"},
                    },
                    {"id": "end", "type": "end", "config": {}},
                ],
                "edges": [
                    {"id": "a", "source": "start", "target": "ai"},
                    {"id": "b", "source": "ai", "target": "end"},
                ],
            },
        )
        run = ExecutionRepository(session).create_run(
            workflow_id=workflow.id,
            version_id=version.id,
            owner_id=owner.id,
            input_json={"BusinessKey": 42},
        )
        run_id, owner_id = run.id, owner.id
    before = dict(
        connection.execute(text("SELECT id,workflow_version_id,input_json FROM workflow_runs"))
        .mappings()
        .one()
    )
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert (
        dict(
            connection.execute(text("SELECT id,workflow_version_id,input_json FROM workflow_runs"))
            .mappings()
            .one()
        )
        == before
    )
    connection.commit()
    with Session(connection) as session, session.begin():
        repository = ExecutionRepository(session)
        repository.transition_run(
            run_id=run_id, owner_id=owner_id, expected_revision=0, target=RunStatus.RUNNING
        )
        attempt = repository.add_attempt(
            run_id=run_id, owner_id=owner_id, expected_run_revision=1, node_id="ai", input_json={}
        )
        repository.transition_attempt(
            run_id=run_id,
            owner_id=owner_id,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repository.transition_attempt(
            run_id=run_id,
            owner_id=owner_id,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.FAILED,
            error_code=FailureCode.PROVIDER_RATE_LIMITED,
            provider_metadata={
                "provider": "groq",
                "requested_model": "test-model",
                "duration_ms": 1,
                "error_code": "PROVIDER_RATE_LIMITED",
                "retry_after_seconds": 2,
            },
        )
        repository.transition_run(
            run_id=run_id,
            owner_id=owner_id,
            expected_revision=1,
            target=RunStatus.FAILED,
            error_code=FailureCode.PROVIDER_RATE_LIMITED,
        )
    count = connection.scalar(text("SELECT count(*) FROM execution_events"))
    connection.commit()
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0009")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0013"
    assert connection.scalar(text("SELECT count(*) FROM execution_events")) == count
    assert (
        connection.scalar(
            text(
                "SELECT event_payload->'provider'->>'error_code' FROM execution_events "
                "WHERE event_payload ? 'provider'"
            )
        )
        == "PROVIDER_RATE_LIMITED"
    )
