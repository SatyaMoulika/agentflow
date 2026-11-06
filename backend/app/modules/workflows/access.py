"""Read-only ownership resolution; writes must still scope queries in their transaction."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import OperationalError, TimeoutError

from app.infrastructure.database.session import Database
from app.modules.workflows.exceptions import WorkflowNotFoundError, WorkflowStorageUnavailableError
from app.modules.workflows.repository import WorkflowRepository


@dataclass(frozen=True)
class OwnedWorkflow:
    workflow_id: UUID
    owner_id: UUID


@dataclass(frozen=True)
class OwnedWorkflowVersion:
    workflow_id: UUID
    version_id: UUID
    owner_id: UUID


class WorkflowAccessService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def require_workflow(self, *, workflow_id: UUID, owner_id: UUID) -> OwnedWorkflow:
        try:
            with self.database.session() as session:
                workflow = WorkflowRepository(session).get_owned(
                    workflow_id=workflow_id, owner_id=owner_id
                )
                if workflow is None:
                    raise WorkflowNotFoundError()
                return OwnedWorkflow(workflow.id, owner_id)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None

    def require_version(
        self, *, workflow_id: UUID, version_id: UUID, owner_id: UUID
    ) -> OwnedWorkflowVersion:
        try:
            with self.database.session() as session:
                version = WorkflowRepository(session).get_version_owned(
                    workflow_id=workflow_id, version_id=version_id, owner_id=owner_id
                )
                if version is None:
                    raise WorkflowNotFoundError()
                return OwnedWorkflowVersion(workflow_id, version.id, owner_id)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None
