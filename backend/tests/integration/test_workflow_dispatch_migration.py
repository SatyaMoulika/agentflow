"""Additive worker provenance migration preserves history and enforces target guards."""

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.auth.repository import UserRepository
from app.modules.executions.dispatch import enqueue_run
from app.modules.executions.repository import ExecutionRepository
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [{"id": "e", "source": "start", "target": "end"}],
}


def seed(connection: Connection):
    with Session(connection) as session, session.begin():
        owner = UserRepository(session).add(
            email="dispatch-migration@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Migration")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owner.id, expected_version=0, definition=GRAPH
        )
        run = ExecutionRepository(session).create_run(
            workflow_id=workflow.id,
            version_id=version.id,
            owner_id=owner.id,
            input_json={"CaseKey": 7},
        )
        probe = session.scalar(text("INSERT INTO outbox_messages DEFAULT VALUES RETURNING id"))
        return owner.id, workflow.id, version.id, run.id, probe


def test_upgrade_downgrade_preserve_existing_run_and_probe(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "0006")
    owner, _, _, run_id, probe = seed(connection)
    before = dict(
        connection.execute(text("SELECT * FROM workflow_runs WHERE id=:id"), {"id": run_id})
        .mappings()
        .one()
    )
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert (
        dict(
            connection.execute(text("SELECT * FROM workflow_runs WHERE id=:id"), {"id": run_id})
            .mappings()
            .one()
        )
        == before
    )
    assert (
        connection.scalar(
            text("SELECT workflow_run_id FROM outbox_messages WHERE id=:id"), {"id": probe}
        )
        is None
    )
    assert connection.scalar(text("SELECT count(*) FROM workflow_dispatches")) == 0
    connection.commit()
    command.downgrade(config, "0006")
    assert "workflow_dispatches" not in inspect(connection).get_table_names()
    assert connection.scalar(text("SELECT id FROM users")) == owner
    assert connection.scalar(text("SELECT id FROM outbox_messages")) == probe
    connection.commit()
    command.upgrade(config, "head")
    command.check(config)
    assert connection.scalar(text("SELECT id FROM workflow_runs")) == run_id


def test_dispatch_target_pending_uniqueness_and_retained_history_guards(
    migration_environment: tuple[Connection, Config],
) -> None:
    connection, config = migration_environment
    command.upgrade(config, "head")
    _, _, _, run_id, probe = seed(connection)
    with Session(connection) as session, session.begin():
        enqueue_run(session, run_id)
    message = connection.scalar(text("SELECT id FROM outbox_messages WHERE kind='workflow_run'"))
    connection.commit()
    statements = [
        "INSERT INTO outbox_messages (kind) VALUES ('workflow_run')",
        "INSERT INTO outbox_messages (kind, workflow_run_id) VALUES ('transport_probe', :run)",
        "INSERT INTO outbox_messages (kind, workflow_run_id) VALUES ('workflow_run', :run)",
        "UPDATE outbox_messages SET workflow_run_id=NULL WHERE id=:message",
        "DELETE FROM workflow_dispatches",
        "TRUNCATE workflow_dispatches CASCADE",
        "UPDATE workflow_dispatches SET dispatch_count=0",
    ]
    for statement in statements:
        with pytest.raises(IntegrityError):
            connection.execute(text(statement), {"run": run_id, "message": message})
        connection.rollback()
    assert (
        connection.scalar(text("SELECT id FROM outbox_messages WHERE id=:id"), {"id": probe})
        == probe
    )
    connection.commit()
    with pytest.raises(IntegrityError):
        command.downgrade(config, "0006")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010"
    assert connection.scalar(text("SELECT count(*) FROM workflow_dispatches")) == 1
