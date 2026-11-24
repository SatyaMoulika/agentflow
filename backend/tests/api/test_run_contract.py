"""Run authentication, request privacy and OpenAPI without successful SQL access."""

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
CREATE = f"/api/v1/workflows/{uuid4()}/runs"
GET = f"/api/v1/runs/{uuid4()}"
BODY = {"workflow_version_id": str(uuid4()), "input": {}}


@pytest.fixture
def run_app() -> Iterator[FastAPI]:
    database = Database(SecretStr("postgresql+psycopg://unused@localhost/unused"))
    application = create_app()

    async def resource() -> Database:
        return database

    async def user() -> UserResponse:
        return UserResponse(
            id=uuid4(),
            email="run@example.com",
            display_name="Run",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    application.dependency_overrides[get_current_user] = user
    application.dependency_overrides[get_database_resource] = resource
    try:
        yield application
    finally:
        database.dispose()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", CREATE),
        ("GET", GET),
        ("GET", GET + "/events"),
        ("GET", GET + "/events/stream"),
        ("POST", GET + "/retry"),
        ("POST", GET + "/cancel"),
    ],
)
async def test_run_routes_require_bearer_before_storage(method: str, path: str) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.request(method, path, json=BODY)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "query", ["after_sequence=-1", "limit=0", "limit=101", "after_sequence=9223372036854775808"]
)
async def test_invalid_event_pagination_is_rejected(run_app: FastAPI, query: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="https://test") as client:
        response = await client.get(f"{GET}/events?{query}")
    assert response.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"input": None},
        {"max_attempts": 0},
        {"max_attempts": 4},
        {"max_attempts": True},
        {"max_attempts": "2"},
        {"input": []},
        {"input": "private-input"},
        {"workflow_version_id": None},
        {"workflow_version_id": "private-version"},
        {"owner_id": "private-owner"},
        {"status": "succeeded"},
        {"definition": {}},
        {"input": {"large": "x" * 262144}},
    ],
)
async def test_invalid_run_commands_return_safe_422_without_sql(
    run_app: FastAPI, changes: dict, caplog: pytest.LogCaptureFixture
) -> None:
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="https://test") as client:
        response = await client.post(CREATE, json=BODY | changes)
    assert response.status_code == 422
    assert response.json()["error"]["details"] is None
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert "private-" not in response.text + caplog.text


async def test_invalid_idempotency_header_is_rejected_without_sql(run_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="https://test") as client:
        response = await client.post(CREATE, json=BODY, headers={"Idempotency-Key": "private key"})
    assert response.status_code == 422 and "private-key" not in response.text


async def test_run_openapi_documents_delivery_modes_and_public_json_names() -> None:
    schema = create_app().openapi()
    create = schema["paths"]["/api/v1/workflows/{workflow_id}/runs"]["post"]
    get = schema["paths"]["/api/v1/runs/{run_id}"]["get"]
    assert len(schema["paths"]) == 31
    assert sum(len(path) for path in schema["paths"].values()) == 36
    resume = schema["paths"]["/api/v1/runs/{run_id}/agent-resume"]["post"]
    assert resume["operationId"] == "resume_workflow_agent"
    assert resume["security"] == [{"AccessBearer": []}]
    assert resume["requestBody"]["required"] is True
    assert create["operationId"] == "create_workflow_run"
    assert create["requestBody"]["required"] is True
    assert "201" in create["responses"] and "202" in create["responses"]
    assert create["responses"]["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/RunResponse"
    }
    for operation in (create, get):
        assert operation["security"] == [{"AccessBearer": []}]
        for code in ("401", "404", "422", "503"):
            assert operation["responses"][code]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorResponse"
            }
    command = schema["components"]["schemas"]["RunCreateRequest"]
    assert command["additionalProperties"] is False
    assert set(command["required"]) == {"workflow_version_id", "input"}
    response = schema["components"]["schemas"]["RunResponse"]["properties"]
    assert {"input", "output", "version", "node_runs", "error_code"} <= set(response)
    assert not {"input_json", "output_json", "password_hash", "owner_id"} & set(response)


async def test_run_listing_requires_authentication_before_storage() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.get("/api/v1/runs")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "query",
    [
        "page=0",
        "page_size=101",
        "page_size=0",
        "status=private-invalid",
        "workflow_id=private-invalid",
        "owner_id=private-owner",
    ],
)
async def test_run_list_rejects_invalid_filters_without_sql(run_app: FastAPI, query: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="https://test") as client:
        response = await client.get(f"/api/v1/runs?{query}")
    assert response.status_code == 422
    assert "private-" not in response.text


async def test_run_list_openapi_excludes_business_payloads() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/runs"]["get"]
    assert operation["operationId"] == "list_workflow_runs"
    assert operation["security"] == [{"AccessBearer": []}]
    item = schema["components"]["schemas"]["RunListItem"]["properties"]
    assert not {"input", "output", "node_runs", "version"} & set(item)
    assert {"workflow_name", "version_number", "status"} <= set(item)


@pytest.mark.parametrize(
    "payload",
    [
        {"max_attempts": 0},
        {"max_attempts": 4},
        {"max_attempts": True},
        {"max_attempts": "2"},
        {"input": {}},
        {"workflow_version_id": "private"},
    ],
)
async def test_retry_body_is_bounded_and_cannot_override_original(
    run_app: FastAPI, payload: dict
) -> None:
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="https://test") as client:
        result = await client.post(GET + "/retry", json=payload)
    assert result.status_code == 422 and "private" not in result.text


async def test_duplicate_idempotency_headers_are_rejected(run_app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=run_app), base_url="https://test") as client:
        result = await client.post(
            CREATE, json=BODY, headers=[("Idempotency-Key", "a"), ("Idempotency-Key", "b")]
        )
    assert result.status_code == 422
