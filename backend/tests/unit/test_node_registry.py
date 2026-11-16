"""Typed contracts reject ambiguous operations without evaluating or resolving anything."""

from copy import deepcopy

import pytest
from pydantic import JsonValue, TypeAdapter, ValidationError

from app.modules.workflows.node_configs import OutputReference
from app.modules.workflows.node_registry import (
    InvalidNodeConfigError,
    UnsupportedNodeTypeError,
    node_type_catalog,
    validate_node_config,
)
from app.modules.workflows.schemas import WorkflowCreateRequest


@pytest.mark.parametrize("node_type", ["manual", "merge", "end"])
def test_structural_configs_are_empty_and_strict(node_type: str) -> None:
    assert validate_node_config(node_type, {}).model_dump() == {}
    with pytest.raises(InvalidNodeConfigError):
        validate_node_config(node_type, {"expression": "private-arbitrary-code"})


@pytest.mark.parametrize(
    ("node_type", "config"),
    [
        ("transform", {"operation": "identity"}),
        ("transform", {"operation": "pick_fields", "fields": ["CustomerID", "invoice_total"]}),
        (
            "condition",
            {"field": "$.start.output.amount", "operator": "greater_than", "value": 50000},
        ),
        ("condition", {"field": "$.a.output", "operator": "equals", "value": None}),
        ("condition", {"field": "$.a.output.flag", "operator": "not_equals", "value": False}),
        (
            "condition",
            {"field": "$.a.output.text", "operator": "contains", "value": " Mixed Case "},
        ),
        (
            "calculator",
            {
                "operation": "multiply",
                "operands": [
                    {"kind": "output", "path": "$.start.output.amount"},
                    {"kind": "literal", "value": 1.18},
                ],
            },
        ),
        (
            "calculator",
            {
                "operation": "divide",
                "operands": [
                    {"kind": "literal", "value": 1},
                    {"kind": "literal", "value": 0},
                ],
            },
        ),  # Runtime arithmetic failures belong to execution, not config parsing.
    ],
)
def test_valid_configs_round_trip_without_coercion_or_business_key_changes(
    node_type: str,
    config: dict,
) -> None:
    before = deepcopy(config)
    assert validate_node_config(node_type, config).model_dump() == before
    assert config == before


@pytest.mark.parametrize("value", [False, True, 1, 1.25, "1", None])
def test_equality_operands_keep_their_exact_json_type(value: object) -> None:
    config = validate_node_config(
        "condition",
        {
            "field": "$.start.output.amount",
            "operator": "equals",
            "value": value,
        },
    ).model_dump()
    assert type(config["value"]) is type(value)
    assert config["value"] == value


@pytest.mark.parametrize(
    ("node_type", "config"),
    [
        ("manual", []),
        ("end", None),
        ("transform", {}),
        ("transform", {"operation": "eval", "expression": "__import__('os')"}),
        ("transform", {"operation": "identity", "expression": "input"}),
        ("transform", {"operation": "pick_fields", "fields": []}),
        ("transform", {"operation": "pick_fields", "fields": ["same", "same"]}),
        ("transform", {"operation": "pick_fields", "fields": [1]}),
        ("transform", {"operation": "pick_fields", "fields": ["x" * 201]}),
        ("transform", {"operation": "pick_fields", "fields": [str(i) for i in range(101)]}),
        (
            "condition",
            {"field": "$.start.output.amount", "operator": "greater_than", "value": "50"},
        ),
        ("condition", {"field": "$.start.output.amount", "operator": "less_than", "value": True}),
        ("condition", {"field": "$.start.output.amount", "operator": "equals", "value": {}}),
        ("condition", {"field": "$.start.output.amount", "operator": "contains", "value": 123}),
        ("condition", {"field": "$.start.output.amount", "operator": "equals"}),
        (
            "condition",
            {"field": "$.start.output.amount", "operator": "equals", "value": float("inf")},
        ),
        (
            "condition",
            {"field": "$.start.output.amount", "operator": "equals", "value": "x" * 4097},
        ),
        ("calculator", {"operation": "add", "operands": [{"kind": "literal", "value": 1}]}),
        ("calculator", {"operation": "add", "operands": [{"kind": "literal", "value": 1}] * 21}),
        ("calculator", {"operation": "divide", "operands": [{"kind": "literal", "value": 1}] * 3}),
        ("calculator", {"operation": "multiply", "operands": [1, 2]}),
        (
            "calculator",
            {
                "operation": "add",
                "operands": [
                    {"kind": "literal", "value": "1"},
                    {"kind": "literal", "value": 2},
                ],
            },
        ),
        (
            "calculator",
            {
                "operation": "add",
                "operands": [
                    {"kind": "literal", "value": True},
                    {"kind": "literal", "value": 2},
                ],
            },
        ),
        (
            "calculator",
            {
                "operation": "add",
                "operands": [
                    {"kind": "literal", "value": float("nan")},
                    {"kind": "literal", "value": 2},
                ],
            },
        ),
        (
            "calculator",
            {
                "operation": "add",
                "operands": [
                    {"kind": "literal", "value": 1000000000001},
                    {"kind": "literal", "value": 2},
                ],
            },
        ),
        (
            "calculator",
            {
                "operation": "add",
                "operands": [
                    {"kind": "output", "path": "$.start.output.amount", "value": 1},
                    {"kind": "literal", "value": 2},
                ],
            },
        ),
    ],
)
def test_invalid_config_has_static_error_without_raw_values(node_type: str, config: object) -> None:
    with pytest.raises(InvalidNodeConfigError) as outcome:
        validate_node_config(node_type, config)
    assert str(outcome.value) == "The node configuration does not match its registered contract."
    assert outcome.value.__suppress_context__


