"""Connection endpoints require real authentication and never expose credential inputs."""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.infrastructure.database.session import Database
from app.main import create_app
from app.modules.auth.schemas import UserResponse
from app.modules.connections.schemas import ConnectionCreate
from app.modules.connections.service import ConnectionService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/connections"),
        ("POST", "/connections"),
        ("GET", f"/connections/{uuid4()}"),
        ("DELETE", f"/connections/{uuid4()}"),
    ],
)
async def test_connection_routes_require_bearer_before_database_lookup(
    method: str, path: str
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.request(method, f"/api/v1{path}", json={})
    assert response.status_code == 401


async def test_bad_connection_input_is_static_and_does_not_echo_credentials(caplog) -> None:
    app = create_app()

    async def user():
        return UserResponse(
            id=uuid4(),
            email="contract@example.com",
            display_name="Owner",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    async def database():
        return cast(Database, object())

    app.dependency_overrides[get_current_user] = user
    # Replace get_database itself: this test must never open storage.
    from app.api.dependencies import get_database

    app.dependency_overrides[get_database] = database
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.post(
            "/api/v1/connections",
            json={
                "name": "Test",
                "endpoint_url": "https://private-token@example.com/",
                "auth_type": "bearer",
                "secret": "private-credential\r\nheader",
            },
        )
    assert response.status_code == 422
    assert "private-token" not in response.text + caplog.text
    assert "private-credential" not in response.text + caplog.text
    assert response.json()["error"]["details"] is None


def test_secret_fields_are_write_only_and_missing_encryption_never_opens_storage() -> None:
    schema = create_app().openapi()["components"]["schemas"]
    assert schema["ConnectionCreate"]["properties"]["secret"]["anyOf"][0]["writeOnly"]
    assert "secret" not in schema["ConnectionResponse"]["properties"]
    from app.core.config import Settings
    from app.modules.connections.secrets import ConnectionUnavailableError

    data = ConnectionCreate.model_validate(
        {
            "name": "Test",
            "endpoint_url": "https://example.com/",
            "auth_type": "bearer",
            "secret": "private-credential",
        }
    )
    with pytest.raises(ConnectionUnavailableError):
        ConnectionService(cast(Database, object()), Settings()).create(uuid4(), data)
