"""Generation is authenticated, read-only, and validates untrusted provider output."""

import json
from datetime import UTC, datetime
from typing import get_args
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.core.config import Settings
from app.main import create_app
from app.modules.auth.schemas import UserResponse
from app.modules.connections.schemas import PlannerConnection
from app.modules.executions.groq_provider import GroqError
from app.modules.workflows.generation import INSTRUCTIONS, InvalidProposalError, generate
from app.modules.workflows.node_configs import BinaryCalculatorConfig, FoldCalculatorConfig

pytestmark = pytest.mark.anyio


def signed_in_app():
    application = create_app()

    async def user() -> UserResponse:
        return UserResponse(
            id=uuid4(),
            email="test@example.com",
            display_name="Test",
            is_active=True,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

    application.dependency_overrides[get_current_user] = user
    return application


PROPOSAL = {
    "status": "ready",
    "message": "Review this proposal.",
    "name": "Support reply",
    "description": "Draft a reply",
    "definition": {
        "schema_version": "1.0",
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {
                "id": "reply",
                "type": "groq",
                "config": {"instruction": "Reply", "input_field": "message"},
            },
            {"id": "end", "type": "end", "config": {}},
        ],
        "edges": [
            {"id": "a", "source": "start", "target": "reply"},
            {"id": "b", "source": "reply", "target": "end"},
        ],
    },
    "sample_input": {"message": "Hello"},
}


def test_generation_instructions_include_all_calculator_operations() -> None:
    for config in (FoldCalculatorConfig, BinaryCalculatorConfig):
        for operation in get_args(config.model_fields["operation"].annotation):
            assert f'"{operation}"' in INSTRUCTIONS
    assert '{"kind":"output","path":"$.start.output.amount"}' in INSTRUCTIONS


def test_planner_cannot_invent_http_connections_but_edits_can_preserve_existing_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = str(uuid4())
    definition = {
        **PROPOSAL["definition"],
        "nodes": [
            {"id": "start", "type": "manual", "config": {}},
            {"id": "reply", "type": "http", "config": {"connection_id": identity}},
            {"id": "end", "type": "end", "config": {}},
        ],
    }

    def fake(*args, **kwargs):
        return {
            "content": json.dumps({**PROPOSAL, "definition": definition}),
            "model": "test-model",
        }

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    with pytest.raises(InvalidProposalError):
        generate(Settings(), "Read an endpoint")
    result = generate(
        Settings(),
        "Preserve the HTTP node",
        source_definition=definition,
        connections=[
            PlannerConnection(id=UUID(identity), name="Status", endpoint_url="https://example.com/")
        ],
    )
    assert result.definition is not None
    assert result.definition.nodes[1]["config"] == {"connection_id": identity}


def test_invalid_graph_gets_one_regeneration_using_only_static_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = {**PROPOSAL, "definition": {**PROPOSAL["definition"], "edges": []}}
    calls: list[str] = []

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        calls.append(prompt)
        result = invalid if len(calls) == 1 else PROPOSAL
        return {"content": json.dumps(result), "model": "test-model"}

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    result = generate(Settings(), "private user request")
    assert result.status == "ready" and result.repair_attempted
    assert len(calls) == 2
    assert "INVALID_OUTPUT_HANDLES" in calls[1]
    assert json.dumps(invalid) not in calls[1]


def test_repeated_invalid_proposal_stops_after_two_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        calls.append(prompt)
        return {"content": "private invalid content", "model": "test-model"}

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    with pytest.raises(InvalidProposalError) as captured:
        generate(Settings(), "request")
    assert len(calls) == 2 and captured.value.reason == "invalid_schema"
    assert "private invalid content" not in calls[1]


def test_rate_limit_never_causes_regeneration(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        calls.append(prompt)
        raise GroqError(429)

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    with pytest.raises(GroqError):
        generate(Settings(), "request")
    assert len(calls) == 1


def test_rate_limit_on_regeneration_stops_without_a_third_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        calls.append(prompt)
        if len(calls) == 1:
            return {"content": "invalid", "model": "test-model"}
        raise GroqError(429)

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    with pytest.raises(GroqError) as captured:
        generate(Settings(), "request")
    assert captured.value.status == 429 and len(calls) == 2


async def test_generation_requires_authentication() -> None:
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="https://test") as c:
        response = await c.post("/api/v1/workflows/generate", json={"prompt": "Make a workflow"})
    assert response.status_code == 401


async def test_generation_returns_validated_proposal_without_saving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake(settings: Settings, prompt: str, *, json_mode: bool = False) -> dict[str, str]:
        calls.append((prompt, json_mode))
        return {"content": json.dumps(PROPOSAL), "model": "test-model"}

    monkeypatch.setattr("app.modules.workflows.generation.complete", fake)
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as c:
        response = await c.post(
            "/api/v1/workflows/generate", json={"prompt": "Draft a support reply"}
        )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["definition"] == PROPOSAL["definition"]
    assert response.json()["sample_input"] == {"message": "Hello"}
    assert len(calls) == 1 and calls[0][1] is True
    assert "Draft a support reply" in calls[0][0]


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        json.dumps(
            {
                **PROPOSAL,
                "definition": {
                    **PROPOSAL["definition"],
                    "nodes": [{"id": "bad", "type": "email", "config": {}}],
                },
            }
        ),
        json.dumps({**PROPOSAL, "definition": {**PROPOSAL["definition"], "edges": []}}),
        json.dumps({**PROPOSAL, "status": "unsupported"}),
    ],
)
async def test_generation_rejects_invalid_or_unsupported_graphs(
    monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    monkeypatch.setattr(
        "app.modules.workflows.generation.complete",
        lambda *args, **kwargs: {"content": content, "model": "test-model"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as c:
        response = await c.post("/api/v1/workflows/generate", json={"prompt": "private request"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "GENERATION_INVALID"
    assert "private request" not in response.text


async def test_unsupported_request_returns_explanation_without_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unsupported = {
        "status": "unsupported",
        "message": "Email is not supported yet.",
        "name": "",
        "description": "",
        "definition": None,
        "sample_input": {},
    }
    monkeypatch.setattr(
        "app.modules.workflows.generation.complete",
        lambda *args, **kwargs: {"content": json.dumps(unsupported), "model": "test-model"},
    )
    async with AsyncClient(
        transport=ASGITransport(app=signed_in_app()), base_url="https://test"
    ) as c:
        response = await c.post("/api/v1/workflows/generate", json={"prompt": "Send email"})
    assert response.status_code == 200
    assert response.json()["status"] == "unsupported" and response.json()["definition"] is None
