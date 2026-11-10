"""Lifecycle specification includes terminal immutability and reserved approval states."""

from itertools import product

import pytest

from app.modules.executions.state import (
    InvalidTransitionError,
    NodeStatus,
    RunStatus,
    require_node_transition,
    require_run_transition,
)

RUN_EDGES = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"waiting_approval", "succeeded", "failed", "cancelled"},
    "waiting_approval": {"running", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
}
NODE_EDGES = {
    "pending": {"running", "skipped", "failed", "cancelled"},
    "running": {"waiting_approval", "succeeded", "failed", "cancelled"},
    "waiting_approval": {"running", "succeeded", "failed", "cancelled"},
    "succeeded": set(),
    "failed": set(),
    "skipped": set(),
    "cancelled": set(),
}


@pytest.mark.parametrize(("current", "target"), list(product(RunStatus, repeat=2)))
def test_run_transition_specification(current: RunStatus, target: RunStatus) -> None:
    if target.value in RUN_EDGES[current.value]:
        require_run_transition(current, target)
    else:
        with pytest.raises(InvalidTransitionError):
            require_run_transition(current, target)


@pytest.mark.parametrize(("current", "target"), list(product(NodeStatus, repeat=2)))
def test_node_transition_specification(current: NodeStatus, target: NodeStatus) -> None:
    if target.value in NODE_EDGES[current.value]:
        require_node_transition(current, target)
    else:
        with pytest.raises(InvalidTransitionError):
            require_node_transition(current, target)
