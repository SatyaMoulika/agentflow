"""Synchronous pure-node runner with bounded retries and cooperative cancellation."""

from typing import Any
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.tracing import traced
from app.infrastructure.database.session import Database
from app.modules.agents.checkpoints import checkpoint_saver
from app.modules.agents.http_tools import AgentHttpTools
from app.modules.agents.models import AgentInvocation
from app.modules.agents.runner import AgentExecutionError, AgentPaused, execute_agent
from app.modules.connections.http_executor import get_json
from app.modules.connections.secrets import ConnectionUnavailableError
from app.modules.connections.service import ConnectionService
from app.modules.executions.dispatch_models import WorkflowDispatch
from app.modules.executions.exceptions import (
    ExecutionConflictError,
    ExecutionStorageUnavailableError,
)
from app.modules.executions.groq_provider import GroqError, complete
from app.modules.executions.operations import (
    NodeExecutionError,
    execute_node,
    next_node_id,
    resolve_config,
    resolve_input,
)
from app.modules.executions.payloads import copy_payload
from app.modules.executions.recovery import ReconstructedProgress
from app.modules.executions.repository import ExecutionRepository
from app.modules.executions.state import (
    RETRYABLE_FAILURE_CODES,
    EventType,
    FailureCode,
    NodeStatus,
    RunStatus,
)
from app.modules.executions.structured_tools import prepare, validate
from app.modules.gmail.provider import GmailProviderError
from app.modules.gmail.service import GmailConnectionNotFound, GmailNotConfigured, GmailService
from app.modules.workflows.compiler import CompiledNode, CompiledWorkflow
from app.modules.workflows.node_configs import AgentConfig

