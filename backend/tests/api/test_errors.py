"""Public error contracts, response correlation, and private input protection."""

import logging
import re

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, field_validator

from app.core.config import Settings
from app.core.exceptions import REQUEST_ID_PATTERN
from app.core.logging import request_id_context
from app.main import create_app

pytestmark = pytest.mark.anyio
PRIVATE_VALUE = "private-test-credential"


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [("GET", "/missing", 404, "NOT_FOUND"), ("POST", "/api/v1/health", 405, "METHOD_NOT_ALLOWED")],
)
async def test_routing_errors_have_matching_header_body_and_log_ids(
    method: str, path: str, status: int, code: str, caplog: pytest.LogCaptureFixture
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=create_app()), base_url="http://test"
    ) as client:
        response = await client.request(method, path)

    request_id = response.headers["x-request-id"]
    assert re.fullmatch(REQUEST_ID_PATTERN, request_id)
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert set(response.json()) == {"error", "request_id"}
    assert response.json()["request_id"] == request_id
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["details"] is None
    if status == 405:
        assert response.headers["allow"] == "GET"
    records = [record for record in caplog.records if record.name == "agentflow.http"]
    assert len(records) == 1
    assert records[0].__dict__["request_id"] == request_id
    assert records[0].__dict__["status_code"] == status
    assert records[0].__dict__["duration_ms"] >= 0


@pytest.mark.parametrize(
    ("status", "code", "headers"),
    [
        (401, "UNAUTHENTICATED", {"WWW-Authenticate": "Bearer"}),
        (429, "RATE_LIMITED", {"Retry-After": "30"}),
        (503, "SERVICE_UNAVAILABLE", {"Retry-After": "5"}),
    ],
)
async def test_http_errors_keep_protocol_headers_without_raw_detail(
    status: int, code: str, headers: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    application = create_app()

    @application.get("/test/http-error", include_in_schema=False)
    async def http_error() -> None:
        raise HTTPException(
            status_code=status,
            detail={"credential": PRIVATE_VALUE},
            headers=headers | {"X-Private-Detail": PRIVATE_VALUE},
        )

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/test/http-error")

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"]
    for key, value in headers.items():
        assert response.headers[key] == value
    assert "x-private-detail" not in response.headers
    assert PRIVATE_VALUE not in response.text
    assert PRIVATE_VALUE not in caplog.text


class PrivateInput(BaseModel):
    """Test validator deliberately embeds input in its internal error message."""

    credential: str

    @field_validator("credential")
    @classmethod
    def reject_credential(cls, value: str) -> str:
        raise ValueError(f"rejected credential: {value}")


@pytest.mark.parametrize("malformed_json", [False, True])
async def test_validation_errors_do_not_return_input_messages_or_context(
    malformed_json: bool, caplog: pytest.LogCaptureFixture
) -> None:
    application = create_app()

    @application.post("/test/validate", include_in_schema=False)
    async def validate_body(body: PrivateInput) -> None:
        raise AssertionError("invalid input must not reach the endpoint")

    body = (
        f'{{"credential":"{PRIVATE_VALUE}"'
        if malformed_json
        else (f'{{"credential":"{PRIVATE_VALUE}"}}')
    )
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.post(
            "/test/validate", content=body, headers={"Content-Type": "application/json"}
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "The request is invalid.",
            "details": None,
        },
        "request_id": response.headers["x-request-id"],
    }
    assert PRIVATE_VALUE not in response.text + caplog.text


@pytest.mark.parametrize("debug", [False, True])
async def test_unexpected_errors_are_safe_even_in_debug_and_reset_context(
    debug: bool, caplog: pytest.LogCaptureFixture
) -> None:
    application = create_app(Settings(debug=debug))

    @application.get("/test/crash", include_in_schema=False)
    async def crash() -> None:
        raise RuntimeError(PRIVATE_VALUE)

    # The app owns failures before response start; even the default raising transport
    # must receive the handled envelope, rather than an uncaught runtime exception.
    token = request_id_context.set("outer-context")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            response = await client.get("/test/crash", headers={"Accept": "text/html"})
            assert request_id_context.get() == "outer-context"
            assert (await client.get("/api/v1/health")).status_code == 200
    finally:
        request_id_context.reset(token)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred.",
            "details": None,
        },
        "request_id": response.headers["x-request-id"],
    }
    record = next(record for record in caplog.records if record.__dict__.get("status_code") == 500)
    assert record.levelno == logging.ERROR
    assert record.__dict__["error_type"] == "RuntimeError"
    assert record.__dict__["request_id"] == response.headers["x-request-id"]
    assert PRIVATE_VALUE not in response.text + caplog.text
    assert record.exc_info is None


async def test_response_validation_is_an_internal_error_not_a_client_error() -> None:
    application = create_app()

    class ExpectedOutput(BaseModel):
        amount: int

    @application.get("/test/bad-output", response_model=ExpectedOutput, include_in_schema=False)
    async def bad_output() -> dict[str, str]:
        return {"amount": PRIVATE_VALUE}

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        response = await client.get("/test/bad-output")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert PRIVATE_VALUE not in response.text


async def test_openapi_documents_shared_error_schema_and_request_id_header() -> None:
    schema = create_app().openapi()
    responses = schema["paths"]["/api/v1/health"]["get"]["responses"]

    assert responses["default"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    for status in ("200", "default"):
        assert (
            responses[status]["headers"]["X-Request-ID"]["schema"]["pattern"] == REQUEST_ID_PATTERN
        )
    assert set(schema["components"]["schemas"]["ErrorResponse"]["required"]) == {
        "error",
        "request_id",
    }
