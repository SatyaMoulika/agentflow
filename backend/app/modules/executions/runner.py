"""Synchronous pure-node runner with bounded retries and cooperative cancellation."""

from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.exceptions import ExecutionConflictError
from app.modules.executions.groq_provider import GroqError, complete
from app.modules.executions.operations import (
    NodeExecutionError,
    execute_node,
    next_node_id,
    resolve_config,
    resolve_input,
)
from app.modules.executions.payloads import copy_payload
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import RETRYABLE_FAILURE_CODES, FailureCode, NodeStatus, RunStatus
from app.modules.workflows.compiler import CompiledNode, CompiledWorkflow

RETRY_SAFE_TYPES = frozenset({"manual", "transform", "condition", "calculator", "merge", "end"})


class _Cancelled(Exception):
    """A committed cancellation wins over any in-flight computation."""


class WorkflowRunner:
    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings

    @staticmethod
    def _check(repository: ExecutionRepository, run_id: UUID, owner_id: UUID) -> None:
        if repository.lock_owned(run_id=run_id, owner_id=owner_id).status == RunStatus.CANCELLED:
            raise _Cancelled()

    def _fail(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        attempt_id: UUID,
        attempt_revision: int,
        code: FailureCode,
        terminal: bool = True,
    ) -> None:
        with self.database.unit_of_work() as session:
            repository = ExecutionRepository(session)
            self._check(repository, run_id, owner_id)
            repository.transition_attempt(
                run_id=run_id,
                owner_id=owner_id,
                attempt_id=attempt_id,
                expected_run_revision=1,
                expected_revision=attempt_revision,
                target=NodeStatus.FAILED,
                error_code=code,
            )
            if terminal:
                repository.transition_run(
                    run_id=run_id,
                    owner_id=owner_id,
                    expected_revision=1,
                    target=RunStatus.FAILED,
                    error_code=code,
                )

    def _execute(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        node: CompiledNode,
        incoming: dict[str, Any],
        outputs: dict[str, dict[str, Any]],
        visited: set[str],
        nodes: dict[str, CompiledNode],
        max_attempts: int,
    ) -> tuple[dict[str, Any], str | None, UUID] | None:
        mapping_error = None
        config: dict[str, Any] = {}
        try:
            resolved = resolve_input(node, incoming, outputs)
            config = resolve_config(node, outputs)
        except NodeExecutionError as error:
            resolved, mapping_error = {}, error.code
        except Exception:
            resolved, mapping_error = {}, FailureCode.INTERNAL_FAILURE
        for number in range(1, max_attempts + 1):
            with self.database.unit_of_work() as session:
                repository = ExecutionRepository(session)
                self._check(repository, run_id, owner_id)
                attempt = repository.add_attempt(
                    run_id=run_id,
                    owner_id=owner_id,
                    expected_run_revision=1,
                    node_id=node.id,
                    input_json=resolved,
                )
                attempt_id = attempt.id
                repository.transition_attempt(
                    run_id=run_id,
                    owner_id=owner_id,
                    attempt_id=attempt_id,
                    expected_run_revision=1,
                    expected_revision=0,
                    target=NodeStatus.RUNNING if mapping_error is None else NodeStatus.FAILED,
                    error_code=mapping_error,
                )
                if mapping_error is not None:
                    repository.transition_run(
                        run_id=run_id,
                        owner_id=owner_id,
                        expected_revision=1,
                        target=RunStatus.FAILED,
                        error_code=mapping_error,
                    )
            if mapping_error is not None:
                return None
            code = None
            try:
                if node.type == "groq":
                    value = resolved.get(config["input_field"])
                    if not isinstance(value, str) or not value.strip() or self.settings is None:
                        raise NodeExecutionError()
                    prompt = f"{config['instruction']}\n\n{value}"
                    if len(prompt) > 4000:
                        raise NodeExecutionError()
                    try:
                        output = copy_payload(complete(self.settings, prompt))
                    except GroqError:
                        raise NodeExecutionError() from None
                else:
                    output = copy_payload(
                        execute_node(
                            node, copy_payload(resolved), resolved_config=copy_payload(config)
                        )
                    )
                following = next_node_id(node, output)
                if following is not None and (following in visited or following not in nodes):
                    raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
                return output, following, attempt_id
            except NodeExecutionError as error:
                code = error.code
            except Exception:
                code = FailureCode.INTERNAL_FAILURE
            # Deterministic input/config/arithmetic failures never benefit from retry.
            retry = (
                node.type in RETRY_SAFE_TYPES
                and number < max_attempts
                and code in RETRYABLE_FAILURE_CODES
            )
            self._fail(
                run_id=run_id,
                owner_id=owner_id,
                attempt_id=attempt_id,
                attempt_revision=1,
                code=code,
                terminal=not retry,
            )
            if not retry:
                return None
        return None

    def run(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        plan: CompiledWorkflow,
        input_data: dict[str, Any],
        max_attempts: int = 1,
    ) -> None:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("Invalid attempt budget")
        try:
            self._run(
                run_id=run_id,
                owner_id=owner_id,
                plan=plan,
                input_data=input_data,
                max_attempts=max_attempts,
            )
        except _Cancelled:
            # Cancellation closed all open attempts and the run in one transaction.
            return

    def _run(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        plan: CompiledWorkflow,
        input_data: dict[str, Any],
        max_attempts: int,
    ) -> None:
        with self.database.unit_of_work() as session:
            repository = ExecutionRepository(session)
            self._check(repository, run_id, owner_id)
            if session.get(WorkflowDispatch, run_id) is not None:
                raise ExecutionConflictError()
            if repository.lock_owned(run_id=run_id, owner_id=owner_id).max_attempts != max_attempts:
                raise ExecutionConflictError()
            repository.transition_run(
                run_id=run_id,
                owner_id=owner_id,
                expected_revision=0,
                target=RunStatus.RUNNING,
            )
        incoming = copy_payload(input_data)
        outputs: dict[str, dict[str, Any]] = {}
        nodes = {node.id: node for node in plan.nodes}
        visited: set[str] = set()
        current = plan.entry_node_id
        while True:
            node = nodes[current]
            visited.add(node.id)
            result = self._execute(
                run_id=run_id,
                owner_id=owner_id,
                node=node,
                incoming=incoming,
                outputs=outputs,
                visited=visited,
                nodes=nodes,
                max_attempts=max_attempts,
            )
            if result is None:
                return
            output, following, attempt_id = result
            with self.database.unit_of_work() as session:
                repository = ExecutionRepository(session)
                self._check(repository, run_id, owner_id)
                repository.transition_attempt(
                    run_id=run_id,
                    owner_id=owner_id,
                    attempt_id=attempt_id,
                    expected_run_revision=1,
                    expected_revision=1,
                    target=NodeStatus.SUCCEEDED,
                    output=output,
                )
                if node.type == "end":
                    for other in plan.nodes:
                        if other.id in visited:
                            continue
                        skipped = repository.add_attempt(
                            run_id=run_id,
                            owner_id=owner_id,
                            expected_run_revision=1,
                            node_id=other.id,
                            input_json={},
                        )
                        repository.transition_attempt(
                            run_id=run_id,
                            owner_id=owner_id,
                            attempt_id=skipped.id,
                            expected_run_revision=1,
                            expected_revision=0,
                            target=NodeStatus.SKIPPED,
                        )
                    repository.transition_run(
                        run_id=run_id,
                        owner_id=owner_id,
                        expected_revision=1,
                        target=RunStatus.SUCCEEDED,
                        output=output,
                    )
            outputs[node.id] = output
            incoming = output
            if following is None:
                return
            current = following
