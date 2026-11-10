"""Real saved/candidate graph validation is private, snapshot-bound and read-only."""

from collections.abc import AsyncIterator
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import User, Workflow, WorkflowVersion
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.workflows.repository import WorkflowRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-workflow-validation-key-at-least-32-bytes"
DEFINITION: dict[str, Any] = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "finish", "type": "end", "config": {}},
    ],
    "edges": [{"id": "e1", "source": "start", "target": "finish"}],
}


@pytest.fixture
def owners(repository_database: Database) -> dict[str, UUID]:
    with repository_database.unit_of_work() as session:
        repository = UserRepository(session)
        return {
            label: repository.add(
                email=f"{label}@example.com",
                password_hash="not-a-login-fixture",
                display_name=label,
            ).id
            for label in ("a", "b")
        }


def authorization(owner_id: UUID) -> dict[str, str]:
    tokens = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )
    return {"Authorization": f"Bearer {tokens.issue(owner_id)}"}


@pytest.fixture
async def client(
    repository_database: Database, owners: dict[str, UUID]
) -> AsyncIterator[AsyncClient]:
    application = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return repository_database

    application.dependency_overrides[get_database_resource] = resource
    async with AsyncClient(
        transport=ASGITransport(app=application),
        base_url="https://test",
        headers=authorization(owners["a"]),
    ) as client:
        yield client


def stored_state(database: Database, workflow_id: UUID) -> tuple:
    """Track both metadata timestamps and complete immutable history across validation."""
    with database.session() as session:
        workflow = session.get(Workflow, workflow_id)
        assert workflow is not None
        versions = session.scalars(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version_number)
        ).all()
        return (
            workflow.name,
            workflow.description,
            workflow.status,
            workflow.current_version_id,
            workflow.created_at,
            workflow.updated_at,
            [(row.id, row.version_number, deepcopy(row.definition_json)) for row in versions],
        )


async def test_versionless_current_returns_a_read_only_missing_definition_report(
    client: AsyncClient, repository_database: Database
) -> None:
    created = await client.post("/api/v1/workflows", json={"name": "Unfinished"})
    assert created.status_code == 201
    workflow_id = UUID(created.json()["id"])
    before = stored_state(repository_database, workflow_id)
    response = await client.post(created.headers["location"] + "/validate", json={})
    assert response.status_code == 200
    report = response.json()
    assert report["workflow_id"] == str(workflow_id)
    assert report["workflow_version_id"] is None and report["source"] == "saved"
    assert report["valid"] is False and report["execution_ready"] is False
    assert report["plan"] is None and report["issues_truncated"] is False
    assert [issue["code"] for issue in report["issues"]] == ["NO_SAVED_DEFINITION"]
    assert response.headers["cache-control"] == "no-store"
    assert stored_state(repository_database, workflow_id) == before


async def test_valid_candidate_compiles_without_saving_and_returns_a_fresh_plan(
    client: AsyncClient, repository_database: Database
) -> None:
    created = await client.post("/api/v1/workflows", json={"name": "Candidate"})
    workflow_id = UUID(created.json()["id"])
    before = stored_state(repository_database, workflow_id)
    path = created.headers["location"] + "/validate"
    response = await client.post(path, json={"definition": DEFINITION})
    assert response.status_code == 200
    report = response.json()
    assert report["workflow_id"] == str(workflow_id)
    assert report["source"] == "candidate" and report["workflow_version_id"] is None
    assert report["valid"] is True and report["execution_ready"] is True
    assert report["issues"] == [] and report["issues_truncated"] is False
    expected_plan = {
        "entry_node_id": "start",
        "node_count": 2,
        "edge_count": 1,
        "topological_order": ["start", "finish"],
        "terminal_node_ids": ["finish"],
    }
    assert report["plan"] == expected_plan
    report["plan"]["topological_order"].append("injected")
    repeated = await client.post(path, json={"definition": DEFINITION})
    assert repeated.json()["plan"] == expected_plan
    assert repeated.headers["cache-control"] == "no-store"
    assert stored_state(repository_database, workflow_id) == before


@pytest.mark.parametrize("node_type", ["llm", "calculator"])
async def test_semantically_invalid_candidate_returns_safe_issues_without_saving(
    client: AsyncClient,
    repository_database: Database,
    caplog: pytest.LogCaptureFixture,
    node_type: str,
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "Original", "definition": DEFINITION}
    )
    workflow_id = UUID(created.json()["id"])
    before = stored_state(repository_database, workflow_id)
    definition = deepcopy(DEFINITION)
    definition["nodes"][1] = {
        "id": "finish",
        "type": node_type,
        "config": {"password": "private-validation-config"},
    }
    response = await client.post(
        created.headers["location"] + "/validate", json={"definition": definition}
    )
    assert response.status_code == 200
    report = response.json()
    assert report["valid"] is False and report["execution_ready"] is False
    assert report["plan"] is None and report["issues"]
    assert all(set(issue) == {"code", "message", "path"} for issue in report["issues"])
    assert "private-validation-config" not in response.text + caplog.text
    assert "password" not in response.text + caplog.text
    assert stored_state(repository_database, workflow_id) == before


