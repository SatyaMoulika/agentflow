"""The compiler proves topology and reference availability without executing a graph."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest

from app.modules.workflows.compiler import compile_workflow


def _node(node_id: str, node_type: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    defaults: dict[str, dict[str, Any]] = {
        "manual": {},
        "transform": {"operation": "identity"},
        "condition": {"field": "$.start.output.flag", "operator": "equals", "value": True},
        "calculator": {
            "operation": "add",
            "operands": [{"kind": "literal", "value": 1}, {"kind": "literal", "value": 2}],
        },
        "merge": {},
        "end": {},
    }
    return {
        "id": node_id,
        "type": node_type,
        "config": deepcopy(defaults.get(node_type, {})) if config is None else config,
    }


def _edge(source: str, target: str, handle: str | None = None) -> dict[str, Any]:
    edge: dict[str, Any] = {
        "id": f"{source}_{handle or 'default'}_{target}",
        "source": source,
        "target": target,
    }
    if handle is not None:
        edge["source_handle"] = handle
    return edge


def _definition(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": "1.0", "nodes": nodes, "edges": edges}


def _linear() -> dict[str, Any]:
    return _definition(
        [_node("start", "manual"), _node("step", "transform"), _node("finish", "end")],
        [_edge("start", "step"), _edge("step", "finish")],
    )


def _diamond() -> dict[str, Any]:
    return _definition(
        [
            _node("start", "manual"),
            _node("choose", "condition"),
            _node("left", "transform"),
            _node("right", "transform"),
            _node("join", "merge"),
            _node("after", "calculator"),
            _node("finish", "end"),
        ],
        [
            _edge("start", "choose"),
            _edge("choose", "left", "true"),
            _edge("choose", "right", "false"),
            _edge("left", "join"),
            _edge("right", "join"),
            _edge("join", "after"),
            _edge("after", "finish"),
        ],
    )


def _find_node(definition: dict[str, Any], node_id: str) -> dict[str, Any]:
    return next(node for node in definition["nodes"] if node["id"] == node_id)


def _assert_invalid(definition: dict[str, Any], code: str) -> None:
    result = compile_workflow(definition)
    assert result.valid is False
    assert result.plan is None
    assert code in {issue.code for issue in result.issues}
    assert all(issue.message and isinstance(issue.path, str) for issue in result.issues)


def test_linear_plan_preserves_typed_config_without_executing_it() -> None:
    graph = _linear()
    _find_node(graph, "step")["config"] = {"operation": "pick_fields", "fields": ["CustomerID"]}
    result = compile_workflow(graph)
    assert result.valid is True
    assert result.issues == ()
    assert result.issues_truncated is False
    assert result.plan is not None
    assert result.plan.entry_node_id == "start"
    assert result.plan.topological_order == ("start", "step", "finish")
    assert result.plan.terminal_node_ids == ("finish",)
    assert result.plan.edge_count == 2
    assert tuple(node.id for node in result.plan.nodes) == result.plan.topological_order
    step = next(node for node in result.plan.nodes if node.id == "step")
    assert step.type == "transform"
    assert json.loads(step.config_json) == {"operation": "pick_fields", "fields": ["CustomerID"]}
    assert step.bindings == ()
    assert isinstance(step.routes, tuple)


def test_manual_can_finish_directly() -> None:
    graph = _definition(
        [_node("start", "manual"), _node("finish", "end")], [_edge("start", "finish")]
    )
    assert compile_workflow(graph).valid


def test_both_condition_branches_can_finish_without_reconverging() -> None:
    graph = _definition(
        [
            _node("start", "manual"),
            _node("choose", "condition"),
            _node("yes", "end"),
            _node("no", "end"),
        ],
        [_edge("start", "choose"), _edge("choose", "yes", "true"), _edge("choose", "no", "false")],
    )
    result = compile_workflow(graph)
    assert result.valid and result.plan is not None
    assert set(result.plan.terminal_node_ids) == {"yes", "no"}


def test_explicit_diamond_and_nested_diamond_compile() -> None:
    graph = _diamond()
    assert compile_workflow(graph).valid
    graph["nodes"].extend(
        [
            _node("inner", "condition"),
            _node("inner_left", "transform"),
            _node("inner_right", "transform"),
            _node("inner_join", "merge"),
        ]
    )
    graph["edges"].remove(_edge("left", "join"))
    graph["edges"].extend(
        [
            _edge("left", "inner"),
            _edge("inner", "inner_left", "true"),
            _edge("inner", "inner_right", "false"),
            _edge("inner_left", "inner_join"),
            _edge("inner_right", "inner_join"),
            _edge("inner_join", "join"),
        ]
    )
    assert compile_workflow(graph).valid


def test_both_exclusive_handles_may_enter_one_merge() -> None:
    graph = _definition(
        [
            _node("start", "manual"),
            _node("choose", "condition"),
            _node("join", "merge"),
            _node("finish", "end"),
        ],
        [
            _edge("start", "choose"),
            _edge("choose", "join", "true"),
            _edge("choose", "join", "false"),
            _edge("join", "finish"),
        ],
    )
    assert compile_workflow(graph).valid


def test_order_and_canonical_configs_are_independent_of_editor_array_order() -> None:
    graph = _diamond()
    original = compile_workflow(graph)
    shuffled = deepcopy(graph)
    shuffled["nodes"].reverse()
    shuffled["edges"].reverse()
    _find_node(shuffled, "choose")["config"] = {
        "value": True,
        "operator": "equals",
        "field": "$.start.output.flag",
    }
    assert compile_workflow(shuffled) == original


def test_presentation_metadata_is_accepted_without_becoming_runtime_configuration() -> None:
    graph = _linear()
    graph["metadata"] = {"editor": {"zoom": 1.25}, "business key": "preserved in saved draft"}
    _find_node(graph, "step").update(label="Customer view", position={"x": -1.5, "y": 20})
    result = compile_workflow(graph)
    assert result.valid and result.plan is not None
    step = next(node for node in result.plan.nodes if node.id == "step")
    assert json.loads(step.config_json) == {"operation": "identity"}


@pytest.mark.parametrize(
    "root_change",
    [
        {"schema_version": "2.0"},
        {"nodes": {}},
        {"edges": {}},
        {"metadata": []},
        {"execution_policy": {"allow_python": True}},
    ],
)
def test_invalid_envelope_or_unknown_semantic_fields_do_not_compile(
    root_change: dict[str, Any],
) -> None:
    graph = _linear()
    graph.update(root_change)
    _assert_invalid(graph, "INVALID_DEFINITION")


@pytest.mark.parametrize(
    "change",
    [
        {"id": "has.dot"},
        {"id": "9starts_with_number"},
        {"id": "bad\n"},
        {"id": 2},
        {"config": []},
        {"inputMapping": {}},
        {"retries": 2},
    ],
)
def test_node_shape_is_strict_and_does_not_silently_accept_editor_aliases(
    change: dict[str, Any],
) -> None:
    graph = _linear()
    _find_node(graph, "step").update(change)
    _assert_invalid(graph, "INVALID_NODE")


def test_unsupported_type_and_invalid_registered_config_have_distinct_static_codes() -> None:
    graph = _linear()
    _find_node(graph, "step")["type"] = "llm"
    _assert_invalid(graph, "UNSUPPORTED_NODE_TYPE")
    _find_node(graph, "step").update(
        type="calculator",
        config={
            "operation": "add",
            "operands": [
                {"kind": "literal", "value": "secret-numeric-string"},
                {"kind": "literal", "value": 2},
            ],
        },
    )
    result = compile_workflow(graph)
    assert not result.valid and result.plan is None
    assert "INVALID_NODE_CONFIG" in {issue.code for issue in result.issues}
    assert "secret-numeric-string" not in str(result.issues)


def test_duplicate_node_id_is_rejected_before_a_lookup_can_overwrite_it() -> None:
    graph = _linear()
    graph["nodes"].append(_node("step", "end"))
    _assert_invalid(graph, "DUPLICATE_NODE_ID")


@pytest.mark.parametrize(
    "change",
    [
        {"sourceHandle": "default"},
        {"target_handle": "default"},
        {"source_handle": None},
        {"source": 42},
        {"id": False},
    ],
)
def test_edge_shape_and_handle_naming_are_strict(change: dict[str, Any]) -> None:
    graph = _linear()
    graph["edges"][0].update(change)
    _assert_invalid(graph, "INVALID_EDGE")


def test_duplicate_edge_identity_and_duplicate_connection_are_rejected() -> None:
    graph = _linear()
    graph["edges"][1]["id"] = graph["edges"][0]["id"]
    _assert_invalid(graph, "DUPLICATE_EDGE_ID")
    graph = _linear()
    duplicate = deepcopy(graph["edges"][0])
    duplicate.update(id="second_identity", source_handle="default")
    graph["edges"].append(duplicate)
    _assert_invalid(graph, "DUPLICATE_EDGE")


def test_missing_endpoint_and_self_edge_are_rejected() -> None:
    graph = _linear()
    graph["edges"][0]["target"] = "missing"
    _assert_invalid(graph, "INVALID_EDGE_ENDPOINT")
    graph = _linear()
    graph["edges"][0]["target"] = "start"
    _assert_invalid(graph, "SELF_EDGE")


@pytest.mark.parametrize("entry_count", [0, 2])
def test_exactly_one_manual_entry_is_required(entry_count: int) -> None:
    graph = _linear()
    if entry_count == 0:
        _find_node(graph, "start").update(type="transform", config={"operation": "identity"})
    else:
        graph["nodes"].append(_node("second_start", "manual"))
    _assert_invalid(graph, "INVALID_ENTRY_COUNT")


def test_terminal_end_is_required() -> None:
    graph = _linear()
    _find_node(graph, "finish").update(type="transform", config={"operation": "identity"})
    _assert_invalid(graph, "MISSING_END")


@pytest.mark.parametrize("scenario", ["fanout", "dangling", "end_output", "unknown_handle"])
def test_default_nodes_are_sequential_and_ends_are_terminal(scenario: str) -> None:
    graph = _linear()
    if scenario == "fanout":
        graph["nodes"].append(_node("other_end", "end"))
        graph["edges"].append(_edge("step", "other_end"))
    elif scenario == "dangling":
        graph["edges"].pop()
    elif scenario == "end_output":
        graph["edges"].append(_edge("finish", "step"))
    else:
        graph["edges"][0]["source_handle"] = "approved"
    _assert_invalid(graph, "INVALID_OUTPUT_HANDLES")


@pytest.mark.parametrize("scenario", ["missing_false", "duplicate_true", "default"])
def test_condition_requires_one_edge_for_each_exclusive_handle(scenario: str) -> None:
    graph = _diamond()
    false_edge = next(edge for edge in graph["edges"] if edge.get("source_handle") == "false")
    if scenario == "missing_false":
        graph["edges"].remove(false_edge)
    else:
        false_edge["source_handle"] = "true" if scenario == "duplicate_true" else "default"
    _assert_invalid(graph, "INVALID_OUTPUT_HANDLES")


@pytest.mark.parametrize("join_type", ["transform", "end"])
def test_reconvergence_must_be_an_explicit_merge(join_type: str) -> None:
    graph = _diamond()
    _find_node(graph, "join").update(
        type=join_type, config={"operation": "identity"} if join_type == "transform" else {}
    )
    _assert_invalid(graph, "INVALID_INCOMING_EDGES")


def test_merge_with_only_one_incoming_edge_is_not_a_join() -> None:
    graph = _linear()
    _find_node(graph, "step").update(type="merge", config={})
    _assert_invalid(graph, "INVALID_INCOMING_EDGES")


def test_manual_entry_cannot_have_incoming_edges() -> None:
    graph = _linear()
    graph["edges"].append(_edge("finish", "start"))
    _assert_invalid(graph, "INVALID_INCOMING_EDGES")


def test_disconnected_nodes_and_disconnected_cycles_are_not_hidden_by_entry_traversal() -> None:
    graph = _linear()
    graph["nodes"].append(_node("unused", "end"))
    _assert_invalid(graph, "UNREACHABLE_NODE")
    graph = _linear()
    graph["nodes"].extend([_node("cycle_a", "transform"), _node("cycle_b", "transform")])
    graph["edges"].extend([_edge("cycle_a", "cycle_b"), _edge("cycle_b", "cycle_a")])
    _assert_invalid(graph, "CYCLE")


@pytest.mark.parametrize(
    "reference",
    [
        "$.left.output.total",
        "$.right.output.total",
        "$.after.output",
        "$.finish.output",
        "$.missing.output",
    ],
)
def test_merged_consumer_cannot_reference_branch_local_self_future_or_missing_output(
    reference: str,
) -> None:
    graph = _diamond()
    _find_node(graph, "after")["config"]["operands"][0] = {"kind": "output", "path": reference}
    _assert_invalid(graph, "REFERENCE_NOT_AVAILABLE")


@pytest.mark.parametrize("reference", ["$.start.output.total", "$.choose.output", "$.join.output"])
def test_outputs_that_dominate_a_merged_consumer_are_available(reference: str) -> None:
    graph = _diamond()
    _find_node(graph, "after")["config"]["operands"][0] = {"kind": "output", "path": reference}
    result = compile_workflow(graph)
    assert result.valid and result.plan is not None
    node = next(node for node in result.plan.nodes if node.id == "after")
    assert len(node.bindings) == 1


def test_sibling_branch_output_is_not_available_even_before_the_merge() -> None:
    graph = _diamond()
    _find_node(graph, "right")["input_mapping"] = {"invoice total": "$.left.output.total"}
    _assert_invalid(graph, "REFERENCE_NOT_AVAILABLE")


def test_dominance_applies_to_paths_reaching_the_consumer_not_other_terminated_paths() -> None:
    graph = _definition(
        [
            _node("start", "manual"),
            _node("choose", "condition"),
            _node("work", "transform"),
            _node("after", "transform"),
            _node("early_end", "end"),
            _node("finish", "end"),
        ],
        [
            _edge("start", "choose"),
            _edge("choose", "work", "true"),
            _edge("choose", "early_end", "false"),
            _edge("work", "after"),
            _edge("after", "finish"),
        ],
    )
    _find_node(graph, "after")["input_mapping"] = {"value": "$.work.output.total"}
    assert compile_workflow(graph).valid


def test_condition_reference_requires_an_available_output() -> None:
    graph = _diamond()
    _find_node(graph, "choose")["config"]["field"] = "$.left.output.flag"
    _assert_invalid(graph, "REFERENCE_NOT_AVAILABLE")


def test_path_looking_comparison_literals_and_selected_field_names_are_not_references() -> None:
    graph = _diamond()
    _find_node(graph, "choose")["config"]["value"] = "$.missing.output"
    _find_node(graph, "left")["config"] = {
        "operation": "pick_fields",
        "fields": ["$.also_missing.output"],
    }
    assert compile_workflow(graph).valid


def test_input_mapping_preserves_literal_business_keys_and_requires_output_references() -> None:
    graph = _linear()
    mapping = {"Customer ID": "$.start.output.CustomerID", "a.b": "$.start.output.nested.value"}
    _find_node(graph, "step")["input_mapping"] = mapping
    result = compile_workflow(graph)
    assert result.valid and result.plan is not None
    step = next(node for node in result.plan.nodes if node.id == "step")
    assert len(step.bindings) == 2
    _find_node(graph, "step")["input_mapping"]["Customer ID"] = "literal text"
    _assert_invalid(graph, "INVALID_NODE")


def test_compilation_neither_mutates_the_source_nor_retains_mutable_source_containers() -> None:
    graph = _linear()
    _find_node(graph, "step")["config"] = {"operation": "pick_fields", "fields": ["amount"]}
    _find_node(graph, "step")["input_mapping"] = {"payload": "$.start.output"}
    before = deepcopy(graph)
    result = compile_workflow(graph)
    assert result.valid and result.plan is not None
    assert graph == before
    plan = result.plan
    _find_node(graph, "step")["config"]["fields"].append("later")
    _find_node(graph, "step")["input_mapping"]["payload"] = "$.missing.output"
    graph["edges"].clear()
    assert plan == compile_workflow(before).plan
    with pytest.raises(FrozenInstanceError):
        cast(Any, plan).entry_node_id = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, plan.nodes[0]).id = "changed"
    assert isinstance(plan.nodes, tuple)
    assert all(
        isinstance(node.bindings, tuple) and isinstance(node.routes, tuple) for node in plan.nodes
    )


def test_issue_output_is_bounded_and_reports_truncation() -> None:
    graph = _definition(
        [_node("start", "manual"), _node("finish", "end")]
        + [_node(f"unsupported_{index}", "private-provider-name") for index in range(150)],
        [_edge("start", "finish")],
    )
    result = compile_workflow(graph)
    assert not result.valid and result.plan is None
    assert len(result.issues) == 100
    assert result.issues_truncated is True
    assert "private-provider-name" not in str(result.issues)


def test_arithmetic_is_not_evaluated_by_the_compiler() -> None:
    graph = _linear()
    _find_node(graph, "step").update(
        type="calculator",
        config={
            "operation": "divide",
            "operands": [{"kind": "literal", "value": 1}, {"kind": "literal", "value": 0}],
        },
    )
    assert compile_workflow(graph).valid
