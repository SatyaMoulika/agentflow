"""Approval routes require bearer authentication before looking up stored requests."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.workflows.node_registry import InvalidNodeConfigError, validate_node_config

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/approvals"),
        ("GET", f"/api/v1/approvals/{uuid4()}"),
        ("POST", f"/api/v1/approvals/{uuid4()}/decision"),
    ],
)
async def test_missing_bearer_is_rejected_before_database_lookup(method, path):
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="https://test"
    ) as client:
        response = await client.request(method, path, json={"decision": "approved"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "config",
    [
        {"title": " "},
        {"title": "Review", "expires_in_seconds": 59},
        {"title": "Review", "expires_in_seconds": True},
        {"title": "Review", "assigned_to": str(uuid4())},
    ],
)
async def test_approval_config_cannot_assign_another_identity_or_unbounded_expiry(config):
    with pytest.raises(InvalidNodeConfigError):
        validate_node_config("approval", config)
