"""Reconstruct a pure selected route from stored attempts without executing nodes."""

from dataclasses import dataclass
from typing import Any, Literal

from app.modules.executions.operations import NodeExecutionError, next_node_id
from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload
from app.modules.executions.state import NodeStatus
from app.modules.workflows.compiler import CompiledWorkflow


class InconsistentHistoryError(Exception):
    """Stored attempts cannot safely describe a single selected route."""


@dataclass(frozen=True)
class StoredAttempt:
    node_id: str
    attempt_number: int
    status: NodeStatus
    output: dict[str, Any] | None


@dataclass(frozen=True)
class ReconstructedProgress:
    state: Literal["ready", "interrupted", "failed", "complete"]
    next_node_id: str | None
    incoming: dict[str, Any]
    outputs: dict[str, dict[str, Any]]
    visited: tuple[str, ...]
    attempts_used: int


def reconstruct_progress(
    plan: CompiledWorkflow, input_data: dict[str, Any], attempts: list[StoredAttempt]
) -> ReconstructedProgress:
    """Read committed successful outputs; never retry or guess ambiguous attempt outcomes.

    Callers must supply the exact compiled run version and an owner-authorized, coherent
    snapshot of run and attempt history, obtained while holding the run row lock.
    This function is not a worker, checkpoint writer, or authorization boundary.
    """
    try:
        return _reconstruct(plan, input_data, attempts)
    except (InvalidExecutionPayloadError, NodeExecutionError, KeyError, TypeError, ValueError):
        raise InconsistentHistoryError("Run history cannot be safely reconstructed.") from None


def _reconstruct(
    plan: CompiledWorkflow, input_data: dict[str, Any], attempts: list[StoredAttempt]
) -> ReconstructedProgress:
    nodes = {node.id: node for node in plan.nodes}
    if len(nodes) != len(plan.nodes) or plan.entry_node_id not in nodes:
        raise InconsistentHistoryError("Invalid compiled graph.")
    by_node: dict[str, list[StoredAttempt]] = {}
    for attempt in attempts:
        if attempt.node_id not in nodes or not isinstance(attempt.status, NodeStatus):
            raise InconsistentHistoryError("Unknown node or attempt status.")
        rows = by_node.setdefault(attempt.node_id, [])
        if type(attempt.attempt_number) is not int or attempt.attempt_number != len(rows) + 1:
            raise InconsistentHistoryError("Non-contiguous attempt history.")
        if rows and rows[-1].status != NodeStatus.FAILED:
            raise InconsistentHistoryError("Only a failed attempt can precede another attempt.")
        if rows and attempt.status == NodeStatus.SKIPPED:
            raise InconsistentHistoryError("A previously attempted node cannot be skipped.")
        if (attempt.status == NodeStatus.SUCCEEDED) != (attempt.output is not None):
            raise InconsistentHistoryError("Attempt output is inconsistent with its status.")
        rows.append(attempt)
    incoming = copy_payload(input_data)
    outputs: dict[str, dict[str, Any]] = {}
    visited: list[str] = []
    node_id: str | None = plan.entry_node_id
    state: Literal["ready", "interrupted", "failed", "complete"] = "ready"
    attempts_used = 0
    while node_id is not None:
        if node_id in visited or node_id not in nodes:
            raise InconsistentHistoryError("Invalid route.")
        rows = by_node.get(node_id, [])
        if not rows:
            state = "ready"
            break
        latest = rows[-1]
        attempts_used = latest.attempt_number
        if latest.status in {NodeStatus.PENDING, NodeStatus.RUNNING}:
            state = "interrupted"
            break
        if latest.status == NodeStatus.FAILED:
            state = "failed"
            break
        if latest.status != NodeStatus.SUCCEEDED or latest.output is None:
            raise InconsistentHistoryError("A selected node is not recoverable.")
        output = copy_payload(latest.output)
        visited.append(node_id)
        outputs[node_id] = output
        incoming = copy_payload(output)
        node_id = next_node_id(nodes[node_id], output)
        attempts_used = 0
    else:
        state = "complete"
    allowed = set(visited)
    if node_id is not None:
        allowed.add(node_id)
    for attempt in attempts:
        if attempt.node_id not in allowed:
            if state != "complete" or attempt.status != NodeStatus.SKIPPED:
                raise InconsistentHistoryError("Attempts exist outside the selected route.")
    if state == "complete" and set(by_node) != set(nodes):
        raise InconsistentHistoryError("Completed history is missing skipped nodes.")
    selected_order = visited + ([node_id] if node_id is not None else [])
    route_position = {item: index for index, item in enumerate(selected_order)}
    last_position = -1
    seen_skip = False
    for attempt in attempts:
        if attempt.status == NodeStatus.SKIPPED:
            seen_skip = True
            continue
        if seen_skip or route_position[attempt.node_id] < last_position:
            raise InconsistentHistoryError("Attempt order is inconsistent with selected route.")
        last_position = route_position[attempt.node_id]
    return ReconstructedProgress(state, node_id, incoming, outputs, tuple(visited), attempts_used)
