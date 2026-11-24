"""Queued API commands, durable dispatch, owner boundaries and recovery scheduling."""

import base64
import json
import os
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
from threading import Barrier, Event
from time import monotonic, sleep
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from opentelemetry import context, trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import event, func, select
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import (
    NodeRun,
    RunClaim,
    RunCommand,
    WorkflowDispatch,
    WorkflowRun,
)
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.executions import runner, worker_runner
from app.modules.executions.dispatch import schedule_recovery
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.schemas import RunCreateRequest, RunListParams
from app.modules.executions.service import ExecutionService
from app.modules.executions.state import RunStatus
from app.modules.executions.worker_state import WorkerState
from app.modules.outbox.dispatcher import OutboxDispatcher
from app.modules.outbox.models import OutboxMessage
from app.modules.workflows.repository import WorkflowRepository
from app.workers.celery_app import create_celery, publish_workflow
from app.workers.workflow_tasks import consume_workflow

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "isolated-background-test-key-at-least-32-bytes"
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "select",
            "type": "transform",
            "config": {"operation": "pick_fields", "fields": ["CustomerID"]},
        },
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "a", "source": "start", "target": "select"},
        {"id": "b", "source": "select", "target": "end"},
    ],
}


@pytest.fixture
def prepared(repository_database: Database, test_database_url: SecretStr):
    settings = Settings(
        database_url=test_database_url,
        redis_url=SecretStr("redis://127.0.0.1:1/15"),
        background_execution_enabled=True,
        jwt_secret_key=SecretStr(KEY),
        worker_redelivery_seconds=5,
    )
    with repository_database.unit_of_work() as session:
        owner = UserRepository(session).add(
            email="background@example.com", display_name="Owner", password_hash="fixture"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=owner.id, name="Background")
        version = workflows.append_version(
            workflow_id=workflow.id, owner_id=owner.id, expected_version=0, definition=GRAPH
        )
        owner_id, workflow_id, version_id = owner.id, workflow.id, version.id
    application = create_app(settings)

    async def database() -> Database:
        return repository_database

    application.dependency_overrides[get_database_resource] = database
    token = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    ).issue(owner_id)
    return application, settings, owner_id, workflow_id, version_id, token


def queued(database: Database, prepared, *, data=None, budget=2):
    _, settings, owner, workflow, version, _ = prepared
    return ExecutionService(database, settings).create_and_execute(
        workflow_id=workflow,
        owner_id=owner,
        data=RunCreateRequest(
            workflow_version_id=version,
            input={"CustomerID": 42, "CaseKey": {"ID": 7}} if data is None else data,
            max_attempts=budget,
        ),
        idempotency_key=str(uuid4()),
    )


def due(database: Database, run_id: UUID) -> None:
    with database.unit_of_work() as session:
        delivery = session.get(WorkflowDispatch, run_id)
        assert delivery is not None
        delivery.next_dispatch_at -= timedelta(hours=1)


