"""Legal lifecycle transitions; failed attempts never restart in place."""

from enum import StrEnum
from types import MappingProxyType


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class FailureCode(StrEnum):
    EXECUTION_FAILED = "EXECUTION_FAILED"
    INPUT_MAPPING_FAILED = "INPUT_MAPPING_FAILED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    INTERNAL_FAILURE = "INTERNAL_FAILURE"


RETRYABLE_FAILURE_CODES = frozenset({FailureCode.INTERNAL_FAILURE, FailureCode.DEADLINE_EXCEEDED})


class EventType(StrEnum):
    RUN_CREATED = "run.created"
    RUN_STATUS_CHANGED = "run.status_changed"
    NODE_CREATED = "node.created"
    NODE_STATUS_CHANGED = "node.status_changed"
    NODE_RETRY_SCHEDULED = "node.retry_scheduled"


class InvalidTransitionError(Exception):
    def __init__(self) -> None:
        super().__init__("The execution state transition is not allowed.")


RUN_TRANSITIONS = MappingProxyType(
    {
        RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
        RunStatus.RUNNING: frozenset(
            {RunStatus.WAITING_APPROVAL, RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
        ),
        RunStatus.WAITING_APPROVAL: frozenset(
            {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
        ),
        RunStatus.SUCCEEDED: frozenset(),
        RunStatus.FAILED: frozenset(),
        RunStatus.CANCELLED: frozenset(),
    }
)
NODE_TRANSITIONS = MappingProxyType(
    {
        NodeStatus.PENDING: frozenset(
            {NodeStatus.RUNNING, NodeStatus.SKIPPED, NodeStatus.FAILED, NodeStatus.CANCELLED}
        ),
        NodeStatus.RUNNING: frozenset(
            {
                NodeStatus.WAITING_APPROVAL,
                NodeStatus.SUCCEEDED,
                NodeStatus.FAILED,
                NodeStatus.CANCELLED,
            }
        ),
        NodeStatus.WAITING_APPROVAL: frozenset(
            {NodeStatus.RUNNING, NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.CANCELLED}
        ),
        NodeStatus.SUCCEEDED: frozenset(),
        NodeStatus.FAILED: frozenset(),
        NodeStatus.SKIPPED: frozenset(),
        NodeStatus.CANCELLED: frozenset(),
    }
)
RUN_TERMINAL = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})
NODE_TERMINAL = frozenset(
    {NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.SKIPPED, NodeStatus.CANCELLED}
)


def require_run_transition(current: RunStatus, target: RunStatus) -> None:
    if not isinstance(current, RunStatus) or not isinstance(target, RunStatus):
        raise InvalidTransitionError()
    if target not in RUN_TRANSITIONS[current]:
        raise InvalidTransitionError()


def require_node_transition(current: NodeStatus, target: NodeStatus) -> None:
    if not isinstance(current, NodeStatus) or not isinstance(target, NodeStatus):
        raise InvalidTransitionError()
    if target not in NODE_TRANSITIONS[current]:
        raise InvalidTransitionError()
