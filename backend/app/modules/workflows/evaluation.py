"""Small synthetic evaluations for generated proposals; no network or storage access."""

import json
from dataclasses import dataclass
from typing import Any, Literal

from app.modules.executions.operations import (
    NodeExecutionError,
    execute_node,
    next_node_id,
    resolve_config,
    resolve_input,
)
from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload
from app.modules.workflows.compiler import CompiledWorkflow, compile_workflow
from app.modules.workflows.generation import GenerationResponse
from app.modules.workflows.node_registry import EXECUTION_READY_TYPES


@dataclass(frozen=True)
class Scenario:
    input: dict[str, Any]
    output: dict[str, Any]
    groq_input: str | None = None


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    prompt: str
    expected: Literal["ready", "unsupported"]
    scenarios: tuple[Scenario, ...] = ()


CASES = (
    EvaluationCase(
        "branch_amount",
        "Create a workflow accepting amount. If amount is greater than 10, multiply it by 2; "
        "otherwise add 1. Merge the branches and return the result.",
        "ready",
        (Scenario({"amount": 15}, {"result": 30}), Scenario({"amount": 4}, {"result": 5})),
    ),
    EvaluationCase(
        "multiply_input",
        "Create a workflow that takes a number in the field amount, multiplies it by 3, "
        "and returns the result.",
        "ready",
        (Scenario({"amount": 7}, {"result": 21}), Scenario({"amount": -2}, {"result": -6})),
    ),
    EvaluationCase(
        "select_fields",
        "Create a workflow that accepts a JSON object, keeps only customer_name and message, "
        "and returns those two fields.",
        "ready",
        (
            Scenario(
                {"customer_name": "Asha", "message": "Hello", "order_id": "TEST-1"},
                {"customer_name": "Asha", "message": "Hello"},
            ),
        ),
    ),
    EvaluationCase(
        "support_reply",
        "Create a workflow that takes a customer support message in the message field and "
        "uses Groq to draft a helpful response; return the Groq result.",
        "ready",
        (
            Scenario(
                {"message": "My package arrived damaged."},
                {"model": "evaluation-model", "content": "evaluation-response"},
                "My package arrived damaged.",
            ),
        ),
    ),
    EvaluationCase(
        "unsupported_email",
        "Create a workflow that automatically sends an email to a customer.",
        "unsupported",
    ),
    EvaluationCase(
        "unsupported_schedule",
        "Run a workflow on a schedule every morning without a manual trigger.",
        "unsupported",
    ),
)


def _simulate(
    plan: CompiledWorkflow, input_data: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Use actual pure operations; replace Groq calls with a deterministic local stub."""
    incoming = copy_payload(input_data)
    outputs: dict[str, dict[str, Any]] = {}
    nodes = {node.id: node for node in plan.nodes}
    current: str | None = plan.entry_node_id
    calls: list[str] = []
    visited: set[str] = set()
    while current is not None:
        if current in visited or current not in nodes:
            raise ValueError("Invalid route")
        visited.add(current)
        node = nodes[current]
        resolved = resolve_input(node, incoming, outputs)
        config = resolve_config(node, outputs)
        if node.type == "groq":
            selected = resolved.get(config["input_field"])
            if (
                not isinstance(selected, str)
                or not selected.strip()
                or len(f"{config['instruction']}\n\n{selected}") > 4000
            ):
                raise ValueError("Invalid Groq input")
            calls.append(selected)
            incoming = {"model": "evaluation-model", "content": "evaluation-response"}
        else:
            incoming = execute_node(node, resolved, resolved_config=config)
        outputs[current] = incoming
        current = next_node_id(node, incoming)
    return incoming, calls


def evaluate(case: EvaluationCase, proposal: GenerationResponse) -> str:
    """Return a static outcome code; never print prompts or model output."""
    if proposal.status != case.expected:
        return "unexpected_status"
    if case.expected == "unsupported":
        return "pass" if proposal.definition is None and proposal.message.strip() else "bad_refusal"
    if proposal.definition is None:
        return "missing_definition"
    compiled = compile_workflow(proposal.definition.model_dump())
    plan = compiled.plan
    if plan is None or any(node.type not in EXECUTION_READY_TYPES for node in plan.nodes):
        return "invalid_graph"
    for scenario in case.scenarios:
        try:
            output, calls = _simulate(plan, scenario.input)
        except (NodeExecutionError, InvalidExecutionPayloadError, KeyError, TypeError, ValueError):
            return "execution_failed"
        if json.dumps(output, sort_keys=True) != json.dumps(scenario.output, sort_keys=True):
            return "wrong_output"
        if calls != ([scenario.groq_input] if scenario.groq_input is not None else []):
            return "wrong_groq_input"
    try:
        _simulate(plan, proposal.sample_input)
    except (NodeExecutionError, InvalidExecutionPayloadError, KeyError, TypeError, ValueError):
        return "invalid_sample_input"
    return "pass"