def test_background_trace_context_survives_storage_and_reaches_worker(
    repository_database: Database, prepared, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = SpanContext(trace_id=123, span_id=456, is_remote=False, trace_flags=TraceFlags(1))
    token = context.attach(set_span_in_context(NonRecordingSpan(original)))
    try:
        run = queued(repository_database, prepared)
    finally:
        context.detach(token)
    with repository_database.session() as session:
        saved = session.get(WorkflowDispatch, run.id)
        assert saved is not None and saved.traceparent is not None
    seen = []
    messages = []
    original_run = worker_runner.PureWorkerRunner.run

    def record_worker(self, *args, **kwargs):
        seen.append(trace.get_current_span().get_span_context().trace_id)
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(worker_runner.PureWorkerRunner, "run", record_worker)

    def publish(message_id):
        seen.append(trace.get_current_span().get_span_context().trace_id)
        messages.append(message_id)

    result = OutboxDispatcher(
        repository_database, lambda _: None, publish_workflow=publish
    ).dispatch_once()
    assert result.published == 1 and seen == [123]
    consume_workflow(repository_database, str(messages[0]))
    assert seen == [123, 123]
    with repository_database.session() as session:
        completed = session.get(WorkflowRun, run.id)
        assert completed is not None and completed.status == RunStatus.SUCCEEDED
    assert not trace.get_current_span().get_span_context().is_valid


async def test_api_returns_202_without_node_or_broker_calls_and_replay_preserves_mode(
    repository_database: Database,
    prepared,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, settings, owner, workflow, version, token = prepared

    def forbidden(*args, **kwargs):
        pytest.fail("Queued API executed a node or contacted the broker")

    monkeypatch.setattr(runner.WorkflowRunner, "run", forbidden)
    from app.workers import celery_app

    monkeypatch.setattr(celery_app, "create_celery", forbidden)
    body = {"workflow_version_id": str(version), "input": {"CustomerID": 42}, "max_attempts": 2}
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "queued-command"},
    ) as client:
        response = await client.post(f"/api/v1/workflows/{workflow}/runs", json=body)
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued" and data["execution_mode"] == "background"
        assert data["node_runs"] == [] and data["output"] is None
        assert response.headers["Location"] == f"/api/v1/runs/{data['id']}"
        assert response.headers["Cache-Control"] == "no-store"
        application.state.settings = settings.model_copy(
            update={"background_execution_enabled": False}
        )
        replay = await client.post(f"/api/v1/workflows/{workflow}/runs", json=body)
        assert replay.status_code == 202 and replay.json() == data
        conflict = await client.post(
            f"/api/v1/workflows/{workflow}/runs", json={**body, "input": {}}
        )
        assert conflict.status_code == 409
        listed = await client.get("/api/v1/runs")
        assert listed.json()["items"][0]["execution_mode"] == "background"
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowRun)) == 1
        assert session.scalar(select(func.count()).select_from(WorkflowDispatch)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
        assert session.scalar(select(func.count()).select_from(RunCommand)) == 1
        assert session.scalar(select(func.count()).select_from(NodeRun)) == 0
        saved = session.get(WorkflowRun, UUID(data["id"]))
        assert saved is not None and saved.event_sequence == 1


async def test_receipt_failure_rolls_back_run_events_dispatch_and_outbox(
    repository_database: Database,
    prepared,
) -> None:
    application, _, _, workflow, version, token = prepared

    def fail(*args):
        raise OperationalError("synthetic", {}, Exception())

    event.listen(RunCommand, "before_insert", fail)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application),
            base_url="https://test",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "rollback"},
        ) as client:
            response = await client.post(
                f"/api/v1/workflows/{workflow}/runs",
                json={"workflow_version_id": str(version), "input": {}},
            )
        assert response.status_code == 503
    finally:
        event.remove(RunCommand, "before_insert", fail)
    with repository_database.session() as session:
        for model in (WorkflowRun, WorkflowDispatch, OutboxMessage, RunCommand):
            assert session.scalar(select(func.count()).select_from(model)) == 0


async def test_cancelled_queued_run_stays_cancelled_and_retry_is_queued(
    repository_database: Database,
    prepared,
) -> None:
    application, _, owner, _, _, token = prepared
    original = queued(repository_database, prepared)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        cancelled = await client.post(f"/api/v1/runs/{original.id}/cancel")
        assert cancelled.status_code == 200
        with repository_database.session() as session:
            message = session.scalar(select(OutboxMessage.id))
        consume_workflow(repository_database, str(message))
        retained = await client.get(f"/api/v1/runs/{original.id}")
        assert retained.json() == cancelled.json() and retained.json()["node_runs"] == []
        retried = await client.post(
            f"/api/v1/runs/{original.id}/retry", json={}, headers={"Idempotency-Key": "retry"}
        )
        assert retried.status_code == 202
        assert retried.json()["parent_run_id"] == str(original.id)
        assert retried.json()["status"] == "queued"
        assert retried.json()["workflow_version_id"] == str(original.workflow_version_id)
        assert retried.json()["input"] == original.input
        replay = await client.post(
            f"/api/v1/runs/{original.id}/retry", json={}, headers={"Idempotency-Key": "retry"}
        )
        assert replay.json() == retried.json()
    assert (
        ExecutionService(repository_database).get(run_id=original.id, owner_id=owner).status
        == RunStatus.CANCELLED
    )


