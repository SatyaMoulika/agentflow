"""Reconstruct route state from actual persisted runner history, not a synthetic checkpoint."""

from uuid import UUID

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import NodeRun
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.executions.recovery import StoredAttempt, reconstruct_progress
from app.modules.executions.schemas import RunCreateRequest
from app.modules.executions.service import ExecutionService
from app.modules.workflows.compiler import compile_workflow
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration

GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "choose",
            "type": "condition",
            "config": {"field": "$.start.output.amount", "operator": "greater_than", "value": 10},
        },
        {"id": "high", "type": "transform", "config": {"operation": "identity"}},
        {"id": "low", "type": "transform", "config": {"operation": "identity"}},
        {"id": "join", "type": "merge", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "choose"},
        {"id": "e2", "source": "choose", "source_handle": "true", "target": "high"},
        {"id": "e3", "source": "choose", "source_handle": "false", "target": "low"},
        {"id": "e4", "source": "high", "target": "join"},
        {"id": "e5", "source": "low", "target": "join"},
        {"id": "e6", "source": "join", "target": "end"},
    ],
}


@pytest.mark.parametrize(("amount", "route"), [(20, "high"), (2, "low")])
def test_persisted_selected_route_can_be_reconstructed(
    repository_database: Database, amount: int, route: str
) -> None:
    with repository_database.unit_of_work() as session:
        user = UserRepository(session).add(
            email=f"{route}@recover.example.com", display_name="Owner", password_hash="fixture"
        )
        repo = WorkflowRepository(session)
        workflow = repo.add(owner_id=user.id, name="Recovery history")
        version = repo.append_version(
            workflow_id=workflow.id, owner_id=user.id, expected_version=0, definition=GRAPH
        )
        owner_id, workflow_id, version_id = user.id, workflow.id, version.id
    input_data = {"amount": amount, "CaseSensitive": "actual"}
    run = ExecutionService(repository_database).create_and_execute(
        workflow_id=workflow_id,
        owner_id=owner_id,
        data=RunCreateRequest(workflow_version_id=version_id, input=input_data),
    )
    assert run.status == "succeeded"
    plan = compile_workflow(GRAPH).plan
    assert plan is not None
    with repository_database.session() as session:
        rows = session.scalars(
            select(NodeRun)
            .where(NodeRun.workflow_run_id == UUID(str(run.id)))
            .order_by(NodeRun.created_at, NodeRun.id)
        ).all()
        attempts = [
            StoredAttempt(row.node_id, row.attempt_number, row.status, row.output_json)
            for row in rows
        ]
    progress = reconstruct_progress(plan, input_data, attempts)
    assert progress.state == "complete" and progress.visited == (
        "start",
        "choose",
        route,
        "join",
        "end",
    )
    assert progress.incoming == run.output
