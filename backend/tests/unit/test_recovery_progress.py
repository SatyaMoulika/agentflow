"""Selected route reconstruction preserves committed results and refuses ambiguity."""

from copy import deepcopy

import pytest

from app.modules.executions.recovery import (
    InconsistentHistoryError,
    StoredAttempt,
    reconstruct_progress,
)
from app.modules.executions.state import NodeStatus
from app.modules.workflows.compiler import compile_workflow

GRAPH = {
    "schema_version": "1.0",
    "nodes": [
        {"id": "start", "type": "manual", "config": {}},
        {
            "id": "choose",
            "type": "condition",
            "config": {"field": "$.start.output.amount", "operator": "greater_than", "value": 10},
        },
        {"id": "high", "type": "transform", "config": {"operation": "identity"}},
        {"id": "low", "type": "transform", "config": {"operation": "identity"}},
        {"id": "merge", "type": "merge", "config": {}},
        {"id": "end", "type": "end", "config": {}},
    ],
    "edges": [
        {"id": "e1", "source": "start", "target": "choose"},
        {"id": "e2", "source": "choose", "source_handle": "true", "target": "high"},
        {"id": "e3", "source": "choose", "source_handle": "false", "target": "low"},
        {"id": "e4", "source": "high", "target": "merge"},
        {"id": "e5", "source": "low", "target": "merge"},
        {"id": "e6", "source": "merge", "target": "end"},
    ],
}


def plan():
    result = compile_workflow(deepcopy(GRAPH))
    assert result.plan is not None
    return result.plan


def row(node, status, output=None, number=1):
    return StoredAttempt(node, number, status, output)


@pytest.mark.parametrize(("chosen", "expected"), [(True, "high"), (False, "low")])
def test_reconstructs_chosen_branch_without_reexecution(chosen: bool, expected: str) -> None:
    source = {"amount": 11, "BusinessKey": {"case": "Value"}}
    attempts = [
        row("start", NodeStatus.SUCCEEDED, source),
        row("choose", NodeStatus.SUCCEEDED, {"result": chosen}),
    ]
    result = reconstruct_progress(plan(), source, attempts)
    assert result.state == "ready" and result.next_node_id == expected
    assert result.visited == ("start", "choose")
    assert result.outputs["start"] == source and result.incoming == {"result": chosen}
    source["BusinessKey"]["case"] = "changed"
    assert result.outputs["start"]["BusinessKey"]["case"] == "Value"


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (NodeStatus.PENDING, "interrupted"),
        (NodeStatus.RUNNING, "interrupted"),
        (NodeStatus.FAILED, "failed"),
    ],
)
def test_unfinished_attempt_requires_explicit_reconciliation(status, state) -> None:
    attempts = [row("start", NodeStatus.SUCCEEDED, {"amount": 11}), row("choose", status)]
    result = reconstruct_progress(plan(), {"amount": 11}, attempts)
    assert result.state == state and result.next_node_id == "choose" and result.attempts_used == 1


def test_retries_and_terminal_skips_preserve_actual_history() -> None:
    attempts = [
        row("start", NodeStatus.SUCCEEDED, {"amount": 11}),
        row("choose", NodeStatus.SUCCEEDED, {"result": True}),
        row("high", NodeStatus.FAILED),
        row("high", NodeStatus.SUCCEEDED, {"result": True}, 2),
        row("merge", NodeStatus.SUCCEEDED, {"result": True}),
        row("end", NodeStatus.SUCCEEDED, {"result": True}),
        row("low", NodeStatus.SKIPPED),
    ]
    progress = reconstruct_progress(plan(), {"amount": 11}, attempts)
    assert progress.state == "complete" and progress.next_node_id is None
    assert progress.visited == ("start", "choose", "high", "merge", "end")
    with pytest.raises(InconsistentHistoryError):
        reconstruct_progress(plan(), {"amount": 11}, attempts[:-1])


@pytest.mark.parametrize(
    "attempts",
    [
        [row("start", NodeStatus.SUCCEEDED, {"amount": 11}), row("low", NodeStatus.RUNNING)],
        [
            row("start", NodeStatus.SUCCEEDED, {"amount": 11}),
            row("start", NodeStatus.SUCCEEDED, {}, 2),
        ],
        [row("start", NodeStatus.FAILED, number=2)],
        [row("start", NodeStatus.SUCCEEDED, None)],
        [row("start", NodeStatus.CANCELLED)],
        [row("unknown", NodeStatus.RUNNING)],
        [
            row("start", NodeStatus.SUCCEEDED, {"amount": 11}),
            row("choose", NodeStatus.SUCCEEDED, {"result": "yes"}),
        ],
    ],
)
def test_inconsistent_or_unselected_history_fails_closed(attempts) -> None:
    with pytest.raises(InconsistentHistoryError):
        reconstruct_progress(plan(), {"amount": 11}, attempts)