async def test_other_user_cannot_queue_read_or_cancel_owned_work(
    repository_database: Database,
    prepared,
) -> None:
    application, _, _, workflow, version, _ = prepared
    original = queued(repository_database, prepared)
    with repository_database.unit_of_work() as session:
        other = (
            UserRepository(session)
            .add(
                email="other-background@example.com", display_name="Other", password_hash="fixture"
            )
            .id
        )
    token = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    ).issue(other)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        created = await client.post(
            f"/api/v1/workflows/{workflow}/runs",
            json={"workflow_version_id": str(version), "input": {}},
        )
        assert created.status_code == 404
        assert (await client.get(f"/api/v1/runs/{original.id}")).status_code == 404
        assert (await client.post(f"/api/v1/runs/{original.id}/cancel")).status_code == 404
        assert (await client.get("/api/v1/runs")).json()["total"] == 0


async def test_groq_graph_keeps_synchronous_mode_and_is_never_enqueued(
    repository_database: Database,
    prepared,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, _, owner, workflow, _, token = prepared
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "answer",
                "type": "groq",
                "config": {"instruction": "Reply", "input_field": "message"},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "answer"},
            {"id": "b", "source": "answer", "target": "end"},
        ],
    }
    with repository_database.unit_of_work() as session:
        version = (
            WorkflowRepository(session)
            .append_version(
                workflow_id=workflow, owner_id=owner, expected_version=1, definition=graph
            )
            .id
        )
    calls = []

    def complete(settings, prompt):
        calls.append(prompt)
        return {"model": "test-only-stub", "content": "Synthetic reply"}

    monkeypatch.setattr(runner, "complete", complete)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            f"/api/v1/workflows/{workflow}/runs",
            json={"workflow_version_id": str(version), "input": {"message": "Synthetic question"}},
        )
    assert response.status_code == 201
    assert (
        response.json()["status"] == "succeeded"
        and response.json()["execution_mode"] == "synchronous"
    )
    assert len(calls) == 1
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowDispatch)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_broker_failure_retains_work_and_successful_delivery_uses_stored_owner(
    repository_database: Database,
    prepared,
) -> None:
    original = queued(repository_database, prepared)
    owner = prepared[2]

    def unavailable(_):
        raise OSError("synthetic broker outage")

    failed = OutboxDispatcher(
        repository_database, unavailable, publish_workflow=unavailable
    ).dispatch_once()
    assert failed.failed == 1
    assert (
        ExecutionService(repository_database).get(run_id=original.id, owner_id=owner).status
        == RunStatus.QUEUED
    )
    completed = OutboxDispatcher(
        repository_database,
        unavailable,
        publish_workflow=lambda message: consume_workflow(repository_database, str(message)),
    ).dispatch_once()
    assert completed.published == 1
    result = ExecutionService(repository_database).get(run_id=original.id, owner_id=owner)
    assert result.status == RunStatus.SUCCEEDED and result.output == {"CustomerID": 42}
    assert result.node_runs[0].input == {"CustomerID": 42, "CaseKey": {"ID": 7}}
    assert (
        ExecutionService(repository_database)
        .list(owner_id=owner, params=RunListParams())
        .items[0]
        .execution_mode
        == "background"
    )


def test_json_parser_workflow_runs_through_background_dispatch(
    repository_database: Database, prepared
) -> None:
    _, settings, owner, workflow, _, _ = prepared
    graph = {
        **GRAPH,
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {"id": "select", "type": "json_parser", "config": {"input_field": "raw"}},
            {"id": "end", "type": "end", "config": {}},
        ],
    }
    with repository_database.unit_of_work() as session:
        version = (
            WorkflowRepository(session)
            .append_version(
                workflow_id=workflow, owner_id=owner, expected_version=1, definition=graph
            )
            .id
        )
    run = ExecutionService(repository_database, settings).create_and_execute(
        workflow_id=workflow,
        owner_id=owner,
        data=RunCreateRequest(workflow_version_id=version, input={"raw": '{"CustomerID":42}'}),
    )
    assert run.status == RunStatus.QUEUED and run.execution_mode == "background"
    dispatched = OutboxDispatcher(
        repository_database,
        lambda _: None,
        publish_workflow=lambda message: consume_workflow(repository_database, str(message)),
    ).dispatch_once()
    assert dispatched.published == 1
    result = ExecutionService(repository_database).get(run_id=run.id, owner_id=owner)
    assert result.status == RunStatus.SUCCEEDED and result.output == {"CustomerID": 42}


