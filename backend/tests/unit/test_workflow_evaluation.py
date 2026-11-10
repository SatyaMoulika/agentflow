"""Evaluation cases check behavior using pure operations and a local LLM stub."""

from copy import deepcopy
from typing import Any

from app.modules.workflows.evaluation import CASES, evaluate
from app.modules.workflows.generation import GenerationResponse


def make_proposal(
    nodes: list[dict[str, Any]], edges: list[dict[str, str]], sample: dict
) -> GenerationResponse:
    return GenerationResponse.model_validate(
        {
            "status": "ready",
            "message": "Review",
            "name": "Test",
            "description": "",
            "definition": {"schema_version": "1.0", "nodes": nodes, "edges": edges},
            "sample_input": sample,
            "model": "test-model",
        }
    )


def edge(identifier: str, source: str, target: str, handle: str = "default") -> dict[str, str]:
    return {"id": identifier, "source": source, "target": target, "source_handle": handle}


def cases():
    return {case.id: case for case in CASES}


def branch() -> GenerationResponse:
    value = {"kind": "output", "path": "$.start.output.amount"}
    nodes = [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "choose",
            "type": "condition",
            "config": {
                "field": "$.start.output.amount",
                "operator": "greater_than",
                "value": 10,
            },
        },
        {
            "id": "double",
            "type": "calculator",
            "config": {
                "operation": "multiply",
                "operands": [value, {"kind": "literal", "value": 2}],
            },
        },
        {
            "id": "plus",
            "type": "calculator",
            "config": {
                "operation": "add",
                "operands": [value, {"kind": "literal", "value": 1}],
            },
        },
        {"id": "join", "type": "merge", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ]
    edges = [
        edge("a", "start", "choose"),
        edge("b", "choose", "double", "true"),
        edge("c", "choose", "plus", "false"),
        edge("d", "double", "join"),
        edge("e", "plus", "join"),
        edge("f", "join", "end"),
    ]
    return make_proposal(nodes, edges, {"amount": 15})


def test_case_registry_is_unique_and_bounded() -> None:
    assert len(cases()) == len(CASES) == 6
    assert all(0 < len(case.prompt) <= 2000 for case in CASES)


def test_branch_checks_both_routes_and_sample_input() -> None:
    proposal = branch()
    assert evaluate(cases()["branch_amount"], proposal) == "pass"
    assert proposal.definition is not None
    altered = proposal.model_dump()
    altered["definition"]["nodes"][3]["config"]["operands"][1]["value"] = 9
    assert (
        evaluate(cases()["branch_amount"], GenerationResponse.model_validate(altered))
        == "wrong_output"
    )
    altered = proposal.model_dump()
    altered["sample_input"] = {}
    assert (
        evaluate(cases()["branch_amount"], GenerationResponse.model_validate(altered))
        == "invalid_sample_input"
    )


def test_field_selection_checks_actual_values() -> None:
    nodes = [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "pick",
            "type": "transform",
            "config": {"operation": "pick_fields", "fields": ["customer_name", "message"]},
        },
        {"id": "end", "type": "end", "config": {}},
    ]
    edges = [edge("a", "start", "pick"), edge("b", "pick", "end")]
    proposal = make_proposal(nodes, edges, {"customer_name": "T", "message": "Hi"})
    assert evaluate(cases()["select_fields"], proposal) == "pass"
    nodes = deepcopy(nodes)
    nodes[1]["config"]["fields"] = ["customer_name"]
    assert (
        evaluate(cases()["select_fields"], make_proposal(nodes, edges, {"customer_name": "T"}))
        == "wrong_output"
    )


def test_groq_is_stubbed_and_requires_the_right_message(monkeypatch) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation must not call the provider")

    monkeypatch.setattr("app.modules.executions.groq_provider.complete", forbidden)
    nodes = [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "reply",
            "type": "groq",
            "config": {"instruction": "Reply", "input_field": "message"},
        },
        {"id": "end", "type": "end", "config": {}},
    ]
    edges = [edge("a", "start", "reply"), edge("b", "reply", "end")]
    proposal = make_proposal(nodes, edges, {"message": "Hi"})
    assert evaluate(cases()["support_reply"], proposal) == "pass"
    nodes[1]["config"]["input_field"] = "missing"
    assert evaluate(cases()["support_reply"], make_proposal(nodes, edges, {})) == "execution_failed"


def test_unsupported_case_requires_an_explicit_refusal() -> None:
    case = cases()["unsupported_email"]
    response = GenerationResponse(
        status="unsupported",
        message="Email is not available",
        name="",
        description="",
        definition=None,
        sample_input={},
        model="test-model",
    )
    assert evaluate(case, response) == "pass"
    assert evaluate(case, branch()) == "unexpected_status"