RETRY_SAFE_TYPES = frozenset(
    {"manual", "transform", "condition", "calculator", "merge", "end", "json_parser"}
)


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
        provider_metadata: dict[str, Any] | None = None,
        agent_metadata: dict[str, Any] | None = None,
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
                provider_metadata=provider_metadata,
                agent_metadata=agent_metadata,
            )
            invocation = session.get(AgentInvocation, attempt_id)
            if invocation is not None:
                invocation.status = "failed"
                if agent_metadata is not None and agent_metadata.get("checkpoint_id"):
                    invocation.checkpoint_id = agent_metadata["checkpoint_id"]
            if terminal:
                repository.transition_run(
                    run_id=run_id,
                    owner_id=owner_id,
                    expected_revision=1,
                    target=RunStatus.FAILED,
                    error_code=code,
                )

    @traced("agentflow.node")
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
        resume_attempt_id: UUID | None = None,
        resume_checkpoint_id: str | None = None,
    ) -> (
        tuple[dict[str, Any], str | None, UUID, dict[str, Any] | None, dict[str, Any] | None] | None
    ):
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
            thread_id = None
            with self.database.unit_of_work() as session:
                repository = ExecutionRepository(session)
                self._check(repository, run_id, owner_id)
                if resume_attempt_id is None:
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
                    if node.type == "agent" and mapping_error is None:
                        invocation = AgentInvocation(
                            node_run_id=attempt_id, workflow_run_id=run_id, thread_id=uuid4()
                        )
                        session.add(invocation)
                        session.flush()
                        thread_id = invocation.thread_id
                else:
                    attempt_id = resume_attempt_id
                    invocation = session.get(AgentInvocation, attempt_id)
                    if (
                        node.type != "agent"
                        or invocation is None
                        or invocation.workflow_run_id != run_id
                        or invocation.status != "running"
                        or invocation.checkpoint_id != resume_checkpoint_id
                        or mapping_error is not None
                    ):
                        raise ExecutionConflictError()
                    thread_id = invocation.thread_id
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
            provider_metadata = None
            agent_metadata = None
            try:
                if node.type == "agent":
                    assert thread_id is not None
                    if self.settings is None:
                        raise NodeExecutionError(FailureCode.PROVIDER_NOT_CONFIGURED)

                    def check_active() -> None:
                        with self.database.unit_of_work() as active_session:
                            self._check(ExecutionRepository(active_session), run_id, owner_id)

                    try:
                        agent_config = AgentConfig.model_validate(config)
                        with checkpoint_saver(self.database) as saver:
                            output, agent_metadata = execute_agent(
                                self.settings,
                                agent_config,
                                resolved.get(config["input_field"]),
                                check_active=check_active,
                                http_tools=AgentHttpTools(
                                    self.database,
                                    self.settings,
                                    owner_id,
                                    agent_config.connection_ids,
                                ),
                                checkpointer=saver,
                                thread_id=str(thread_id),
                                resume_checkpoint_id=resume_checkpoint_id,
                            )
                    except AgentPaused as pause:
                        with self.database.unit_of_work() as session:
                            repository = ExecutionRepository(session)
                            self._check(repository, run_id, owner_id)
                            run = repository.lock_owned(run_id=run_id, owner_id=owner_id)
                            invocation = session.get(AgentInvocation, attempt_id)
                            if invocation is None or invocation.status != "running":
                                raise ExecutionConflictError() from None
                            invocation.status = "paused"
                            invocation.checkpoint_id = pause.checkpoint_id
                            repository._event(
                                run,
                                EventType.AGENT_CHECKPOINTED,
                                {"checkpoint_id": pause.checkpoint_id, "agent": pause.metadata},
                                attempt_id,
                            )
                        return None
                    except AgentExecutionError as error:
                        agent_metadata = error.metadata
                        raise
                elif node.type == "gmail_read":
                    message_id = resolved.get(config["message_id_field"])
                    if self.settings is None or not isinstance(message_id, str):
                        raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE)
                    try:
                        text = GmailService(self.database, self.settings).read_message(
                            owner_id, UUID(config["connection_id"]), message_id
                        )
                        output = copy_payload({"text": text, "message_id": message_id})
                    except (
                        GmailConnectionNotFound,
                        GmailNotConfigured,
                        GmailProviderError,
                        ConnectionUnavailableError,
                        ValueError,
                    ):
                        raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE) from None
                elif node.type == "http":
                    if self.settings is None:
                        raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE)
                    try:
                        connection = ConnectionService(self.database, self.settings).authorize(
                            owner_id, UUID(config["connection_id"])
                        )
                    except ConnectionUnavailableError:
                        raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE) from None
                    output = get_json(connection)
                elif node.type == "groq":
                    value = resolved.get(config["input_field"])
                    if not isinstance(value, str) or not value.strip() or self.settings is None:
                        raise NodeExecutionError()
                    prompt = f"{config['instruction']}\n\n{value}"
                    if len(prompt) > 4000:
                        raise NodeExecutionError()
                    try:
                        result = complete(self.settings, prompt)
                        provider_metadata = result.get("metadata")
                        output = copy_payload(
                            {"model": result["model"], "content": result["content"]}
                        )
                    except GroqError as error:
                        provider_metadata = error.metadata
                        raise NodeExecutionError(FailureCode(error.code)) from None
                elif node.type in {"classify", "extract"}:
                    if self.settings is None:
                        raise NodeExecutionError()
                    prompt = prepare(node.type, config, resolved.get(config["input_field"]))
                    try:
                        result = complete(self.settings, prompt, json_mode=True)
                    except GroqError as error:
                        provider_metadata = error.metadata
                        raise NodeExecutionError(FailureCode(error.code)) from None
                    provider_metadata = result.get("metadata")
                    output = copy_payload(validate(node.type, config, result))
                else:
                    output = copy_payload(
                        execute_node(
                            node, copy_payload(resolved), resolved_config=copy_payload(config)
                        )
                    )
                following = next_node_id(node, output)
                if following is not None and (following in visited or following not in nodes):
                    raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
                return output, following, attempt_id, provider_metadata, agent_metadata
            except ExecutionStorageUnavailableError:
                raise ExecutionStorageUnavailableError(run_id) from None
            except _Cancelled:
                raise
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
                provider_metadata=provider_metadata,
                agent_metadata=agent_metadata,
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
        visited: set[str] = set()
        current = plan.entry_node_id
        self._continue(
            run_id=run_id,
            owner_id=owner_id,
            plan=plan,
            incoming=incoming,
            outputs=outputs,
            visited=visited,
            current=current,
            max_attempts=max_attempts,
        )

    def continue_agent(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        plan: CompiledWorkflow,
        progress: ReconstructedProgress,
        attempt_id: UUID,
        checkpoint_id: str,
        max_attempts: int,
    ) -> None:
        assert progress.next_node_id is not None
        try:
            self._continue(
                run_id=run_id,
                owner_id=owner_id,
                plan=plan,
                incoming=progress.incoming,
                outputs=progress.outputs,
                visited=set(progress.visited),
                current=progress.next_node_id,
                max_attempts=max_attempts,
                resume_attempt_id=attempt_id,
                resume_checkpoint_id=checkpoint_id,
            )
        except _Cancelled:
            return

    def _continue(
        self,
        *,
        run_id: UUID,
        owner_id: UUID,
        plan: CompiledWorkflow,
        incoming: dict[str, Any],
        outputs: dict[str, dict[str, Any]],
        visited: set[str],
        current: str,
        max_attempts: int,
        resume_attempt_id: UUID | None = None,
        resume_checkpoint_id: str | None = None,
    ) -> None:
        nodes = {node.id: node for node in plan.nodes}
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
                resume_attempt_id=resume_attempt_id,
                resume_checkpoint_id=resume_checkpoint_id,
            )
            resume_attempt_id, resume_checkpoint_id = None, None
            if result is None:
                return
            output, following, attempt_id, provider_metadata, agent_metadata = result
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
                    provider_metadata=provider_metadata,
                    agent_metadata=agent_metadata,
                )
                invocation = session.get(AgentInvocation, attempt_id)
                if invocation is not None:
                    invocation.status = "completed"
                    if agent_metadata is not None:
                        invocation.checkpoint_id = agent_metadata.get("checkpoint_id")
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