@pytest.mark.parametrize(
    ("node_type", "config", "provider_content", "expected"),
    [
        (
            "classify",
            {"input_field": "text", "labels": ["yes", "no"]},
            '{"label":"yes"}',
            {"model": "test", "label": "yes"},
        ),
        (
            "extract",
            {"input_field": "text", "fields": ["CustomerID"]},
            '{"CustomerID":"42"}',
            {"model": "test", "fields": {"CustomerID": "42"}},
        ),
    ],
)
async def test_structured_groq_nodes_run_synchronously_once(
    repository_database: Database,
    prepared,
    monkeypatch: pytest.MonkeyPatch,
    node_type,
    config,
    provider_content,
    expected,
) -> None:
    application, _, owner, workflow, _, token = prepared
    graph = {
        **GRAPH,
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {"id": "select", "type": node_type, "config": config},
            {"id": "end", "type": "end", "config": {}},
        ],
    }
    with repository_database.unit_of_work() as session:
        version = (
            WorkflowRepository(session)
            .append_version(
                workflow_id=workflow, owner_id=owner, expected_version=1, definition=graph
            )
            .id
        )
    calls = []

    def complete(settings, prompt, *, json_mode=False):
        calls.append(json_mode)
        return {"model": "test", "content": provider_content}

    monkeypatch.setattr(runner, "complete", complete)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            f"/api/v1/workflows/{workflow}/runs",
            json={
                "workflow_version_id": str(version),
                "input": {"text": "synthetic"},
                "max_attempts": 3,
            },
        )
    assert response.status_code == 201
    assert response.json()["status"] == "succeeded"
    assert response.json()["execution_mode"] == "synchronous"
    assert response.json()["output"] == expected
    assert calls == [True]


async def test_invalid_classification_output_fails_without_automatic_retry(
    repository_database: Database,
    prepared,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    application, _, owner, workflow, _, token = prepared
    graph = {
        **GRAPH,
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "select",
                "type": "classify",
                "config": {"input_field": "text", "labels": ["yes", "no"]},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
    }
    with repository_database.unit_of_work() as session:
        version = (
            WorkflowRepository(session)
            .append_version(
                workflow_id=workflow, owner_id=owner, expected_version=1, definition=graph
            )
            .id
        )
    calls = []

    def complete(settings, prompt, *, json_mode=False):
        calls.append(json_mode)
        return {"model": "test", "content": '{"label":"unexpected"}'}

    monkeypatch.setattr(runner, "complete", complete)
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            f"/api/v1/workflows/{workflow}/runs",
            json={
                "workflow_version_id": str(version),
                "input": {"text": "synthetic"},
                "max_attempts": 3,
            },
        )
    assert response.status_code == 201 and response.json()["status"] == "failed"
    assert response.json()["node_runs"][1]["error_code"] == "EXECUTION_FAILED"
    assert calls == [True]


