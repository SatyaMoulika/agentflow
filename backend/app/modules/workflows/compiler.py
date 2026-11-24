"""Bounded DAG compilation; never executes nodes, resolves values or writes storage."""

from __future__ import annotations

import heapq
import json
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from app.modules.workflows.graph_schemas import GraphEdge, GraphNode
from app.modules.workflows.node_registry import (
    BACKGROUND_READY_TYPES,
    InvalidNodeConfigError,
    NodeTypeId,
    UnsupportedNodeTypeError,
    node_output_handles,
    validate_node_config,
)
from app.modules.workflows.schemas import WorkflowDefinition
from app.modules.workflows.validation_schemas import WorkflowValidationIssue

_MESSAGES = {
    "APPROVAL_REQUIRES_PURE_GRAPH": "Approval workflows currently support only pure nodes.",
    "INVALID_DEFINITION": "The definition does not match the supported graph envelope.",
    "EMPTY_GRAPH": "Provide at least one node.",
    "INVALID_NODE": "The node does not match the supported node envelope.",
    "UNSUPPORTED_NODE_TYPE": "The node type has no supported configuration contract.",
    "INVALID_NODE_CONFIG": "The node configuration does not match its registered contract.",
    "DUPLICATE_NODE_ID": "Node identifiers must be unique.",
    "INVALID_EDGE": "The edge does not match the supported edge envelope.",
    "DUPLICATE_EDGE_ID": "Edge identifiers must be unique.",
    "DUPLICATE_EDGE": "The same source, handle and target route is repeated.",
    "INVALID_EDGE_ENDPOINT": "Both edge endpoints must belong to this graph.",
    "SELF_EDGE": "An edge cannot connect a node to itself.",
    "INVALID_ENTRY_COUNT": "Exactly one manual entry node is required.",
    "MISSING_END": "At least one end node is required.",
    "INVALID_OUTPUT_HANDLES": "Outgoing routes must match the node's declared handles exactly.",
    "INVALID_INCOMING_EDGES": "Incoming routes do not match this node's entry or merge policy.",
    "CYCLE": "The graph must be acyclic.",
    "UNREACHABLE_NODE": "Every node must be reachable from the manual entry.",
    "REFERENCE_NOT_AVAILABLE": "A reference must name an output available on every incoming path.",
    "NO_SAVED_DEFINITION": "The workflow has no current saved definition to validate.",
}


def validation_issue(code: str, path: str = "definition") -> WorkflowValidationIssue:
    """Only code-owned messages and structural paths may reach public reports."""
    return WorkflowValidationIssue(code=code, message=_MESSAGES[code], path=path)


class _Diagnostics:
    def __init__(self) -> None:
        self.items: list[WorkflowValidationIssue] = []
        self.truncated = False

    def add(self, code: str, path: str = "definition") -> None:
        if len(self.items) < 100:
            self.items.append(validation_issue(code, path))
        else:
            self.truncated = True

    def invalid(self) -> CompilationResult:
        return CompilationResult(None, tuple(self.items), self.truncated)


@dataclass(frozen=True)
class CompiledBinding:
    """A future dictionary lookup, never an evaluated expression."""

    target_path: tuple[str | int, ...]
    source_node_id: str
    field_path: tuple[str, ...]


@dataclass(frozen=True)
class CompiledRoute:
    handle: str
    target_node_id: str


@dataclass(frozen=True)
class CompiledNode:
    id: str
    type: NodeTypeId
    config_json: str
    bindings: tuple[CompiledBinding, ...]
    routes: tuple[CompiledRoute, ...]


@dataclass(frozen=True)
class CompiledWorkflow:
    entry_node_id: str
    nodes: tuple[CompiledNode, ...]
    topological_order: tuple[str, ...]
    terminal_node_ids: tuple[str, ...]
    edge_count: int


@dataclass(frozen=True)
class CompilationResult:
    plan: CompiledWorkflow | None
    issues: tuple[WorkflowValidationIssue, ...]
    issues_truncated: bool = False

    @property
    def valid(self) -> bool:
        return self.plan is not None


