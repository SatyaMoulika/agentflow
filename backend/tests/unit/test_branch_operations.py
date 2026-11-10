"""Typed scalar comparisons, bounded arithmetic and route/reference semantics."""

import json
from typing import Any

import pytest

from app.modules.executions.operations import (
    NodeExecutionError,
    execute_node,
    next_node_id,
    resolve_config,
    resolve_input,
)
from app.modules.executions.state import FailureCode
from app.modules.workflows.compiler import CompiledBinding, CompiledNode, CompiledRoute


def node(kind: Any, config: dict | None = None, bindings: tuple = ()) -> CompiledNode:
    return CompiledNode("n", kind, json.dumps(config or {}), bindings, ())


@pytest.mark.parametrize(
    ("operation", "left", "right", "expected"),
    [
        ("equals", 1, 1.0, True),
        ("equals", True, 1, False),
        ("equals", False, 0, False),
        ("equals", "1", 1, False),
        ("not_equals", True, 1, True),
        ("not_equals", None, None, False),
        ("equals", None, None, True),
        ("equals", None, False, False),
        ("equals", "Case", "case", False),
        ("equals", "界", "界", True),
        ("not_equals", 2, 2, False),
        ("equals", False, False, True),
        ("greater_than", 2, 1, True),
        ("greater_than", 1, 1, False),
        ("greater_than_or_equal", 1, 1.0, True),
        ("less_than", -2, -1, True),
        ("less_than_or_equal", 1.0, 1, True),
        ("less_than", 2, 1, False),
        ("contains", "Hello 世界", "世界", True),
        ("contains", "Case", "case", False),
        ("contains", "value", "", True),
        ("equals", "x" * 4096, "x" * 4096, True),
    ],
)
def test_conditions_use_typed_scalars_without_coercion(
    operation: str, left: Any, right: Any, expected: bool
) -> None:
    result = execute_node(
        node("condition"),
        {},
        resolved_config={"operator": operation, "field": left, "value": right},
    )
    assert result == {"result": expected}
    assert type(result["result"]) is bool


@pytest.mark.parametrize(
    ("operation", "value"),
    [
        ("equals", []),
        ("equals", {}),
        ("equals", "x" * 4097),
        ("equals", float("nan")),
        ("equals", float("inf")),
        ("equals", 1_000_000_000_001),
        ("greater_than", True),
        ("less_than", "2"),
        ("greater_than", None),
        ("contains", ["x"]),
        ("contains", None),
        ("contains", 1),
    ],
)
def test_invalid_condition_operands_fail_statically(operation: str, value: Any) -> None:
    with pytest.raises(NodeExecutionError) as error:
        execute_node(
            node("condition"),
            {},
            resolved_config={
                "operator": operation,
                "field": value,
                "value": "private-literal" if operation in {"equals", "contains"} else 1,
            },
        )
    assert error.value.code == FailureCode.EXECUTION_FAILED
    assert "private-literal" not in str(error.value)


@pytest.mark.parametrize(
    ("operation", "values", "expected"),
    [
        ("add", [1, 2, 3], 6),
        ("add", [-2, 2], 0),
        ("multiply", [2, 3, 4], 24),
        ("multiply", [-2, 3], -6),
        ("subtract", [5, 8], -3),
        ("divide", [7, 2], 3.5),
        ("divide", [4, 2], 2.0),
        ("add", [0.5, 0.25], 0.75),
        ("add", [1_000_000_000_000, 0], 1_000_000_000_000),
        ("subtract", [-1_000_000_000_000, 0], -1_000_000_000_000),
    ],
)
def test_calculators_return_bounded_numeric_results(
    operation: str, values: list, expected: int | float
) -> None:
    config = {
        "operation": operation,
        "operands": [{"kind": "literal", "value": value} for value in values],
    }
    output = execute_node(node("calculator"), {}, resolved_config=config)
    assert output == {"result": expected}
    assert type(output["result"]) is type(expected)


