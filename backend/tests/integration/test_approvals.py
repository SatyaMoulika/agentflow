"""Durable selected-route approval, ownership, concurrency and retained history."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.infrastructure.database.models import (
    Approval,
    OutboxMessage,
    RunClaim,
    WorkflowRun,
)
from app.modules.approvals.schemas import ApprovalDecision
from app.modules.approvals.service import ApprovalService
from app.modules.auth.repository import UserRepository
from app.modules.executions.exceptions import (
    ExecutionConflictError,
    ExecutionNotFoundError,
    WorkflowNotExecutableError,
)
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.schemas import RunCreateRequest
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import NodeStatus, RunStatus
from app.modules.executions.worker_runner import PureWorkerRunner
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.workflows.compiler import compile_workflow
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration

GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "review", "type": "approval", "config": {"title": "Review calculation"}},
        {"id": "yes", "type": "end", "config": {}},
        {"id": "no", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "a", "source": "start", "target": "review"},
        {"id": "b", "source": "review", "source_handle": "approved", "target": "yes"},
        {"id": "c", "source": "review", "source_handle": "rejected", "target": "no"},
    ],
}


@pytest.fixture
def prepared(repository_database):
    database = repository_database
    with database.unit_of_work() as session:
        user = UserRepository(session).add(
            email=f"{uuid4().hex}@example.com", display_name="Reviewer", password_hash="fixture"
        )
        owner = user.id
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner, name="Review")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owner, expected_version=0, definition=deepcopy(GRAPH)
        )
        workflow_id, version_id = workflow.id, version.id
    settings = Settings(
        database_url=SecretStr("postgresql+psycopg://unused@localhost/agentflow_test"),
        redis_url=SecretStr("redis://localhost/15"),
        background_execution_enabled=True,
    )
    service = ExecutionService(database, settings)
    data = RunCreateRequest(workflow_version_id=version_id, input={"CaseKey": {"ID": 7}})
    run = service.create_and_execute(workflow_id=workflow_id, owner_id=owner, data=data)
    # A real dispatcher state transition, using a no-op test broker.
    OutboxDispatcher(database, lambda _: None, publish_workflow=lambda _: None).dispatch_once()
    assert PureWorkerRunner(database, require_dispatch=True).run(run_id=run.id, owner_id=owner)
    approvals = ApprovalService(database)
    row = approvals.list(owner).items[0]
    return database, owner, run.id, row.id, workflow_id, data


@pytest.mark.parametrize(
    "decision,selected,skipped", [("approved", "yes", "no"), ("rejected", "no", "yes")]
)
def test_pause_decide_new_worker_preserves_committed_history(prepared, decision, selected, skipped):
    database, owner, run_id, approval_id, _, _ = prepared
    approvals = ApprovalService(database)
    executions = ExecutionService(database)
    before = executions.get(run_id=run_id, owner_id=owner)
    assert before.status == RunStatus.WAITING_APPROVAL
    assert approvals.get(owner, approval_id).input == {"CaseKey": {"ID": 7}}
    with database.session() as session:
        assert session.get(RunClaim, run_id).lease_token is None
    assert not PureWorkerRunner(database).run(run_id=run_id, owner_id=owner)
    result = approvals.decide(
        owner, approval_id, ApprovalDecision(decision=decision, note="Reviewed")
    )
    assert result.status == decision
    with database.session() as session:
        intents = list(
            session.scalars(select(OutboxMessage).where(OutboxMessage.workflow_run_id == run_id))
        )
        assert len(intents) == 2 and intents[-1].published_at is None
    assert (
        approvals.decide(owner, approval_id, ApprovalDecision(decision=decision, note="Reviewed"))
        == result
    )
    # A new worker instance reconstructs only committed results; no in-memory continuation.
    schema = database.engine.get_execution_options()["schema_translate_map"][None]
    code = """
import os, sys
from uuid import UUID
from pydantic import SecretStr
from app.infrastructure.database.session import Database
from app.modules.executions.worker_runner import PureWorkerRunner
database = Database(SecretStr(os.environ['TEST_DATABASE_URL']))
database.engine = database.engine.execution_options(schema_translate_map={None: sys.argv[1]})
database.session_factory.configure(bind=database.engine)
try:
    assert PureWorkerRunner(database, require_dispatch=True).run(
        run_id=UUID(sys.argv[2]), owner_id=UUID(sys.argv[3]))
