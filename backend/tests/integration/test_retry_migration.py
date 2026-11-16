"""Populated upgrades preserve prior dispatch history; retry history cannot be dropped."""

from datetime import timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.database.models import NodeRetry
from app.modules.auth.repository import UserRepository
from app.modules.executions.dispatch import enqueue_run
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import EventType, FailureCode, NodeStatus, RunStatus
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration


def test_retry_upgrade_preserves_populated_dispatch_and_empty_retry_downgrade(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0007")
    owner = connection.scalar(
        text(
            "INSERT INTO users (email, display_name, password_hash) "
            "VALUES ('retry-migration@example.com', 'Owner', 'fixture') RETURNING id"
        )
    )
    workflow = connection.scalar(
        text(
            "INSERT INTO workflows (owner_id, name) VALUES (:owner, 'Retry migration') RETURNING id"
        ),
        {"owner": owner},
    )
    version = connection.scalar(
        text(
            "INSERT INTO workflow_versions "
            "(workflow_id, created_by, version_number, definition_json) "
            "VALUES (:workflow, :owner, 1, CAST(:definition AS jsonb)) "
            "RETURNING id"
        ),
        {
            "workflow": workflow,
            "owner": owner,
            "definition": '{"schema_version":"1.0","nodes":[],"edges":[]}',
        },
    )
    run = connection.scalar(
        text(
            "INSERT INTO workflow_runs (workflow_id, workflow_version_id, input_json) "
            "VALUES (:workflow, :version, CAST(:input AS jsonb)) RETURNING id"
        ),
        {"workflow": workflow, "version": version, "input": '{"CaseKey":42}'},
    )
    connection.execute(text("INSERT INTO workflow_dispatches (run_id) VALUES (:run)"), {"run": run})
    message = connection.scalar(
        text(
            "INSERT INTO outbox_messages (kind, workflow_run_id) "
            "VALUES ('workflow_run', :run) RETURNING id"
        ),
        {"run": run},
    )
    before = dict(connection.execute(text("SELECT * FROM workflow_dispatches")).mappings().one())
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    after = dict(connection.execute(text("SELECT * FROM workflow_dispatches")).mappings().one())
    assert {key: after[key] for key in before} == before
    assert after["retry_base_seconds"] == 5 and after["retry_max_seconds"] == 60
    assert connection.scalar(text("SELECT id FROM outbox_messages")) == message
    assert connection.scalar(text("SELECT count(*) FROM node_retries")) == 0
    connection.commit()
    command.downgrade(config, "0007")
    assert (
        dict(connection.execute(text("SELECT * FROM workflow_dispatches")).mappings().one())
        == before
    )
    assert connection.scalar(text("SELECT id FROM outbox_messages")) == message
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT id FROM workflow_runs")) == run


def test_retry_history_prevents_downgrade(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "head")
    with Session(connection) as session, session.begin():
        owner = UserRepository(session).add(
            email="retained-retry@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Retry history")
        version = workflows.append_version(
            workflow_id=workflow.id,
            owner_id=owner.id,
            expected_version=0,
            definition={
                "schema_version": "1.0",
                "nodes": [
                    {"id": "start", "type": "manual", "config": {}},
                    {"id": "end", "type": "end", "config": {}},
                ],
                "edges": [{"id": "a", "source": "start", "target": "end"}],
            },
        )
        repository = ExecutionRepository(session)
        run = repository.create_run(
            workflow_id=workflow.id,
            version_id=version.id,
            owner_id=owner.id,
            input_json={},
            max_attempts=2,
        )
        enqueue_run(session, run.id)
        repository.transition_run(
            run_id=run.id, owner_id=owner.id, expected_revision=0, target=RunStatus.RUNNING
        )
        attempt = repository.add_attempt(
            run_id=run.id,
            owner_id=owner.id,
            expected_run_revision=1,
            node_id="start",
            input_json={},
        )
        repository.transition_attempt(
            run_id=run.id,
            owner_id=owner.id,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.FAILED,
            error_code=FailureCode.INTERNAL_FAILURE,
        )
        now = session.scalar(text("SELECT clock_timestamp()"))
        assert now is not None
        session.add(
            NodeRetry(
                node_run_id=attempt.id,
                workflow_run_id=run.id,
                created_at=now,
                due_at=now + timedelta(seconds=5),
            )
        )
        session.flush()
        repository._event(run, EventType.NODE_RETRY_SCHEDULED, {"node_id": "start"}, attempt.id)
    before = connection.scalar(text("SELECT count(*) FROM execution_events"))
    connection.commit()
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0007")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0012"
    assert connection.scalar(text("SELECT count(*) FROM execution_events")) == before
    assert connection.scalar(text("SELECT count(*) FROM node_retries")) == 1