def test_parallel_recovery_scans_create_only_one_new_pending_intent(
    repository_database: Database,
    prepared,
) -> None:
    original = queued(repository_database, prepared)
    OutboxDispatcher(
        repository_database, lambda _: None, publish_workflow=lambda _: None
    ).dispatch_once()
    due(repository_database, original.id)
    gate = Barrier(2)

    def scan():
        gate.wait(5)
        return schedule_recovery(repository_database, redelivery_seconds=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(scan), pool.submit(scan)
        assert sorted([a.result(10), b.result(10)]) == [0, 1]
    assert schedule_recovery(repository_database, redelivery_seconds=5) == 0
    with repository_database.session() as session:
        rows = session.scalars(select(OutboxMessage).order_by(OutboxMessage.created_at)).all()
        assert len(rows) == 2 and rows[0].published_at is not None and rows[1].published_at is None
        delivery = session.get(WorkflowDispatch, original.id)
        assert delivery is not None and delivery.dispatch_count == 2


def test_live_lease_is_not_rescheduled_but_expired_lease_is(
    repository_database: Database,
    prepared,
) -> None:
    original = queued(repository_database, prepared)
    OutboxDispatcher(
        repository_database, lambda _: None, publish_workflow=lambda _: None
    ).dispatch_once()
    with repository_database.unit_of_work() as session:
        from app.modules.claims.repository import ClaimRepository

        claim = ClaimRepository(session).acquire(original.id)
        assert claim is not None
    WorkerState(repository_database, owner_id=prepared[2], claim=claim).transition_run(
        expected_revision=0, target=RunStatus.RUNNING
    )
    due(repository_database, original.id)
    assert schedule_recovery(repository_database, redelivery_seconds=5) == 0
    with repository_database.unit_of_work() as session:
        slot = session.get(RunClaim, original.id)
        assert slot is not None and slot.lease_until is not None
        slot.lease_until -= timedelta(hours=1)
    assert schedule_recovery(repository_database, redelivery_seconds=5) == 1


def test_recovery_scan_excludes_terminal_and_synchronous_runs(
    repository_database: Database,
    prepared,
) -> None:
    original = queued(repository_database, prepared)
    OutboxDispatcher(
        repository_database, lambda _: None, publish_workflow=lambda _: None
    ).dispatch_once()
    ExecutionService(repository_database).cancel(run_id=original.id, owner_id=prepared[2])
    due(repository_database, original.id)
    with repository_database.unit_of_work() as session:
        for running in (False, True):
            row = ExecutionRepository(session).create_run(
                workflow_id=prepared[3], version_id=prepared[4], owner_id=prepared[2], input_json={}
            )
            if running:
                ExecutionRepository(session).transition_run(
                    run_id=row.id,
                    owner_id=prepared[2],
                    expected_revision=0,
                    target=RunStatus.RUNNING,
                )
    assert schedule_recovery(repository_database, redelivery_seconds=5) == 0


def test_worker_heartbeat_keeps_long_pure_computation_leased(
    repository_database: Database,
    prepared,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = queued(repository_database, prepared)
    owner = prepared[2]
    entered, release = Event(), Event()
    execute = worker_runner.execute_node

    def paused(node, data, **kwargs):
        if node.id == "select":
            entered.set()
            assert release.wait(12)
        return execute(node, data, **kwargs)

    monkeypatch.setattr(worker_runner, "execute_node", paused)
    with repository_database.session() as session:
        message = session.scalar(select(OutboxMessage.id))
    OutboxDispatcher(
        repository_database, lambda _: None, publish_workflow=lambda _: None
    ).dispatch_once()
    due(repository_database, original.id)
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(consume_workflow, repository_database, str(message), lease_seconds=5)
        try:
            assert entered.wait(10)
            sleep(6)  # Longer than the original lease, with the computation still paused.
            with repository_database.session() as session:
                slot = session.get(RunClaim, original.id)
                now = session.scalar(select(func.clock_timestamp()))
                assert now is not None
                assert slot is not None and slot.lease_until is not None and slot.lease_until > now
            assert schedule_recovery(repository_database, redelivery_seconds=5) == 0
        finally:
            release.set()
        active.result(10)
    assert (
        ExecutionService(repository_database).get(run_id=original.id, owner_id=owner).status
        == RunStatus.SUCCEEDED
    )


@pytest.mark.parametrize("identifier", ["private-invalid-message", str(uuid4())])
def test_unknown_delivery_cannot_execute_arbitrary_runs_or_log_supplied_values(
    repository_database: Database,
    prepared,
    identifier,
    caplog,
) -> None:
    original = queued(repository_database, prepared)
    consume_workflow(repository_database, identifier)
    assert identifier not in caplog.text
    assert (
        ExecutionService(repository_database).get(run_id=original.id, owner_id=prepared[2]).status
        == RunStatus.QUEUED
    )


@pytest.fixture
def real_transport(repository_database: Database, prepared, tmp_path):
    raw = os.environ.get("TEST_REDIS_URL", "")
    parsed = urlsplit(raw)
    if not (
        parsed.scheme == "redis"
        and parsed.hostname in {"localhost", "127.0.0.1"}
        and parsed.port == 16380
        and parsed.path == "/15"
        and not parsed.query
        and not parsed.fragment
        and parsed.username is None
        and parsed.password is None
    ):
        pytest.fail(
            "TEST_REDIS_URL must select the disposable local Redis test service", pytrace=False
        )
    queue = f"agentflow.test.{uuid4().hex}"
    settings = Settings(redis_url=SecretStr(raw), worker_queue=queue)
    app = create_celery(settings)
    schema = repository_database.engine.get_execution_options()["schema_translate_map"][None]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("AGENTFLOW_", "CELERY_")) and key.upper() != "GROQ_API_KEY"
    }
    env.update(
        AGENTFLOW_DATABASE_URL=prepared[1].database_url.get_secret_value(),
        AGENTFLOW_REDIS_URL=raw,
        AGENTFLOW_WORKER_QUEUE=queue,
        AGENTFLOW_ENVIRONMENT="testing",
        AGENTFLOW_WORKER_LEASE_SECONDS="5",
        AGENTFLOW_WORKER_REDELIVERY_SECONDS="5",
        WORKFLOW_TEST_SCHEMA=schema,
        PYTHONUNBUFFERED="1",
    )
    bootstrap = """
import os, signal, sys
from pydantic import SecretStr
from app.core.config import Settings
Settings.model_config['env_file'] = None
from app.infrastructure.database.session import Database
db = Database(SecretStr(os.environ['TEST_DATABASE_URL']))
db.engine = db.engine.execution_options(
    schema_translate_map={None: os.environ['WORKFLOW_TEST_SCHEMA']}
)
db.session_factory.configure(bind=db.engine)
"""

    @contextmanager
    def launch(kind="worker", *, crash=False, fail_once=False):
        script = bootstrap
        if kind == "worker":
            if fail_once:
                script += """
from app.modules.executions import worker_runner
execute = worker_runner.execute_node
failed_once = False
def transient(node, data, **kwargs):
    global failed_once
    if node.id == 'select' and not failed_once:
        failed_once = True
        raise RuntimeError('Synthetic transient failure')
    return execute(node, data, **kwargs)
worker_runner.execute_node = transient
"""
            if crash:
                script += """
from app.modules.executions import worker_runner
execute = worker_runner.execute_node
def interrupted(node, data, **kwargs):
    if node.id == 'select':
        os.kill(os.getpid(), signal.SIGKILL)
    return execute(node, data, **kwargs)
worker_runner.execute_node = interrupted
"""
            script += (
                "from app.workers.__main__ import main; "
                "raise SystemExit(main(workflow_database=db))"
            )
        else:
            script += (
                "from app.workers.outbox import main; "
                "sys.argv = ['outbox', 'run', '--interval', '0.1']; "
                "raise SystemExit(main(workflow_database=db))"
            )
        path = tmp_path / f"{kind}-{uuid4().hex}.log"
        with path.open("w+") as log:
            process = subprocess.Popen(
                [sys.executable, "-c", script], env=env, stdout=log, stderr=subprocess.STDOUT
            )
            try:
                if kind == "worker":
                    deadline = monotonic() + 15
                    while monotonic() < deadline:
                        assert process.poll() is None, "Worker exited before readiness"
                        if " ready." in path.read_text():
                            break
                        sleep(0.1)
                    else:
                        pytest.fail("Worker did not become ready")
                yield process, path
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(5)
                        pytest.fail("Background process did not stop gracefully")
                if not crash:
                    assert process.returncode in (0, -signal.SIGTERM)

    try:
        yield app, queue, raw, launch
    finally:
        app.close()
        redis = Redis.from_url(raw)
        try:
            redis.delete(
                queue,
                *(queue + "\x06\x16" + str(priority) for priority in (3, 6, 9)),
                f"_kombu.binding.{queue}",
            )
        finally:
            redis.close()