finally:
    database.dispose()
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, schema, str(run_id), str(owner)],
        capture_output=True,
        timeout=30,
        env=os.environ.copy(),
    )
    assert completed.returncode == 0, "Separate worker process could not continue approval"
    after = executions.get(run_id=run_id, owner_id=owner)
    assert after.status == RunStatus.SUCCEEDED and after.output == {"decision": decision}
    assert after.node_runs[0] == before.node_runs[0]
    assert [(row.node_id, row.status.value) for row in after.node_runs] == [
        ("start", "succeeded"),
        ("review", "succeeded"),
        (selected, "succeeded"),
        (skipped, "skipped"),
    ]
    assert approvals.get(owner, approval_id).status == decision
    assert not PureWorkerRunner(database).run(run_id=run_id, owner_id=owner)


def test_decision_and_resume_intent_roll_back_together(prepared, monkeypatch):
    from app.modules.outbox.repository import OutboxRepository

    database, owner, run_id, approval_id, _, _ = prepared
    before = ExecutionService(database).get(run_id=run_id, owner_id=owner)

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr(OutboxRepository, "enqueue_workflow", unavailable)
    with pytest.raises(RuntimeError, match="synthetic outbox failure"):
        ApprovalService(database).decide(owner, approval_id, ApprovalDecision(decision="approved"))
    assert ApprovalService(database).get(owner, approval_id).status == "pending"
    assert ExecutionService(database).get(run_id=run_id, owner_id=owner) == before


def test_decision_uses_original_version_after_a_workflow_edit(prepared):
    database, owner, run_id, approval_id, workflow_id, _ = prepared
    with database.unit_of_work() as session:
        graph = {
            "schema_version": "1.0",
            "nodes": [
                {"id": "start", "type": "manual", "config": {}},
                {"id": "end", "type": "end", "config": {}},
            ],
            "edges": [{"id": "a", "source": "start", "target": "end"}],
        }
        WorkflowRepository(session).append_version(
            workflow_id=workflow_id, owner_id=owner, expected_version=1, definition=graph
        )
    ApprovalService(database).decide(owner, approval_id, ApprovalDecision(decision="approved"))
    PureWorkerRunner(database).run(run_id=run_id, owner_id=owner)
    completed = ExecutionService(database).get(run_id=run_id, owner_id=owner)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"decision": "approved"}
    assert completed.version.version_number == 1


def test_owner_boundaries_and_cancellation(prepared):
    database, owner, run_id, approval_id, _, _ = prepared
    approvals = ApprovalService(database)
    other = uuid4()
    assert approvals.list(other).total == 0
    with pytest.raises(ExecutionNotFoundError):
        approvals.get(other, approval_id)
    with pytest.raises(ExecutionNotFoundError):
        approvals.decide(other, approval_id, ApprovalDecision(decision="approved"))
    ExecutionService(database).cancel(run_id=run_id, owner_id=owner)
    assert approvals.get(owner, approval_id).status == "cancelled"
    with pytest.raises(ExecutionConflictError):
        approvals.decide(owner, approval_id, ApprovalDecision(decision="approved"))
    assert not PureWorkerRunner(database).run(run_id=run_id, owner_id=owner)


def test_competing_decisions_have_one_winner(prepared):
    database, owner, run_id, approval_id, _, _ = prepared
    barrier = Barrier(2)

    def decide(choice):
        barrier.wait(timeout=5)
        try:
            return (
                ApprovalService(database)
                .decide(owner, approval_id, ApprovalDecision(decision=choice))
                .status
            )
        except ExecutionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(decide, ["approved", "rejected"]))
    assert outcomes.count("conflict") == 1
    with database.session() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(OutboxMessage)
                .where(OutboxMessage.workflow_run_id == run_id)
            )
            == 2
        )


