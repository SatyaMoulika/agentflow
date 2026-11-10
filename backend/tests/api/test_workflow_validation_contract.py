"""Validation route authentication and safe request failures without SQL execution."""

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
PATH = f"/api/v1/workflows/{uuid4()}/validate"
ENVELOPE = {"schema_version": "1.0", "nodes": [], "edges": []}


@pytest.fixture
def validation_app() -> Iterator[FastAPI]:
    database = Database(SecretStr("postgresql+psycopg://unused@localhost/unused"))
    application = create_app()

    async def resource() -> Database:
        return database

    async def user() -> UserResponse:
        return UserResponse(
            id=uuid4(),
            email="validation@example.com",
            display_name="Validation",
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


@pytest.mark.parametrize("body", [{}, {"definition": ENVELOPE}, {"version_id": str(uuid4())}])
async def test_validation_requires_bearer_auth_for_every_source(body: dict) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.post(PATH, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "body",
    [
        None,
        [],
        "private-invalid-body",
        {"definition": None},
        {"version_id": None},
        {"version_id": "private-invalid-version"},
        {"version_id": 123},
        {"version_id": str(uuid4()), "definition": ENVELOPE},
        {"expected_version": 0},
        {"definition": ENVELOPE, "owner_id": "private-invalid-owner"},
        {"definition": {}},
        {"definition": {"schema_version": "private-invalid-schema", "nodes": [], "edges": []}},
        {"definition": {"schema_version": "1.0", "nodes": {}, "edges": []}},
        {"definition": {"schema_version": "1.0", "nodes": ["private-invalid-node"], "edges": []}},
        {"definition": {"schema_version": "1.0", "nodes": [], "edges": {}}},
        {"definition": {**ENVELOPE, "private": "x" * 262144}},
    ],
)
async def test_invalid_selectors_or_envelopes_return_safe_422_without_sql(
    validation_app: FastAPI, body: object
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=validation_app), base_url="https://test"
    ) as client:
        response = await client.post(PATH, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"] is None
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-invalid" not in response.text
    assert "x" * 100 not in response.text


async def test_validation_requires_an_explicit_request_body(validation_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=validation_app), base_url="https://test"
    ) as client:
        response = await client.post(PATH)
    assert response.status_code == 422


async def test_explicit_null_body_is_not_a_current_version_selector(
    validation_app: FastAPI,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=validation_app), base_url="https://test"
    ) as client:
        response = await client.post(
            PATH, content="null", headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 422


async def test_invalid_workflow_identifier_is_safe_422_without_sql(
    validation_app: FastAPI,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=validation_app), base_url="https://test"
    ) as client:
        response = await client.post("/api/v1/workflows/private-invalid-workflow/validate", json={})
    assert response.status_code == 422 and "private-invalid" not in response.text


async def test_validation_openapi_documents_auth_required_body_and_error_envelopes() -> None:
    schema = create_app().openapi()
    route = schema["paths"]["/api/v1/workflows/{workflow_id}/validate"]
    assert set(route) == {"post"}
    operation = route["post"]
    assert operation["security"] == [{"AccessBearer": []}]
    assert operation["requestBody"]["required"] is True
    for code in ("401", "404", "422", "503"):
        assert operation["responses"][code]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }
    body_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    body = schema["components"]["schemas"][body_ref.rsplit("/", 1)[1]]
    assert body["additionalProperties"] is False
    assert set(body["properties"]) == {"version_id", "definition"}
    assert "required" not in body
    for field in body["properties"].values():
        assert "anyOf" not in field