async def test_saved_current_and_historical_reports_bind_exact_immutable_versions(
    client: AsyncClient, repository_database: Database
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "History", "definition": DEFINITION}
    )
    first_id = created.json()["version"]["id"]
    location = created.headers["location"]
    saved = await client.patch(
        location,
        json={
            "expected_version": 1,
            "definition": {"schema_version": "1.0", "nodes": [], "edges": []},
        },
    )
    assert saved.status_code == 200  # Unfinished draft saves remain permitted.
    second_id = saved.json()["version"]["id"]
    before = stored_state(repository_database, UUID(saved.json()["id"]))
    current = await client.post(location + "/validate", json={})
    historical = await client.post(location + "/validate", json={"version_id": first_id})
    assert current.status_code == historical.status_code == 200
    assert current.json()["workflow_version_id"] == second_id
    assert current.json()["source"] == "saved" and current.json()["valid"] is False
    assert historical.json()["workflow_version_id"] == first_id
    assert historical.json()["source"] == "saved" and historical.json()["valid"] is True
    assert historical.json()["plan"]["topological_order"] == ["start", "finish"]
    assert stored_state(repository_database, UUID(saved.json()["id"])) == before


async def test_archived_workflow_still_supports_read_only_saved_and_candidate_validation(
    client: AsyncClient, repository_database: Database
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "Archived", "definition": DEFINITION}
    )
    location = created.headers["location"]
    assert (await client.delete(location)).status_code == 204
    workflow_id = UUID(created.json()["id"])
    before = stored_state(repository_database, workflow_id)
    for body in ({}, {"definition": DEFINITION}):
        response = await client.post(location + "/validate", json=body)
        assert response.status_code == 200 and response.json()["valid"] is True
    assert stored_state(repository_database, workflow_id) == before


@pytest.mark.parametrize("source", ["current", "historical", "candidate"])
async def test_missing_and_foreign_workflows_have_identical_404_before_graph_checks(
    client: AsyncClient, owners: dict[str, UUID], source: str
) -> None:
    created = await client.post(
        "/api/v1/workflows",
        headers=authorization(owners["b"]),
        json={"name": "private-other-workflow", "definition": DEFINITION},
    )
    body = {}
    if source == "historical":
        body = {"version_id": created.json()["version"]["id"]}
    elif source == "candidate":
        body = {"definition": {"schema_version": "1.0", "nodes": [], "edges": []}}
    denied = await client.post(created.headers["location"] + "/validate", json=body)
    missing = await client.post(f"/api/v1/workflows/{uuid4()}/validate", json=body)
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["error"] == missing.json()["error"]
    assert denied.json()["error"]["details"] is None
    assert "private-other-workflow" not in denied.text
    assert "issues" not in denied.json()
    allowed = await client.post(
        created.headers["location"] + "/validate",
        headers=authorization(owners["b"]),
        json={},
    )
    assert allowed.status_code == 200 and allowed.json()["valid"] is True


async def test_historical_selector_rejects_versions_of_sibling_or_foreign_workflows(
    client: AsyncClient, owners: dict[str, UUID]
) -> None:
    records = []
    for label in ("a", "a", "b"):
        created = await client.post(
            "/api/v1/workflows",
            headers=authorization(owners[label]),
            json={"name": "private-version-owner", "definition": DEFINITION},
        )
        records.append(created.json())
    own, sibling, foreign = records
    errors = []
    for version_id in (sibling["version"]["id"], foreign["version"]["id"], str(uuid4())):
        response = await client.post(
            f"/api/v1/workflows/{own['id']}/validate", json={"version_id": version_id}
        )
        assert response.status_code == 404 and "private-version-owner" not in response.text
        errors.append(response.json()["error"])
    assert all(error == errors[0] for error in errors)


async def test_valid_token_for_inactive_user_cannot_validate(
    client: AsyncClient, repository_database: Database, owners: dict[str, UUID]
) -> None:
    created = await client.post("/api/v1/workflows", json={"name": "Active before"})
    with repository_database.unit_of_work() as session:
        user = session.get(User, owners["a"])
        assert user is not None
        user.is_active = False
    response = await client.post(created.headers["location"] + "/validate", json={})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_storage_failure_is_safe_503_and_read_only_validation_recovers(
    client: AsyncClient,
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "Resilient", "definition": DEFINITION}
    )
    workflow_id = UUID(created.json()["id"])
    before = stored_state(repository_database, workflow_id)

    def fail_read(self, **kwargs):
        raise OperationalError("private-validation-driver", {}, RuntimeError("private-value"))

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "get_owned", fail_read)
        response = await client.post(created.headers["location"] + "/validate", json={})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-validation-driver" not in response.text + caplog.text
    assert "private-value" not in response.text + caplog.text
    recovered = await client.post(created.headers["location"] + "/validate", json={})
    assert recovered.status_code == 200 and recovered.json()["valid"] is True
    assert stored_state(repository_database, workflow_id) == before


async def test_current_validation_pins_snapshot_when_another_session_advances_pointer(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "Pinned", "definition": DEFINITION}
    )
    first_id = created.json()["version"]["id"]
    workflow_id = UUID(created.json()["id"])
    original = WorkflowRepository.get_version_owned
    advanced = False

    def advance_before_snapshot(self, **kwargs):
        nonlocal advanced
        if not advanced:
            advanced = True
            with repository_database.unit_of_work() as session:
                WorkflowRepository(session).append_version(
                    workflow_id=workflow_id,
                    owner_id=owners["a"],
                    expected_version=1,
                    definition={"schema_version": "1.0", "nodes": [], "edges": []},
                )
        return original(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "get_version_owned", advance_before_snapshot)
        response = await client.post(created.headers["location"] + "/validate", json={})
    assert response.status_code == 200 and advanced
    assert response.json()["workflow_version_id"] == first_id
    assert response.json()["valid"] is True
    current = await client.post(created.headers["location"] + "/validate", json={})
    assert current.json()["workflow_version_id"] != first_id
    assert current.json()["valid"] is False
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 2