def wait_completed(database: Database, run_id, owner, *, timeout=20):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = ExecutionService(database).get(run_id=run_id, owner_id=owner)
        if result.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return result
        sleep(0.1)
    pytest.fail("Background run did not reach a terminal state")


@pytest.mark.redis_integration
def test_approval_releases_real_worker_and_resumes_after_process_restart(
    repository_database: Database,
    prepared,
    real_transport,
) -> None:
    from app.modules.approvals.schemas import ApprovalDecision
    from app.modules.approvals.service import ApprovalService

    _, _, owner, workflow, _, _ = prepared
    _, _, _, launch = real_transport
    graph = {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {"id": "review", "type": "approval", "config": {"title": "Review"}},
            {"id": "yes", "type": "end", "config": {}},
            {"id": "no", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "review"},
            {"id": "b", "source": "review", "target": "yes", "source_handle": "approved"},
            {"id": "c", "source": "review", "target": "no", "source_handle": "rejected"},
        ],
    }
    with repository_database.unit_of_work() as session:
        version = (
            WorkflowRepository(session)
            .append_version(
                workflow_id=workflow,
                owner_id=owner,
                expected_version=1,
                definition=graph,
            )
            .id
        )
    approval_setup = list(prepared)
    approval_setup[4] = version
    with launch(), launch("dispatcher"):
        original = queued(repository_database, approval_setup)
        deadline = monotonic() + 20
        while monotonic() < deadline:
            waiting = ExecutionService(repository_database).get(run_id=original.id, owner_id=owner)
            if waiting.status == RunStatus.WAITING_APPROVAL:
                break
            sleep(0.1)
        else:
            pytest.fail("Real worker did not persist the approval pause")
        # The same solo worker can execute another immutable version while review waits.
        other = queued(repository_database, prepared)
        assert wait_completed(repository_database, other.id, owner).status == RunStatus.SUCCEEDED
    # Both original processes are stopped before the human decision creates resume intent.
    approvals = ApprovalService(repository_database)
    request = approvals.list(owner, run_id=original.id).items[0]
    approvals.decide(owner, request.id, ApprovalDecision(decision="approved"))
    with launch(), launch("dispatcher"):
        completed = wait_completed(repository_database, original.id, owner)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"decision": "approved"}
    assert completed.node_runs[0] == waiting.node_runs[0]