@pytest.mark.parametrize(
    "node_type", ["llm", "http_agent", "approval", "webhook", "private-unknown"]
)
def test_unregistered_capabilities_are_not_invented(node_type: str) -> None:
    with pytest.raises(UnsupportedNodeTypeError) as outcome:
        validate_node_config(node_type, {})
    assert node_type not in str(outcome.value)


@pytest.mark.parametrize(
    "path",
    ["$.start.output", "$.node_1-a.output.CustomerID", "$.a.output.__class__"],
)
def test_references_are_case_preserving_dictionary_paths(path: str) -> None:
    assert TypeAdapter(OutputReference).validate_python(path) == path


@pytest.mark.parametrize(
    "path",
    [
        "start.output.amount",
        "$.start.input.amount",
        "$.start.output[0]",
        "$.start.output.*",
        "$.start.output..amount",
        "{{ start.output }}",
        "$.start.output + 1",
        "$.start.output.amount\n",
        " $.start.output.amount",
        "$.start.output.amount ",
        "$.__import__('os').output",
        "$." + "n" * 65 + ".output",
        "$.a.output" + ".a" * 17,
        "$.a.output." + "p" * 65,
        "$.a.output" + ("." + "b" * 63) * 8,
    ],
)
def test_reference_grammar_rejects_expression_or_unbounded_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(OutputReference).validate_python(path)


def test_catalog_is_fresh_and_all_configuration_schemas_are_self_contained() -> None:
    first = node_type_catalog()
    assert [item.type for item in first.items] == [
        "gmail_read",
        "agent",
        "http",
        "manual",
        "transform",
        "condition",
        "calculator",
        "groq",
        "classify",
        "extract",
        "json_parser",
        "merge",
        "end",
    ]
    for item in first.items:
        ready = item.type in {
            "manual",
            "transform",
            "condition",
            "calculator",
            "merge",
            "end",
            "groq",
            "json_parser",
            "classify",
            "extract",
            "http",
            "agent",
            "gmail_read",
        }
        assert item.execution_ready is ready
        assert item.capabilities == (
            ["validate_config", "execute"] if ready else ["validate_config"]
        )
    for item in first.items:
        schema = item.config_schema
        assert schema
        # Every generated local $ref resolves inside this schema, not API components.
        pending: list[JsonValue] = [schema]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if "$ref" in value:
                    reference = value["$ref"]
                    assert isinstance(reference, str) and reference.startswith("#/")
                    target: JsonValue = schema
                    for part in reference.removeprefix("#/").split("/"):
                        assert isinstance(target, dict)
                        target = target[part]
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
    first.items[0].config_schema["private_mutation"] = True
    first.items[0].output_handles.append("private-handle")
    first.items.clear()
    second = node_type_catalog()
    assert len(second.items) == 13
    assert "private_mutation" not in second.items[0].config_schema
    assert second.items[0].output_handles == ["default"]


def test_draft_saves_remain_independent_of_executable_config_validation() -> None:
    request = WorkflowCreateRequest.model_validate(
        {
            "name": "Unfinished",
            "definition": {
                "schema_version": "1.0",
                "nodes": [
                    {"id": "pending", "type": "calculator", "config": {}},
                    {"id": "later", "type": "llm", "config": {}},
                ],
                "edges": [],
            },
        }
    )
    assert request.definition is not None
    with pytest.raises(InvalidNodeConfigError):
        validate_node_config("calculator", {})


def test_previously_validated_but_changed_models_are_checked_again() -> None:
    valid = validate_node_config("transform", {"operation": "identity"})
    changed = valid.model_copy(update={"operation": "eval"})
    with pytest.raises(InvalidNodeConfigError):
        validate_node_config("transform", changed)