def _nodes(
    raw_nodes: list[dict[str, Any]], diagnostics: _Diagnostics
) -> tuple[dict[str, GraphNode], dict[str, BaseModel], dict[str, int]]:
    nodes: dict[str, GraphNode] = {}
    configs: dict[str, BaseModel] = {}
    indices: dict[str, int] = {}
    for index, raw in enumerate(raw_nodes):
        path = f"nodes.{index}"
        try:
            node = GraphNode.model_validate(raw)
        except ValidationError:
            diagnostics.add("INVALID_NODE", path)
            continue
        if node.id in nodes:
            diagnostics.add("DUPLICATE_NODE_ID", f"{path}.id")
            continue
        nodes[node.id], indices[node.id] = node, index
        try:
            configs[node.id] = validate_node_config(node.type, node.config)
        except UnsupportedNodeTypeError:
            diagnostics.add("UNSUPPORTED_NODE_TYPE", f"{path}.type")
        except InvalidNodeConfigError:
            diagnostics.add("INVALID_NODE_CONFIG", f"{path}.config")
    return nodes, configs, indices


def _edges(
    raw_edges: list[dict[str, Any]], nodes: dict[str, GraphNode], diagnostics: _Diagnostics
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    identifiers: set[str] = set()
    routes: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_edges):
        path = f"edges.{index}"
        try:
            edge = GraphEdge.model_validate(raw)
        except ValidationError:
            diagnostics.add("INVALID_EDGE", path)
            continue
        if edge.id in identifiers:
            diagnostics.add("DUPLICATE_EDGE_ID", f"{path}.id")
        identifiers.add(edge.id)
        route = (edge.source, edge.source_handle, edge.target)
        if route in routes:
            diagnostics.add("DUPLICATE_EDGE", path)
        routes.add(route)
        if edge.source not in nodes or edge.target not in nodes:
            diagnostics.add("INVALID_EDGE_ENDPOINT", path)
        elif edge.source == edge.target:
            diagnostics.add("SELF_EDGE", path)
        else:
            edges.append(edge)
    return edges


def _topological_order(
    nodes: dict[str, GraphNode],
    outgoing: dict[str, list[GraphEdge]],
    incoming: dict[str, list[GraphEdge]],
) -> tuple[str, ...]:
    counts = {node_id: len(incoming[node_id]) for node_id in nodes}
    ready = [node_id for node_id, count in counts.items() if count == 0]
    heapq.heapify(ready)
    ordered: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for edge in outgoing[node_id]:
            counts[edge.target] -= 1
            if counts[edge.target] == 0:
                heapq.heappush(ready, edge.target)
    return tuple(ordered)


def _bindings(node: GraphNode, config: BaseModel) -> list[tuple[CompiledBinding, str]]:
    references: list[tuple[tuple[str | int, ...], str, str]] = [
        (("input_mapping", key), reference, "input_mapping")
        for key, reference in sorted(node.input_mapping.items())
    ]
    data = config.model_dump()
    if node.type == "condition":
        references.append((("config", "field"), data["field"], "config.field"))
    elif node.type == "calculator":
        for index, operand in enumerate(data["operands"]):
            if operand["kind"] == "output":
                references.append(
                    (
                        ("config", "operands", index, "path"),
                        operand["path"],
                        f"config.operands.{index}.path",
                    )
                )
    result: list[tuple[CompiledBinding, str]] = []
    for target, reference, public_path in references:
        parts = reference[2:].split(".")  # Syntax was already checked by typed contracts.
        result.append((CompiledBinding(target, parts[0], tuple(parts[2:])), public_path))
    return result


