"""Authorize and copy one exact candidate/snapshot, close storage, then compile."""

from copy import deepcopy
from uuid import UUID

from sqlalchemy.exc import OperationalError, TimeoutError

from app.infrastructure.database.session import Database
from app.modules.workflows.compiler import compile_workflow, validation_issue
from app.modules.workflows.exceptions import WorkflowNotFoundError, WorkflowStorageUnavailableError
from app.modules.workflows.node_registry import EXECUTION_READY_TYPES
from app.modules.workflows.repository import WorkflowRepository
from app.modules.workflows.validation_schemas import (
    WorkflowPlanSummary,
    WorkflowValidationRequest,
    WorkflowValidationResponse,
)


class WorkflowValidationService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def validate(
        self, *, workflow_id: UUID, owner_id: UUID, data: WorkflowValidationRequest
    ) -> WorkflowValidationResponse:
        source = "candidate" if data.definition is not None else "saved"
        version_id = None
        definition = None
        try:
            with self.database.session() as session:
                repository = WorkflowRepository(session)
                workflow = repository.get_owned(workflow_id=workflow_id, owner_id=owner_id)
                if workflow is None:
                    raise WorkflowNotFoundError()
                if data.definition is not None:
                    definition = data.definition.model_dump()
                else:
                    version_id = data.version_id or workflow.current_version_id
                    if version_id is not None:
                        version = repository.get_version_owned(
                            workflow_id=workflow_id, version_id=version_id, owner_id=owner_id
                        )
                        if version is None:
                            raise WorkflowNotFoundError()
                        definition = deepcopy(version.definition_json)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None
        if definition is None:
            return WorkflowValidationResponse(
                workflow_id=workflow_id,
                workflow_version_id=None,
                source=source,
                valid=False,
                issues=[validation_issue("NO_SAVED_DEFINITION")],
                issues_truncated=False,
                plan=None,
            )
        result = compile_workflow(definition)
        plan = result.plan
        return WorkflowValidationResponse(
            workflow_id=workflow_id,
            workflow_version_id=version_id,
            source=source,
            valid=result.valid,
            execution_ready=plan is not None
            and all(node.type in EXECUTION_READY_TYPES for node in plan.nodes),
            issues=list(result.issues),
            issues_truncated=result.issues_truncated,
            plan=WorkflowPlanSummary(
                entry_node_id=plan.entry_node_id,
                node_count=len(plan.nodes),
                edge_count=plan.edge_count,
                topological_order=list(plan.topological_order),
                terminal_node_ids=list(plan.terminal_node_ids),
            )
            if plan is not None
            else None,
        )
