"""Owner-scoped paginated run discovery for real frontend history."""

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.api.dependencies import get_database_resource
from app.core.config import Settings
from app.core.tokens import AccessTokens
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.repository import UserRepository

pytestmark = [pytest.mark.integration, pytest.mark.anyio]
KEY = "test-only-run-listing-key-at-least-32-bytes"
GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [{"id": "e1", "source": "start", "target": "end"}],
}


@pytest.fixture
def owners(repository_database: Database) -> dict[str, UUID]:
    with repository_database.unit_of_work() as session:
        return {
            label: UserRepository(session)
            .add(email=f"{label}@listing.example.com", display_name=label, password_hash="fixture")
            .id
            for label in ("a", "b")
        }


def auth(owner: UUID) -> dict[str, str]:
    token = AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    ).issue(owner)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client(
    repository_database: Database, owners: dict[str, UUID]
) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(jwt_secret_key=SecretStr(KEY)))

    async def resource() -> Database:
        return repository_database

    app.dependency_overrides[get_database_resource] = resource
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test", headers=auth(owners["a"])
    ) as client:
        yield client


async def seed(
    client: AsyncClient, owner: UUID, name: str, failure: bool = False
) -> tuple[str, str]:
    graph = (
        GRAPH
        if not failure
        else {
            "schema_version": "1.0",
            "nodes": [
                GRAPH["nodes"][0],
                {
                    "id": "pick",
                    "type": "transform",
                    "config": {"operation": "pick_fields", "fields": ["missing"]},
                },
                GRAPH["nodes"][1],
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "pick"},
                {"id": "e2", "source": "pick", "target": "end"},
            ],
        }
    )
    created = await client.post(
        "/api/v1/workflows", json={"name": name, "definition": graph}, headers=auth(owner)
    )
    assert created.status_code == 201
    workflow = created.json()
    run = await client.post(
        f"/api/v1/workflows/{workflow['id']}/runs",
        json={
            "workflow_version_id": workflow["current_version_id"],
            "input": {"private": "business-input"},
        },
        headers=auth(owner),
    )
    assert run.status_code == 201
    return workflow["id"], run.json()["id"]


async def test_empty_run_listing_is_real_empty_state(client: AsyncClient) -> None:
    response = await client.get("/api/v1/runs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 25}
    assert response.headers["cache-control"] == "no-store"


async def test_listing_is_owned_paginated_filtered_and_excludes_payloads(
    client: AsyncClient, owners: dict[str, UUID]
) -> None:
    first, first_run = await seed(client, owners["a"], "First")
    _, failed = await seed(client, owners["a"], "Failed", True)
    other, _ = await seed(client, owners["b"], "Other owner")
    response = await client.get("/api/v1/runs?page_size=1")
    assert response.status_code == 200 and response.json()["total"] == 2
    assert response.json()["items"][0]["id"] == failed
    assert response.json()["items"][0]["status"] == "failed"
    assert response.json()["items"][0]["error_code"] == "EXECUTION_FAILED"
    assert "business-input" not in response.text and "private" not in response.text
    second = await client.get("/api/v1/runs?page_size=1&page=2")
    assert second.json()["items"][0]["id"] == first_run
    assert second.json()["items"][0]["version_number"] == 1
    selected = await client.get(f"/api/v1/runs?workflow_id={first}&status=succeeded")
    assert selected.json()["total"] == 1 and selected.json()["items"][0]["workflow_name"] == "First"
    assert (await client.get(f"/api/v1/runs?workflow_id={other}")).json()["total"] == 0
    assert (await client.get("/api/v1/runs?page=99")).json()["items"] == []
    assert (await client.get("/api/v1/runs", headers=auth(owners["b"]))).json()["total"] == 1


async def test_archived_workflow_runs_stay_discoverable(
    client: AsyncClient, owners: dict[str, UUID]
) -> None:
    workflow, run = await seed(client, owners["a"], "Archived later")
    assert (await client.delete(f"/api/v1/workflows/{workflow}")).status_code == 204
    response = await client.get("/api/v1/runs")
    assert response.json()["total"] == 1 and response.json()["items"][0]["id"] == run


async def test_listing_storage_failure_is_safe_and_recoverable(
    client: AsyncClient,
    repository_database: Database,
) -> None:
    def unavailable(connection, cursor, statement, parameters, context, executemany):
        if "workflow_runs" in statement:
            raise OperationalError("private-query", {}, Exception("private-driver"))

    event.listen(repository_database.engine, "before_cursor_execute", unavailable)
    try:
        response = await client.get("/api/v1/runs")
        assert response.status_code == 503 and "private-" not in response.text
    finally:
        event.remove(repository_database.engine, "before_cursor_execute", unavailable)
    assert (await client.get("/api/v1/runs")).status_code == 200
