"""Owner-scoped workflows and immutable drafts; each mutation owns its transaction."""

from uuid import UUID

from sqlalchemy.exc import OperationalError, TimeoutError

from app.infrastructure.database.session import Database
from app.modules.workflows.exceptions import (
    WorkflowArchivedError,
    WorkflowNotFoundError,
    WorkflowStorageUnavailableError,
)
from app.modules.workflows.models import Workflow, WorkflowStatus
from app.modules.workflows.repository import WorkflowRepository
from app.modules.workflows.schemas import (
    WorkflowCreateRequest,
    WorkflowDetailResponse,
    WorkflowListParams,
    WorkflowPage,
    WorkflowResponse,
    WorkflowUpdateRequest,
    WorkflowVersionResponse,
)


def _detail(
    repository: WorkflowRepository, workflow: Workflow, *, version_id: UUID | None = None
) -> WorkflowDetailResponse:
    """Pin snapshots to the metadata pointer already read, even across concurrent saves."""
    current = None
    if workflow.current_version_id is not None:
        current = repository.get_version_owned(
            workflow_id=workflow.id,
            owner_id=workflow.owner_id,
            version_id=workflow.current_version_id,
        )
        if current is None:
            raise RuntimeError("Workflow current version invariant failed")
    selected = current
    if version_id is not None and version_id != workflow.current_version_id:
        selected = repository.get_version_owned(
            workflow_id=workflow.id, owner_id=workflow.owner_id, version_id=version_id
        )
        if selected is None:
            raise WorkflowNotFoundError()
    return WorkflowDetailResponse(
        **WorkflowResponse.model_validate(workflow).model_dump(),
        current_version_number=current.version_number if current is not None else 0,
        version=WorkflowVersionResponse.model_validate(selected) if selected is not None else None,
    )


class WorkflowService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, *, owner_id: UUID, data: WorkflowCreateRequest) -> WorkflowDetailResponse:
        try:
            with self.database.unit_of_work() as session:
                repository = WorkflowRepository(session)
                workflow = repository.add(
                    owner_id=owner_id, name=data.name, description=data.description
                )
                if data.definition is not None:
                    repository.append_version(
                        workflow_id=workflow.id,
                        owner_id=owner_id,
                        expected_version=0,
                        definition=data.definition.model_dump(),
                    )
                result = _detail(repository, workflow)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None
        return result

    def get(
        self, *, workflow_id: UUID, owner_id: UUID, version_id: UUID | None = None
    ) -> WorkflowDetailResponse:
        try:
            with self.database.session() as session:
                repository = WorkflowRepository(session)
                workflow = repository.get_owned(workflow_id=workflow_id, owner_id=owner_id)
                if workflow is None:
                    raise WorkflowNotFoundError()
                return _detail(repository, workflow, version_id=version_id)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None

    def list(self, *, owner_id: UUID, params: WorkflowListParams) -> WorkflowPage:
        try:
            with self.database.session() as session:
                rows, total = WorkflowRepository(session).page_owned(
                    owner_id=owner_id,
                    page=params.page,
                    page_size=params.page_size,
                    status=params.status,
                    query=params.q,
                )
                return WorkflowPage(
                    items=[WorkflowResponse.model_validate(row) for row in rows],
                    total=total,
                    page=params.page,
                    page_size=params.page_size,
                )
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None

    def update(
        self, *, workflow_id: UUID, owner_id: UUID, data: WorkflowUpdateRequest
    ) -> WorkflowDetailResponse:
        try:
            with self.database.unit_of_work() as session:
                repository = WorkflowRepository(session)
                workflow = repository.lock_owned(workflow_id=workflow_id, owner_id=owner_id)
                if workflow is None:
                    raise WorkflowNotFoundError()
                if workflow.status == WorkflowStatus.ARCHIVED:
                    raise WorkflowArchivedError()
                repository.update_metadata(workflow, name=data.name, description=data.description)
                if data.definition is not None:
                    assert data.expected_version is not None  # Request enforces the pair.
                    repository.append_version(
                        workflow_id=workflow_id,
                        owner_id=owner_id,
                        expected_version=data.expected_version,
                        definition=data.definition.model_dump(),
                    )
                result = _detail(repository, workflow)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None
        return result

    def archive(self, *, workflow_id: UUID, owner_id: UUID) -> None:
        try:
            with self.database.unit_of_work() as session:
                repository = WorkflowRepository(session)
                workflow = repository.lock_owned(workflow_id=workflow_id, owner_id=owner_id)
                if workflow is None:
                    raise WorkflowNotFoundError()
                repository.archive(workflow)
        except (OperationalError, TimeoutError):
            raise WorkflowStorageUnavailableError() from None
