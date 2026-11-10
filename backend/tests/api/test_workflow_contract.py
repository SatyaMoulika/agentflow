"""Workflow auth, request validation and precise OpenAPI without SQL execution."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.dependencies import get_current_user, get_database_resource
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.schemas import UserResponse

pytestmark = pytest.mark.anyio


@pytest.fixture
def validation_app() -> Iterator[FastAPI]:
    database = Database(SecretStr("postgresql+psycopg://unused@localhost/unused"))
    application = create_app()

    async def resource() -> Database:
        return database

    async def user() -> UserResponse:
        return UserResponse(
            id=uuid4(),
            email="schema@example.com",
            display_name="Schema",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    application.dependency_overrides[get_database_resource] = resource
    application.dependency_overrides[get_current_user] = user
    try:
        yield application
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("POST", "", {"name": "Draft"}),
        ("GET", "", None),
        ("GET", f"/{uuid4()}", None),
        ("PATCH", f"/{uuid4()}", {"name": "Rename"}),
        ("DELETE", f"/{uuid4()}", None),
    ],
)
async def test_every_workflow_operation_requires_bearer_auth(
    method: str, suffix: str, body: dict | None
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.request(method, "/api/v1/workflows" + suffix, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("POST", "", {"name": "private-invalid", "owner_id": "injected"}),
        ("POST", "", {"name": 123}),
        ("PATCH", f"/{uuid4()}", {}),
        ("PATCH", f"/{uuid4()}", {"name": None}),
        ("PATCH", f"/{uuid4()}", {"status": "active"}),
        ("GET", "?page=0", None),
        ("GET", "?page_size=101", None),
        ("GET", "?owner_id=injected", None),
        ("GET", "?q=%20", None),
        ("GET", "/private-invalid-uuid", None),
        ("GET", f"/{uuid4()}?version_id=private-invalid-uuid", None),
        ("POST", "", {"name": "Draft", "definition": None}),
        ("PATCH", f"/{uuid4()}", {"expected_version": 0}),
        ("PATCH", f"/{uuid4()}", {"definition": {"schema_version": "private-invalid"}}),
    ],
)
async def test_invalid_workflow_requests_are_safe_422_without_sql(
    validation_app: FastAPI,
    method: str,
    suffix: str,
    body: dict | None,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=validation_app), base_url="https://test"
    ) as client:
        response = await client.request(method, "/api/v1/workflows" + suffix, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"] is None
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-invalid" not in response.text and "injected" not in response.text


async def test_workflow_openapi_matches_versioned_drafts_and_partial_patch_rules() -> None:
    schema = create_app().openapi()
    collection = schema["paths"]["/api/v1/workflows"]
    item = schema["paths"]["/api/v1/workflows/{workflow_id}"]
    assert set(collection) == {"get", "post"} and set(item) == {"get", "patch", "delete"}
    assert "content" not in item["delete"]["responses"]["204"]
    for operation in [*collection.values(), *item.values()]:
        assert operation["security"] == [{"AccessBearer": []}]
        for code in ("401", "422", "503"):
            assert operation["responses"][code]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    patch = schema["components"]["schemas"]["WorkflowUpdateRequest"]
    assert patch["minProperties"] == 1
    assert "required" not in patch and patch["additionalProperties"] is False
    assert patch["properties"]["name"]["type"] == "string"
    assert "anyOf" not in patch["properties"]["name"]
    assert set(schema["components"]["schemas"]["WorkflowResponse"]["properties"]) == {
        "id",
        "owner_id",
        "name",
        "description",
        "status",
        "current_version_id",
        "created_at",
        "updated_at",
    }
    assert len(schema["paths"]) == 22

    assert patch["dependentRequired"] == {
        "definition": ["expected_version"],
        "expected_version": ["definition"],
    }
    assert patch["properties"]["expected_version"]["type"] == "integer"
    assert "anyOf" not in patch["properties"]["definition"]
    detail = schema["components"]["schemas"]["WorkflowDetailResponse"]
    assert {"version", "current_version_number"} <= set(detail["properties"])
    version = schema["components"]["schemas"]["WorkflowVersionResponse"]
    assert "definition" in version["properties"] and "definition_json" not in version["properties"]
    assert item["get"]["parameters"][1]["name"] == "version_id"
    assert "409" in item["patch"]["responses"]