def test_expiry_fails_without_resume(prepared):
    database, owner, run_id, approval_id, _, _ = prepared
    # Construct an already elapsed, legitimate request in this disposable schema.
    # The original request is retained; a separate run models elapsed wall time.
    with database.unit_of_work() as session:
        original = session.get(WorkflowRun, run_id)
        repo = ExecutionRepository(session)
        run = repo.create_run(
            workflow_id=original.workflow_id,
            version_id=original.workflow_version_id,
            owner_id=owner,
            input_json={},
        )
        from app.modules.executions.dispatch import enqueue_run

        enqueue_run(session, run.id)
        repo.transition_run(
            run_id=run.id, owner_id=owner, expected_revision=0, target=RunStatus.RUNNING
        )
        attempt = repo.add_attempt(
            run_id=run.id, owner_id=owner, expected_run_revision=1, node_id="review", input_json={}
        )
        repo.transition_attempt(
            run_id=run.id,
            owner_id=owner,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=0,
            target=NodeStatus.RUNNING,
        )
        repo.transition_attempt(
            run_id=run.id,
            owner_id=owner,
            attempt_id=attempt.id,
            expected_run_revision=1,
            expected_revision=1,
            target=NodeStatus.WAITING_APPROVAL,
        )
        now = session.scalar(select(func.clock_timestamp()))
        row = Approval(
            workflow_run_id=run.id,
            node_run_id=attempt.id,
            node_id="review",
            assigned_to=owner,
            title="Expired",
            created_at=now - timedelta(minutes=2),
            expires_at=now - timedelta(minutes=1),
        )
        session.add(row)
        session.flush()
        expired_id, expired_run = row.id, run.id
        repo.transition_run(
            run_id=run.id, owner_id=owner, expected_revision=1, target=RunStatus.WAITING_APPROVAL
        )
    assert ApprovalService(database).expire_due() == 1
    assert ApprovalService(database).expire_due() == 0
    assert ApprovalService(database).get(owner, expired_id).status == "expired"
    assert (
        ExecutionService(database).get(run_id=expired_run, owner_id=owner).status
        == RunStatus.FAILED
    )
    with pytest.raises(ExecutionConflictError):
        ApprovalService(database).decide(owner, expired_id, ApprovalDecision(decision="approved"))


def test_requests_and_decisions_cannot_be_rewritten(prepared):
    database, owner, _, approval_id, _, _ = prepared
    with pytest.raises(IntegrityError), database.unit_of_work() as session:
        session.get(Approval, approval_id).assigned_to = uuid4()
    ApprovalService(database).decide(owner, approval_id, ApprovalDecision(decision="approved"))
    with pytest.raises(IntegrityError), database.unit_of_work() as session:
        session.get(Approval, approval_id).status = "rejected"


def test_requires_worker_mode_and_rejects_external_approval_graph(prepared):
    database, owner, _, _, workflow_id, data = prepared
    with pytest.raises(WorkflowNotExecutableError):
        ExecutionService(database).create_and_execute(
            workflow_id=workflow_id, owner_id=owner, data=data
        )
    graph = deepcopy(GRAPH)
    graph["nodes"][0] = {"id": "start", "type": "http", "config": {"connection_id": str(uuid4())}}
    assert "APPROVAL_REQUIRES_PURE_GRAPH" in {
        issue.code for issue in compile_workflow(graph).issues
    }


@pytest.mark.anyio
async def test_owned_api_detail_decision_and_invalid_assignment(prepared):
    from httpx import ASGITransport, AsyncClient

    from app.api.dependencies import get_database_resource
    from app.core.tokens import AccessTokens
    from app.main import create_app

    database, owner, _, approval_id, workflow_id, data = prepared
    secret = SecretStr("approval-test-signing-key-at-least-32-bytes")
    application = create_app(Settings(jwt_secret_key=secret))

    async def resource():
        return database

    application.dependency_overrides[get_database_resource] = resource
    tokens = AccessTokens(
        secret=secret, issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {tokens.issue(owner)}"},
    ) as client:
        listed = await client.get("/api/v1/approvals")
        proposal = await client.post(
            f"/api/v1/workflows/{workflow_id}/edit-proposal",
            json={"base_version_id": str(data.workflow_version_id), "prompt": "Rename the review"},
        )
        assert proposal.status_code == 422
        assert proposal.json()["error"]["code"] == "APPROVAL_PROPOSAL_UNAVAILABLE"
        assert listed.status_code == 200 and listed.json()["total"] == 1
        detail = await client.get(f"/api/v1/approvals/{approval_id}")
        assert detail.status_code == 200 and detail.json()["input"] == {"CaseKey": {"ID": 7}}
        assert detail.headers["cache-control"] == "no-store"
        invalid = await client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approved", "assigned_to": str(uuid4())},
        )
        assert invalid.status_code == 422
        decision = await client.post(
            f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approved"}
        )
        assert decision.status_code == 200 and decision.json()["status"] == "approved"
        conflict = await client.post(
            f"/api/v1/approvals/{approval_id}/decision", json={"decision": "rejected"}
        )
        assert conflict.status_code == 409


def test_empty_approval_migration_round_trip_and_metadata(migration_environment):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.infrastructure.database.base import Base

    connection, config = migration_environment
    command.upgrade(config, "head")
    context = MigrationContext.configure(connection, opts={"include_schemas": False})
    assert compare_metadata(context, Base.metadata) == []
    command.downgrade(config, "0013")
    command.upgrade(config, "head")
    assert (
        connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0014"
    )