@pytest.mark.redis_integration
async def test_queued_api_to_real_broker_worker_and_duplicate_delivery(
    repository_database: Database,
    prepared,
    real_transport,
) -> None:
    application, _, owner, workflow, version, token = prepared
    app, queue, raw, launch = real_transport
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        response = await client.post(
            f"/api/v1/workflows/{workflow}/runs",
            json={"workflow_version_id": str(version), "input": {"CustomerID": 42, "CaseKey": 7}},
        )
        assert response.status_code == 202
        run_id = UUID(response.json()["id"])
        dispatcher = OutboxDispatcher(
            repository_database,
            lambda _: pytest.fail("Wrong task kind"),
            publish_workflow=lambda message: publish_workflow(app, queue, message),
        )
        assert dispatcher.dispatch_once().published == 1
        redis = Redis.from_url(raw)
        try:
            encoded = redis.lindex(queue, 0)
            assert encoded is not None
            envelope = json.loads(encoded)
            args, kwargs, _ = json.loads(base64.b64decode(envelope["body"]))
            assert len(args) == 1 and kwargs == {}
            message_id = UUID(args[0])
            assert "CustomerID" not in json.dumps(envelope) and "CaseKey" not in json.dumps(
                envelope
            )
        finally:
            redis.close()
        with launch() as (_, log):
            completed = wait_completed(repository_database, run_id, owner)
            assert completed.status == RunStatus.SUCCEEDED and completed.output == {
                "CustomerID": 42
            }
            publish_workflow(app, queue, message_id)
            deadline = monotonic() + 10
            while monotonic() < deadline:
                if "Workflow delivery deferred or already handled" in log.read_text():
                    break
                sleep(0.1)
            else:
                pytest.fail("Duplicate delivery was not consumed")
            assert (
                ExecutionService(repository_database).get(run_id=run_id, owner_id=owner)
                == completed
            )
            assert "CustomerID" not in log.read_text() and "CaseKey" not in log.read_text()
        fetched = await client.get(response.headers["Location"])
        assert fetched.status_code == 200 and fetched.json()["status"] == "succeeded"