def compile_workflow(definition: dict[str, Any]) -> CompilationResult:
    """Compile only supported, bounded, sequential/exclusive DAG candidates."""
    diagnostics = _Diagnostics()
    try:
        envelope = WorkflowDefinition.model_validate(definition)
    except ValidationError:
        diagnostics.add("INVALID_DEFINITION")
        return diagnostics.invalid()
    raw = envelope.model_dump()
    if set(raw) - {"schema_version", "nodes", "edges", "metadata"} or (
        "metadata" in raw and not isinstance(raw["metadata"], dict)
    ):
        diagnostics.add("INVALID_DEFINITION")
        return diagnostics.invalid()
    if not envelope.nodes:
        diagnostics.add("EMPTY_GRAPH", "nodes")
        return diagnostics.invalid()
    nodes, configs, indices = _nodes(envelope.nodes, diagnostics)
    if any(node.type == "approval" for node in nodes.values()) and any(
        node.type not in BACKGROUND_READY_TYPES for node in nodes.values()
    ):
        diagnostics.add("APPROVAL_REQUIRES_PURE_GRAPH", "nodes")
    if diagnostics.items:
        return diagnostics.invalid()
    edges = _edges(envelope.edges, nodes, diagnostics)
    if diagnostics.items:
        return diagnostics.invalid()
    outgoing: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    incoming: dict[str, list[GraphEdge]] = {node_id: [] for node_id in nodes}
    for edge in edges:
        outgoing[edge.source].append(edge)
        incoming[edge.target].append(edge)
    entries = [node.id for node in nodes.values() if node.type == "manual"]
    if len(entries) != 1:
        diagnostics.add("INVALID_ENTRY_COUNT", "nodes")
    terminals = tuple(sorted(node.id for node in nodes.values() if node.type == "end"))
    if not terminals:
        diagnostics.add("MISSING_END", "nodes")
    for node_id, node in nodes.items():
        path = f"nodes.{indices[node_id]}"
        if sorted(edge.source_handle for edge in outgoing[node_id]) != sorted(
            node_output_handles(node.type)
        ):
            diagnostics.add("INVALID_OUTPUT_HANDLES", path)
        count = len(incoming[node_id])
        if (
            (node.type == "manual" and count != 0)
            or (node.type == "merge" and count < 2)
            or (node.type not in {"manual", "merge"} and count != 1)
        ):
            diagnostics.add("INVALID_INCOMING_EDGES", path)
    ordered = _topological_order(nodes, outgoing, incoming)
    if len(ordered) != len(nodes):
        diagnostics.add("CYCLE", "edges")
    if len(entries) == 1:
        reached: set[str] = set()
        pending = [entries[0]]
        while pending:
            node_id = pending.pop()
            if node_id not in reached:
                reached.add(node_id)
                pending.extend(edge.target for edge in outgoing[node_id])
        for node_id in sorted(nodes.keys() - reached):
            diagnostics.add("UNREACHABLE_NODE", f"nodes.{indices[node_id]}")
    if diagnostics.items:
        return diagnostics.invalid()

    entry = entries[0]
    dominators: dict[str, set[str]] = {entry: {entry}}
    compiled_nodes: list[CompiledNode] = []
    for node_id in ordered:
        if node_id != entry:
            parents = {edge.source for edge in incoming[node_id]}
            common = set.intersection(*(dominators[parent] for parent in sorted(parents)))
            dominators[node_id] = common | {node_id}
        node, config = nodes[node_id], configs[node_id]
        bindings = _bindings(node, config)
        for binding, path in bindings:
            if binding.source_node_id not in dominators[node_id] - {node_id}:
                diagnostics.add("REFERENCE_NOT_AVAILABLE", f"nodes.{indices[node_id]}.{path}")
        compiled_nodes.append(
            CompiledNode(
                id=node_id,
                type=cast(NodeTypeId, node.type),
                config_json=json.dumps(
                    config.model_dump(),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                bindings=tuple(binding for binding, _ in bindings),
                routes=tuple(
                    CompiledRoute(edge.source_handle, edge.target)
                    for edge in sorted(
                        outgoing[node_id],
                        key=lambda edge: (edge.source_handle, edge.target, edge.id),
                    )
                ),
            )
        )
    if diagnostics.items:
        return diagnostics.invalid()
    return CompilationResult(
        CompiledWorkflow(entry, tuple(compiled_nodes), ordered, terminals, len(edges)), ()
    )
