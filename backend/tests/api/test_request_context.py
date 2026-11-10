"""Correlation remains isolated under concurrent requests and excludes raw URLs."""

import asyncio
import json
import logging
import re

import pytest
from asgi_lifespan import LifespanManager
from fastapi import Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import REQUEST_ID_PATTERN
from app.core.logging import request_id_context
from app.main import create_app

pytestmark = pytest.mark.anyio


async def test_health_gets_new_server_ids_ignoring_incoming_and_endpoint_headers() -> None:
    application = create_app()

    @application.get("/test/override-header", include_in_schema=False)
    async def override_header() -> JSONResponse:
        return JSONResponse({}, headers={"X-Request-ID": "endpoint-supplied"})

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        responses = [
            await client.get(path, headers={"X-Request-ID": "caller-supplied"})
            for path in ("/api/v1/health", "/api/v1/health", "/test/override-header")
        ]

    ids = [response.headers["x-request-id"] for response in responses]
    assert len(set(ids)) == 3
    assert all(re.fullmatch(REQUEST_ID_PATTERN, value) for value in ids)
    assert responses[0].json() == {"status": "ok", "service": "agentflow"}
    assert request_id_context.get() is None


async def test_concurrent_requests_keep_context_and_json_logs_isolated(
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = create_app()
    arrived: list[str] = []
    both_arrived = asyncio.Event()
    logger = logging.getLogger("agentflow.test")

    @application.get("/test/context/{label}", include_in_schema=False)
    async def context(label: str, request: Request) -> dict[str, str | None]:
        before = request_id_context.get()
        arrived.append(label)
        if len(arrived) == 2:
            both_arrived.set()
        await both_arrived.wait()
        logger.info("Context observed")
        return {
            "before": before,
            "after": request_id_context.get(),
            "state": request.state.request_id,
        }

    async with LifespanManager(application) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    client.get("/test/context/first"), client.get("/test/context/second")
                ),
                timeout=2,
            )

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    ids = {response.headers["x-request-id"] for response in (first, second)}
    assert len(ids) == 2
    for response in (first, second):
        request_id = response.headers["x-request-id"]
        assert response.json() == {"before": request_id, "after": request_id, "state": request_id}
    observed = [record for record in records if record["message"] == "Context observed"]
    assert {record["request_id"] for record in observed} == ids
    completed = [record for record in records if record["logger"] == "agentflow.http"]
    assert {record["request_id"] for record in completed} == ids
    assert all(record["route"] == "/test/context/{label}" for record in completed)
    lifecycle = [record for record in records if record["logger"] == "agentflow.lifecycle"]
    assert len(lifecycle) == 2
    assert all(record["request_id"] is None for record in lifecycle)
    assert request_id_context.get() is None


async def test_logs_exclude_credentials_query_strings_and_dynamic_path_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    application = create_app()

    @application.get("/test/private/{credential}", include_in_schema=False)
    async def private_path(credential: str) -> dict[str, bool]:
        return {"ok": True}

    async with LifespanManager(application) as manager:
        async with AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as client:
            for path in ("/test/private/secret-path-value", "/unmatched-secret-path"):
                await client.get(
                    path + "?token=secret-query-value",
                    headers={
                        "Authorization": "Bearer secret-auth-value",
                        "Cookie": "session=secret-cookie-value",
                    },
                )

    output = capsys.readouterr().out
    assert "secret-" not in output
    requests = [
        json.loads(line)
        for line in output.splitlines()
        if json.loads(line)["logger"] == "agentflow.http"
    ]
    assert [record["route"] for record in requests] == ["/test/private/{credential}", "<unmatched>"]