@pytest.mark.redis_integration
def test_real_worker_kill_and_dispatcher_loop_recover_after_natural_lease_expiry(
    repository_database: Database,
    prepared,
    real_transport,
) -> None:
    app, queue, _, launch = real_transport
    original = queued(repository_database, prepared)
    owner = prepared[2]
    with launch(crash=True) as (process, _):
        dispatcher = OutboxDispatcher(
            repository_database,
            lambda _: pytest.fail("Wrong task kind"),
            publish_workflow=lambda message: publish_workflow(app, queue, message),
        )
        assert dispatcher.dispatch_once().published == 1
        assert process.wait(15) == -signal.SIGKILL
    interrupted = ExecutionService(repository_database).get(run_id=original.id, owner_id=owner)
    assert interrupted.status == RunStatus.RUNNING
    assert [(row.node_id, row.status.value) for row in interrupted.node_runs] == [
        ("start", "succeeded"),
        ("select", "running"),
    ]
    # No clock/lease edits: the actual dispatcher loop discovers the expired lease
    # and schedules a new immutable intent after the killed worker's heartbeat stops.
    with launch(), launch("dispatcher"):
        completed = wait_completed(repository_database, original.id, owner, timeout=25)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"CustomerID": 42}
    assert completed.node_runs[0] == interrupted.node_runs[0]
    selected = [row for row in completed.node_runs if row.node_id == "select"]
    assert [(row.attempt_number, row.status.value) for row in selected] == [
        (1, "failed"),
        (2, "succeeded"),
    ]
    with repository_database.session() as session:
        slot = session.get(RunClaim, original.id)
        assert slot is not None and slot.generation == 3
        rows = session.scalars(select(OutboxMessage).order_by(OutboxMessage.created_at)).all()
        assert len(rows) == 3 and all(row.published_at is not None for row in rows)
        delivery = session.get(WorkflowDispatch, original.id)
        assert delivery is not None and delivery.dispatch_count == 3


@pytest.mark.redis_integration
def test_scheduled_retry_survives_worker_restart_without_blocking_other_work(
    repository_database: Database,
    prepared,
    real_transport,
) -> None:
    app, queue, _, launch = real_transport
    original = queued(repository_database, prepared)
    owner = prepared[2]
    dispatcher = OutboxDispatcher(
        repository_database,
        lambda _: pytest.fail("Wrong task kind"),
        publish_workflow=lambda message: publish_workflow(app, queue, message),
    )
    with launch(fail_once=True):
        assert dispatcher.dispatch_once().published == 1
        deadline = monotonic() + 10
        while monotonic() < deadline:
            waiting = ExecutionService(repository_database).get(run_id=original.id, owner_id=owner)
            if waiting.next_retry_at is not None:
                break
            sleep(0.05)
        else:
            pytest.fail("Worker did not persist its retry deadline")
        assert waiting.retry_node_id == "select" and waiting.next_retry_attempt == 2
        # The solo worker is free to execute another run while the first waits.
        other = queued(repository_database, prepared)
        assert dispatcher.dispatch_once().published == 1
        assert wait_completed(repository_database, other.id, owner).status == RunStatus.SUCCEEDED
        retained = ExecutionService(repository_database).get(run_id=original.id, owner_id=owner)
        assert retained == waiting
    with launch(), launch("dispatcher"):
        completed = wait_completed(repository_database, original.id, owner)
    assert completed.status == RunStatus.SUCCEEDED and completed.output == {"CustomerID": 42}
    assert completed.node_runs[0] == waiting.node_runs[0]
    assert completed.next_retry_at is None
    retry = completed.node_runs[1].retry
    assert retry is not None and retry.due_at == waiting.next_retry_at
    assert retry.resumed_at is not None and retry.resumed_at >= retry.due_at
    assert [
        (row.attempt_number, row.status.value)
        for row in completed.node_runs
        if row.node_id == "select"
    ] == [(1, "failed"), (2, "succeeded")]
