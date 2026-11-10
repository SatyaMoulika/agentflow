"""Real workflow APIs enforce owner scope, atomic version saves and non-destructive archive."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from threading import Barrier
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.models import Workflow, WorkflowStatus, WorkflowVersion
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository
from app.modules.workflows.repository import WorkflowRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-workflow-crud-key-at-least-32-bytes"


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


async def test_create_get_patch_and_archive_metadata_journey(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "  Invoices  ", "description": "  Original  "}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["owner_id"] == str(owners["a"]) and body["status"] == "draft"
    assert body["name"] == "Invoices" and body["description"] == "Original"
    assert body["current_version_id"] is None
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")
    location = created.headers["location"]
    assert location == f"/api/v1/workflows/{body['id']}"
    assert created.headers["cache-control"] == "no-store"
    assert (await client.get(location)).json() == body
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 0
    renamed = await client.patch(location, json={"name": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["description"] == "Original"
    assert datetime.fromisoformat(renamed.json()["updated_at"]) > datetime.fromisoformat(
        body["updated_at"]
    )
    cleared = await client.patch(location, json={"description": " "})
    assert cleared.json()["name"] == "Renamed" and cleared.json()["description"] == ""
    archived = await client.delete(location)
    assert archived.status_code == 204 and archived.content == b""
    assert archived.headers["cache-control"] == "no-store"
    saved = (await client.get(location)).json()
    assert saved["status"] == "archived"
    assert (await client.delete(location)).status_code == 204
    assert (await client.get(location)).json()["updated_at"] == saved["updated_at"]
    assert (await client.get("/api/v1/workflows")).json()["total"] == 0
    assert (await client.get("/api/v1/workflows?status=archived")).json()["total"] == 1
    conflict = await client.patch(location, json={"name": "Cannot revive"})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "WORKFLOW_ARCHIVED"
    assert (await client.get(location)).json()["name"] == "Renamed"


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
async def test_missing_and_not_owned_reads_or_writes_have_identical_safe_404(
    client: AsyncClient,
    owners: dict[str, UUID],
    method: str,
) -> None:
    other = await client.post(
        "/api/v1/workflows",
        headers=authorization(owners["b"]),
        json={"name": "private-other-owner"},
    )
    location = other.headers["location"]
    body = {"name": "Injected"} if method == "PATCH" else None
    denied = await client.request(method, location, json=body)
    missing = await client.request(
        method, "/api/v1/workflows/00000000-0000-0000-0000-000000000000", json=body
    )
    assert denied.status_code == missing.status_code == 404
    assert denied.json()["error"] == missing.json()["error"]
    assert denied.json()["request_id"] == denied.headers["x-request-id"]
    assert "private-other-owner" not in denied.text
    actual = await client.get(location, headers=authorization(owners["b"]))
    assert actual.json()["name"] == "private-other-owner" and actual.json()["status"] == "draft"
    assert (await client.get("/api/v1/workflows")).json()["total"] == 0


async def test_pagination_count_and_stable_tie_breaker_are_owner_scoped(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
) -> None:
    with repository_database.unit_of_work() as session:
        repository = WorkflowRepository(session)
        ids = [repository.add(owner_id=owners["a"], name=f"Draft {i}").id for i in range(4)]
        repository.add(owner_id=owners["b"], name="Private other owner")
        archived = repository.add(owner_id=owners["a"], name="Archived")
        archived.status = WorkflowStatus.ARCHIVED
    expected = sorted([str(value) for value in ids], reverse=True)
    first = await client.get("/api/v1/workflows?page_size=2")
    second = await client.get("/api/v1/workflows?page=2&page_size=2")
    assert first.status_code == second.status_code == 200
    assert [item["id"] for item in first.json()["items"] + second.json()["items"]] == expected
    assert first.json()["total"] == second.json()["total"] == 4
    assert first.json()["page"] == 1 and second.json()["page"] == 2
    beyond = (await client.get("/api/v1/workflows?page=99&page_size=2")).json()
    assert beyond == {"items": [], "total": 4, "page": 99, "page_size": 2}
    assert first.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("search", "expected"),
    [
        ("%", "Percent %"),
        ("_", "Under_score"),
        ("/", "slash /"),
        ("' OR 1=1 --", "quote ' or 1=1 --"),
        ("pErCeNt", "Percent %"),
    ],
)
async def test_search_is_literal_case_insensitive_and_cannot_expand_sql_wildcards(
    client: AsyncClient,
    search: str,
    expected: str,
) -> None:
    for name in ["Percent %", "Under_score", "slash /", "quote ' or 1=1 --", "Ordinary"]:
        assert (await client.post("/api/v1/workflows", json={"name": name})).status_code == 201
    response = await client.get("/api/v1/workflows", params={"q": search})
    assert response.status_code == 200 and response.json()["total"] == 1
    assert [item["name"] for item in response.json()["items"]] == [expected]


async def test_archive_and_metadata_edits_preserve_saved_history_and_pointer(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
) -> None:
    with repository_database.unit_of_work() as session:
        repository = WorkflowRepository(session)
        row = repository.add(owner_id=owners["a"], name="Versioned")
        version = repository.append_version(
            workflow_id=row.id,
            owner_id=owners["a"],
            expected_version=0,
            definition={
                "schema_version": "1.0",
                "nodes": [],
                "edges": [],
                "private_graph": "preserve-me",
            },
        )
        workflow_id, version_id = row.id, version.id
    location = f"/api/v1/workflows/{workflow_id}"
    response = await client.patch(location, json={"description": "Metadata edit"})
    assert response.status_code == 200 and response.json()["current_version_id"] == str(version_id)
    assert response.json()["version"]["definition"]["private_graph"] == "preserve-me"
    assert "definition_json" not in response.text
    listed = (await client.get("/api/v1/workflows")).json()
    assert "private_graph" not in str(listed) and "version" not in listed["items"][0]
    assert (await client.delete(location)).status_code == 204
    with repository_database.session() as session:
        workflow = session.get(Workflow, workflow_id)
        version = session.get(WorkflowVersion, version_id)
        assert workflow is not None and workflow.current_version_id == version_id
        assert version is not None and version.definition_json["private_graph"] == "preserve-me"


@pytest.mark.parametrize("operation", ["create", "update", "archive"])
async def test_storage_error_after_flush_rolls_back_mutation_and_recovers(
    client: AsyncClient,
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    location = "/api/v1/workflows"
    if operation != "create":
        created = await client.post(location, json={"name": "Original"})
        location = created.headers["location"]
    method = {"create": "add", "update": "update_metadata", "archive": "archive"}[operation]
    original = getattr(WorkflowRepository, method)

    def fail_after_flush(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise OperationalError("private-workflow-driver", {}, RuntimeError("private-input-value"))

    async def request():
        if operation == "create":
            return await client.post(location, json={"name": "Created"})
        if operation == "update":
            return await client.patch(location, json={"name": "Changed"})
        return await client.delete(location)

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, method, fail_after_flush)
        response = await request()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "private-workflow-driver" not in response.text + caplog.text
    with repository_database.session() as session:
        rows = session.scalars(select(Workflow)).all()
        if operation == "create":
            assert rows == []
        else:
            assert (
                len(rows) == 1
                and rows[0].name == "Original"
                and rows[0].status == WorkflowStatus.DRAFT
            )
    assert (await request()).status_code == {"create": 201, "update": 200, "archive": 204}[
        operation
    ]


async def test_invalid_response_after_insert_rolls_back_before_success(
    client: AsyncClient,
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = WorkflowRepository.add

    def invalid_timestamp(self, **kwargs):
        row = original(self, **kwargs)
        row.created_at = datetime(2026, 11, 2)  # Naive fails the public AwareDatetime contract.
        return row

    monkeypatch.setattr(WorkflowRepository, "add", invalid_timestamp)
    response = await client.post("/api/v1/workflows", json={"name": "Must roll back"})
    assert response.status_code == 500 and "location" not in response.headers
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(Workflow)) == 0


DEFINITION = {
    "schema_version": "1.0",
    "nodes": [],
    "edges": [],
    "EditorState": {"CustomerID": 123, "invoice_total": False},
}


async def test_initial_definition_and_historical_read_preserve_immutable_snapshots(
    client: AsyncClient,
    repository_database: Database,
) -> None:
    created = await client.post(
        "/api/v1/workflows", json={"name": "Saved", "definition": DEFINITION}
    )
    assert created.status_code == 201
    location = created.headers["location"]
    first = created.json()
    first_version = first["version"]
    assert first["current_version_number"] == first_version["version_number"] == 1
    assert first["current_version_id"] == first_version["id"]
    assert first_version["definition"] == DEFINITION
    assert first_version["created_by"] == first["owner_id"]
    assert first_version["workflow_id"] == first["id"]
    assert first["status"] == "draft"
    changed = {**DEFINITION, "nodes": [{"config": {"CustomerID": "new"}}]}
    saved = await client.patch(
        location,
        json={
            "name": "Renamed",
            "expected_version": 1,
            "definition": changed,
        },
    )
    assert saved.status_code == 200
    second = saved.json()
    assert second["current_version_number"] == second["version"]["version_number"] == 2
    assert second["current_version_id"] != first_version["id"]
    assert second["version"]["definition"] == changed
    assert (await client.get(location)).json() == second
    historical = await client.get(location, params={"version_id": first_version["id"]})
    assert historical.status_code == 200
    old = historical.json()
    assert old["version"] == first_version
    assert old["name"] == "Renamed" and old["current_version_number"] == 2
    assert old["current_version_id"] == second["current_version_id"]
    assert historical.headers["cache-control"] == "no-store"
    assert (await client.delete(location)).status_code == 204
    archived = await client.get(location, params={"version_id": first_version["id"]})
    assert archived.json()["version"] == first_version and archived.json()["status"] == "archived"
    denied = await client.patch(location, json={"expected_version": 2, "definition": DEFINITION})
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "WORKFLOW_ARCHIVED"
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 2


async def test_versionless_first_save_and_stale_combined_save_are_atomic(
    client: AsyncClient,
    repository_database: Database,
    caplog: pytest.LogCaptureFixture,
) -> None:
    created = await client.post("/api/v1/workflows", json={"name": "Original"})
    location = created.headers["location"]
    assert created.json()["version"] is None and created.json()["current_version_number"] == 0
    stale = await client.patch(location, json={"expected_version": 1, "definition": DEFINITION})
    assert stale.status_code == 409
    assert (await client.get(location)).json() == created.json()
    saved = await client.patch(location, json={"expected_version": 0, "definition": DEFINITION})
    assert saved.status_code == 200 and saved.json()["current_version_number"] == 1
    stale = await client.patch(
        location,
        json={
            "name": "private-stale-overwrite",
            "description": "private-stale-value",
            "expected_version": 0,
            "definition": {**DEFINITION, "private": "private-snapshot"},
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == {
        "code": "WORKFLOW_VERSION_CONFLICT",
        "message": "The workflow version changed. Reload before saving.",
        "details": None,
    }
    assert stale.json()["request_id"] == stale.headers["x-request-id"]
    assert "private-stale" not in stale.text + caplog.text
    assert "private-snapshot" not in stale.text + caplog.text
    assert (await client.get(location)).json() == saved.json()
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 1


async def test_history_and_definition_writes_enforce_owner_and_workflow_membership(
    client: AsyncClient,
    owners: dict[str, UUID],
) -> None:
    records = []
    for owner in ("a", "a", "b"):
        response = await client.post(
            "/api/v1/workflows",
            headers=authorization(owners[owner]),
            json={"name": "private-owned-draft", "definition": DEFINITION},
        )
        assert response.status_code == 201
        records.append(response.json())
    own, sibling, foreign = records
    location = f"/api/v1/workflows/{own['id']}"
    missing_id = "00000000-0000-0000-0000-000000000000"
    errors = []
    for version_id in (sibling["version"]["id"], foreign["version"]["id"], missing_id):
        response = await client.get(location, params={"version_id": version_id})
        assert response.status_code == 404
        errors.append(response.json()["error"])
    for workflow_id in (foreign["id"], missing_id):
        path = f"/api/v1/workflows/{workflow_id}"
        for response in (
            await client.get(path, params={"version_id": foreign["version"]["id"]}),
            await client.patch(path, json={"expected_version": 0, "definition": DEFINITION}),
        ):
            assert response.status_code == 404
            errors.append(response.json()["error"])
            assert "private-owned-draft" not in response.text
    assert all(error == errors[0] for error in errors)
    actual = await client.get(
        f"/api/v1/workflows/{foreign['id']}", headers=authorization(owners["b"])
    )
    assert actual.json() == foreign


@pytest.mark.parametrize("operation", ["create", "update"])
async def test_version_insert_pointer_and_metadata_roll_back_on_storage_failure(
    client: AsyncClient,
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    location = "/api/v1/workflows"
    before = None
    if operation == "update":
        created = await client.post(location, json={"name": "Original", "definition": DEFINITION})
        location, before = created.headers["location"], created.json()
    original = WorkflowRepository.append_version

    def fail_after_pointer(self, **kwargs):
        original(self, **kwargs)
        raise OperationalError("private-version-driver", {}, RuntimeError("private-version-value"))

    async def save():
        if operation == "create":
            return await client.post(location, json={"name": "New", "definition": DEFINITION})
        return await client.patch(
            location,
            json={
                "name": "Changed",
                "expected_version": 1,
                "definition": DEFINITION,
            },
        )

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "append_version", fail_after_pointer)
        response = await save()
    assert response.status_code == 503
    assert "private-version" not in response.text + caplog.text
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(Workflow)) == (1 if before else 0)
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == (
            1 if before else 0
        )
    if before:
        assert (await client.get(location)).json() == before
    recovered = await save()
    assert recovered.status_code == (201 if operation == "create" else 200)
    assert recovered.json()["current_version_number"] == (1 if operation == "create" else 2)


async def test_invalid_version_response_rolls_back_snapshot_and_metadata(
    client: AsyncClient,
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = await client.post("/api/v1/workflows", json={"name": "Original"})
    location, before = created.headers["location"], created.json()
    from app.modules.workflows.schemas import WorkflowVersionResponse

    original = WorkflowVersionResponse.model_validate

    def invalid_timestamp(value):
        return original(
            {
                "id": value.id,
                "workflow_id": value.workflow_id,
                "version_number": value.version_number,
                "created_by": value.created_by,
                "definition_json": value.definition_json,
                "created_at": datetime(2026, 11, 2),
            }
        )

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowVersionResponse, "model_validate", invalid_timestamp)
        response = await client.patch(
            location,
            json={
                "name": "Changed",
                "expected_version": 0,
                "definition": DEFINITION,
            },
        )
    assert response.status_code == 500
    assert (await client.get(location)).json() == before
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 0


@pytest.mark.parametrize("starting_version", [0, 1])
async def test_concurrent_http_saves_commit_one_snapshot_and_reject_stale_writer(
    client: AsyncClient,
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    starting_version: int,
) -> None:
    data: dict[str, object] = {"name": "Original"}
    if starting_version:
        data["definition"] = DEFINITION
    created = await client.post("/api/v1/workflows", json=data)
    location = created.headers["location"]
    barrier = Barrier(2, timeout=5)
    pids: set[int] = set()
    original = WorkflowRepository.lock_owned

    def synchronize(self, **kwargs):
        if not self.session.info.get("version_race_synchronized"):
            self.session.info["version_race_synchronized"] = True
            self.session.execute(text("SET LOCAL lock_timeout = '5s'"))
            self.session.execute(text("SET LOCAL statement_timeout = '8s'"))
            pids.add(int(self.session.scalar(text("SELECT pg_backend_pid()"))))
            # Keep an old identity-map object alive across the competing commit.
            cached = self.get_owned(**kwargs)
            assert cached is not None
            barrier.wait()
        return original(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "lock_owned", synchronize)
        results = await asyncio.gather(
            *[
                client.patch(
                    location,
                    json={
                        "name": label,
                        "expected_version": starting_version,
                        "definition": {**DEFINITION, "winner": label},
                    },
                )
                for label in ("first", "second")
            ]
        )
    assert len(pids) == 2 and sorted(response.status_code for response in results) == [200, 409]
    winner = next(response.json() for response in results if response.status_code == 200)
    loser = next(response for response in results if response.status_code == 409)
    assert loser.json()["error"]["code"] == "WORKFLOW_VERSION_CONFLICT"
    assert winner["current_version_number"] == starting_version + 1
    assert winner["name"] == winner["version"]["definition"]["winner"]
    assert (await client.get(location)).json() == winner
    with repository_database.session() as session:
        assert (
            session.scalar(select(func.count()).select_from(WorkflowVersion))
            == starting_version + 1
        )


async def test_current_read_pins_immutable_snapshot_when_writer_advances_pointer(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.workflows.schemas import WorkflowUpdateRequest
    from app.modules.workflows.service import WorkflowService

    created = await client.post(
        "/api/v1/workflows", json={"name": "Original", "definition": DEFINITION}
    )
    before, location = created.json(), created.headers["location"]
    original = WorkflowRepository.get_version_owned
    advanced = False

    def advance_before_snapshot(self, **kwargs):
        nonlocal advanced
        if not advanced:
            advanced = True
            WorkflowService(repository_database).update(
                workflow_id=UUID(before["id"]),
                owner_id=owners["a"],
                data=WorkflowUpdateRequest.model_validate(
                    {
                        "name": "New metadata",
                        "expected_version": 1,
                        "definition": {**DEFINITION, "writer": "new snapshot"},
                    }
                ),
            )
        return original(self, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(WorkflowRepository, "get_version_owned", advance_before_snapshot)
        read = await client.get(location)
    assert advanced and read.json() == before
    after = (await client.get(location)).json()
    assert after["name"] == "New metadata" and after["current_version_number"] == 2


async def test_real_catalog_auth_uses_current_active_user_and_does_not_execute(
    client: AsyncClient,
    repository_database: Database,
    owners: dict[str, UUID],
) -> None:
    from app.infrastructure.database.models import User

    first = await client.get("/api/v1/node-types")
    second = await client.get("/api/v1/node-types", headers=authorization(owners["b"]))
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert {item["type"] for item in first.json()["items"] if item["execution_ready"]} == {
        "agent",
        "http",
        "groq",
        "json_parser",
        "classify",
        "extract",
        "manual",
        "transform",
        "condition",
        "calculator",
        "merge",
        "end",
    }
    with repository_database.unit_of_work() as session:
        owner = session.get(User, owners["a"])
        assert owner is not None
        owner.is_active = False
    denied = await client.get("/api/v1/node-types")
    assert denied.status_code == 401
    assert denied.json()["error"]["code"] == "UNAUTHENTICATED"
    with repository_database.session() as session:
        assert session.scalar(select(func.count()).select_from(Workflow)) == 0
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 0
