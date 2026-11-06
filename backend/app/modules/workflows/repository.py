"""Owner-scoped workflow persistence and serialized version appends; no commits."""

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import Workflow, WorkflowStatus, WorkflowVersion
from app.modules.workflows.exceptions import WorkflowNotFoundError, WorkflowVersionConflictError


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *, owner_id: UUID, name: str, description: str = "") -> Workflow:
        """Insert draft metadata; first-version creation shares the caller's transaction."""
        workflow = Workflow(owner_id=owner_id, name=name, description=description)
        self.session.add(workflow)
        self.session.flush()
        return workflow

    def get_owned(self, *, workflow_id: UUID, owner_id: UUID) -> Workflow | None:
        return self.session.scalar(
            select(Workflow).where(Workflow.id == workflow_id, Workflow.owner_id == owner_id)
        )

    def lock_owned(self, *, workflow_id: UUID, owner_id: UUID) -> Workflow | None:
        """Refresh state under an owner-scoped lock, preserving pending same-UoW edits."""
        self.session.flush()
        return self.session.scalar(
            select(Workflow)
            .where(Workflow.id == workflow_id, Workflow.owner_id == owner_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def page_owned(
        self,
        *,
        owner_id: UUID,
        page: int,
        page_size: int,
        status: WorkflowStatus | None,
        query: str | None,
    ) -> tuple[list[Workflow], int]:
        if not 1 <= page <= 1000000 or not 1 <= page_size <= 100:
            raise ValueError("Invalid pagination bounds")
        filters = [Workflow.owner_id == owner_id]
        filters.append(
            Workflow.status == status
            if status is not None
            else Workflow.status != WorkflowStatus.ARCHIVED
        )
        if query is not None:
            filters.append(Workflow.name.icontains(query, autoescape=True))
        total = int(
            self.session.scalar(select(func.count()).select_from(Workflow).where(*filters)) or 0
        )
        rows = self.session.scalars(
            select(Workflow)
            .where(*filters)
            .order_by(Workflow.updated_at.desc(), Workflow.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
        return list(rows), total

    def update_metadata(
        self, workflow: Workflow, *, name: str | None, description: str | None
    ) -> None:
        """Caller holds lock_owned and has checked lifecycle policy."""
        if name is not None:
            workflow.name = name
        if description is not None:
            workflow.description = description
        self.session.flush()

    def archive(self, workflow: Workflow) -> None:
        """Archive metadata only; preserve pointer and every immutable version."""
        if workflow.status != WorkflowStatus.ARCHIVED:
            workflow.status = WorkflowStatus.ARCHIVED
            self.session.flush()

    def list_owned(self, *, owner_id: UUID, limit: int = 25, offset: int = 0) -> list[Workflow]:
        """Bounded, deterministic metadata listing; archived rows are included for now."""
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be between 1 and 100 and offset must be nonnegative")
        return list(
            self.session.scalars(
                select(Workflow)
                .where(Workflow.owner_id == owner_id)
                .order_by(Workflow.updated_at.desc(), Workflow.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    def get_version_owned(
        self, *, workflow_id: UUID, version_id: UUID, owner_id: UUID
    ) -> WorkflowVersion | None:
        return self.session.scalar(
            select(WorkflowVersion)
            .join(Workflow, WorkflowVersion.workflow_id == Workflow.id)
            .where(
                Workflow.id == workflow_id,
                Workflow.owner_id == owner_id,
                WorkflowVersion.id == version_id,
            )
        )

    def append_version(
        self,
        *,
        workflow_id: UUID,
        owner_id: UUID,
        expected_version: int,
        definition: dict[str, Any],
    ) -> WorkflowVersion:
        """Lock/check current state, insert a snapshot and advance the pointer atomically.

        expected_version=0 represents a versionless draft. The caller must let any
        failure escape its unit of work; this method never commits or retries.
        """
        if expected_version < 0:
            raise ValueError("expected_version must be nonnegative")
        # populate_existing refreshes cached attributes; do not silently discard
        # pending metadata edits in this same caller-owned transaction.
        workflow = self.lock_owned(workflow_id=workflow_id, owner_id=owner_id)
        if workflow is None:
            raise WorkflowNotFoundError()
        current_number = (
            self.session.scalar(
                select(WorkflowVersion.version_number).where(
                    WorkflowVersion.id == workflow.current_version_id,
                    WorkflowVersion.workflow_id == workflow.id,
                )
            )
            if workflow.current_version_id is not None
            else 0
        )
        if current_number != expected_version:
            raise WorkflowVersionConflictError()

        # Allocate from history, not the pointer, so a manually moved pointer cannot
        # reuse a saved number. Cooperating writers all hold this workflow's lock.
        latest_number = (
            self.session.scalar(
                select(func.max(WorkflowVersion.version_number)).where(
                    WorkflowVersion.workflow_id == workflow.id
                )
            )
            or 0
        )
        version = WorkflowVersion(
            workflow_id=workflow.id,
            created_by=owner_id,
            version_number=latest_number + 1,
            definition_json=deepcopy(definition),
        )
        self.session.add(version)
        self.session.flush()
        workflow.current_version_id = version.id
        self.session.flush()
        # Avoid returning stale navigation/defaults to code in the same unit of work.
        self.session.expire(workflow, ["current_version", "versions", "updated_at"])
        return version
