"""Pure operations, dictionary mappings and command boundaries without storage."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.executions.runner import NodeExecutionError, execute_node, resolve_input
from app.modules.executions.schemas import RunCreateRequest
from app.modules.executions.state import FailureCode
from app.modules.workflows.compiler import CompiledBinding, CompiledNode


def transform(config: str, bindings: tuple[CompiledBinding, ...] = ()) -> CompiledNode:
    return CompiledNode("step", "transform", config, bindings, ())


@pytest.mark.parametrize("node_type", ["manual", "transform", "end"])
def test_identity_operations_copy_native_json_without_mutation(node_type: Any) -> None:
    data = {"CustomerID": 4, "nested": {"items": [False, None, 1.5]}, "text": "界"}
    original = deepcopy(data)
    node = CompiledNode("n", node_type, '{"operation":"identity"}', (), ())
    result = execute_node(node, data)
    assert result == data
    result["nested"]["items"].append("changed")
    assert data == original


def test_pick_fields_is_top_level_exact_and_preserves_nulls() -> None:
    result = execute_node(
        transform('{"operation":"pick_fields","fields":["A.B","empty","nested"]}'),
        {"A.B": 3, "a.b": 4, "empty": None, "nested": {"Id": 2}, "omit": True},
    )
    assert result == {"A.B": 3, "empty": None, "nested": {"Id": 2}}


def test_missing_pick_field_has_static_failure_not_a_partial_success() -> None:
    with pytest.raises(NodeExecutionError) as error:
        execute_node(transform('{"operation":"pick_fields","fields":["private-field"]}'), {})
    assert error.value.code == FailureCode.EXECUTION_FAILED
    assert "private-field" not in str(error.value)


def test_json_parser_preserves_business_keys_and_json_types() -> None:
    node = CompiledNode("parse", "json_parser", '{"input_field":"raw"}', (), ())
    assert execute_node(node, {"raw": '{"CustomerID":42,"value":[false,null]}'}) == {
        "CustomerID": 42,
        "value": [False, None],
    }


@pytest.mark.parametrize(
    "value", [None, 42, "[]", "not-json", '{"x":1,"x":2}', '{"x":NaN}', '"scalar"', "x" * 65537]
)
def test_json_parser_rejects_invalid_or_unbounded_input_without_leaking_it(value: Any) -> None:
    node = CompiledNode("parse", "json_parser", '{"input_field":"raw"}', (), ())
    with pytest.raises(NodeExecutionError) as error:
        execute_node(node, {"raw": value})
    assert error.value.code == FailureCode.EXECUTION_FAILED
    assert "not-json" not in str(error.value)


def test_mapping_replaces_incoming_and_uses_upstream_dictionary_keys_only() -> None:
    outputs = {"start": {"Account": {"ID": 10}, "nothing": None}}
    node = transform(
        '{"operation":"identity"}',
        (
            CompiledBinding(("input_mapping", "literal.dot"), "start", ("Account", "ID")),
            CompiledBinding(("input_mapping", "Null"), "start", ("nothing",)),
            CompiledBinding(("input_mapping", "Whole"), "start", ()),
        ),
    )
    result = resolve_input(node, {"discard": True}, outputs)
    assert result == {"literal.dot": 10, "Null": None, "Whole": outputs["start"]}
    result["Whole"]["Account"]["ID"] = 20
    assert outputs["start"]["Account"]["ID"] == 10


@pytest.mark.parametrize(
    ("source", "path", "outputs"),
    [
        ("missing", (), {}),
        ("start", ("missing",), {"start": {}}),
        ("start", ("items", "length"), {"start": {"items": [1]}}),
        ("start", ("item", "x"), {"start": {"item": None}}),
        ("start", ("item", "real"), {"start": {"item": 1}}),
    ],
)
def test_missing_or_non_dictionary_mapping_is_a_safe_error(
    source: str, path: tuple[str, ...], outputs: dict
) -> None:
    node = transform("{}", (CompiledBinding(("input_mapping", "value"), source, path),))
    with pytest.raises(NodeExecutionError) as error:
        resolve_input(node, {}, outputs)
    assert error.value.code == FailureCode.INPUT_MAPPING_FAILED


@pytest.mark.parametrize(
    "input_data", [None, [], "private-input", {"bad": float("inf")}, {"large": "x" * 262144}]
)
def test_run_input_must_be_bounded_native_json_object(input_data: Any) -> None:
    with pytest.raises(ValidationError) as error:
        RunCreateRequest.model_validate({"workflow_version_id": str(uuid4()), "input": input_data})
    assert "private-input" not in str(error.value)


def test_command_requires_exact_version_and_copies_input_without_key_conversion() -> None:
    original = {"InvoiceID": [1, False, None]}
    version_id = uuid4()
    command = RunCreateRequest.model_validate(
        {"workflow_version_id": str(version_id), "input": original}
    )
    original["InvoiceID"].append(99)
    assert command.workflow_version_id == version_id
    assert command.input == {"InvoiceID": [1, False, None]}
    for body in (
        {"input": {}},
        {"workflow_version_id": str(version_id)},
        {"workflow_version_id": None, "input": {}},
    ):
        with pytest.raises(ValidationError):
            RunCreateRequest.model_validate(body)