@pytest.mark.parametrize(
    ("operation", "values"),
    [
        ("divide", [1, 0]),
        ("divide", [0, -0.0]),
        ("add", [1_000_000_000_000, 1]),
        ("multiply", [1_000_000_000_000, 2]),
        (
            "add",
            [1_000_000_000_000, 1, -1],
        ),  # intermediate overflow is not hidden by later subtraction
        ("add", [True, 1]),
        ("add", ["2", 1]),
        ("add", [None, 1]),
        ("add", [{}, 1]),
        ("add", [1_000_000_000_001, 0]),
        ("add", [float("inf"), 1]),
        ("add", [float("nan"), 1]),
    ],
)
def test_invalid_arithmetic_does_not_coerce_or_overflow(operation: str, values: list) -> None:
    with pytest.raises(NodeExecutionError) as error:
        execute_node(
            node("calculator"),
            {},
            resolved_config={
                "operation": operation,
                "operands": [{"kind": "literal", "value": value} for value in values],
            },
        )
    assert error.value.code == FailureCode.EXECUTION_FAILED


@pytest.mark.parametrize("kind", ["calculator", "condition"])
def test_reference_executors_require_explicit_resolved_configuration(kind: str) -> None:
    with pytest.raises(NodeExecutionError):
        execute_node(node(kind), {})


def test_config_bindings_and_data_mappings_are_resolved_separately_without_mutation() -> None:
    config = {
        "operation": "add",
        "operands": [
            {"kind": "output", "path": "$.start.output.Amount"},
            {"kind": "literal", "value": 2},
        ],
    }
    bindings = (
        CompiledBinding(("input_mapping", "Original"), "start", ()),
        CompiledBinding(("config", "operands", 0, "path"), "start", ("Amount",)),
    )
    compiled = node("calculator", config, bindings)
    outputs = {"start": {"Amount": 4}}
    resolved = resolve_config(compiled, outputs)
    assert execute_node(
        compiled, resolve_input(compiled, {}, outputs), resolved_config=resolved
    ) == {"result": 6}
    assert json.loads(compiled.config_json) == config
    assert resolve_input(compiled, {}, outputs) == {"Original": {"Amount": 4}}
    outputs["start"]["Amount"] = 10
    assert resolved["operands"][0]["path"] == 4


def test_missing_config_reference_is_mapping_failure_not_numeric_failure() -> None:
    compiled = node(
        "condition",
        {"field": "$.start.output.Missing", "value": 1, "operator": "equals"},
        (CompiledBinding(("config", "field"), "start", ("Missing",)),),
    )
    with pytest.raises(NodeExecutionError) as error:
        resolve_config(compiled, {"start": {}})
    assert error.value.code == FailureCode.INPUT_MAPPING_FAILED


@pytest.mark.parametrize(("decision", "target"), [(True, "yes"), (False, "no")])
def test_routing_selects_exact_boolean_handle(decision: bool, target: str) -> None:
    compiled = CompiledNode(
        "n", "condition", "{}", (), (CompiledRoute("true", "yes"), CompiledRoute("false", "no"))
    )
    assert next_node_id(compiled, {"result": decision}) == target


@pytest.mark.parametrize("decision", [1, 0, "true", None])
def test_routing_rejects_truthy_nonboolean_results(decision: Any) -> None:
    with pytest.raises(NodeExecutionError):
        next_node_id(node("condition"), {"result": decision})


def test_merge_copies_only_the_selected_incoming_payload() -> None:
    source = {"Chosen": {"value": 1}}
    output = execute_node(node("merge"), source)
    output["Chosen"]["value"] = 2
    assert source == {"Chosen": {"value": 1}}
    assert next_node_id(node("end"), {}) is None


def test_path_looking_literal_stays_literal_and_only_declared_field_is_resolved() -> None:
    path_text = "$.not_available.output.value"
    compiled = node(
        "condition",
        {"field": "$.start.output.text", "operator": "equals", "value": path_text},
        (CompiledBinding(("config", "field"), "start", ("text",)),),
    )
    config = resolve_config(compiled, {"start": {"text": path_text}})
    assert config["value"] == path_text
    assert execute_node(compiled, {}, resolved_config=config) == {"result": True}
