"""Mutable workflow metadata and immutable JSONB definition snapshots."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    FetchedValue,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from app.modules.auth.models import User


class WorkflowStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_nonempty"),
        ForeignKeyConstraint(
            ["id", "current_version_id"],
            ["workflow_versions.workflow_id", "workflow_versions.id"],
            name="fk_workflows_current_version",
            use_alter=True,
            ondelete="RESTRICT",
        ),
        Index("ix_workflows_owner_updated_id", "owner_id", "updated_at", "id"),
        Index("ix_workflows_owner_status_updated_id", "owner_id", "status", "updated_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, server_default=text("''"))
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(
            WorkflowStatus,
            values_callable=lambda values: [value.value for value in values],
            native_enum=False,
            create_constraint=True,
            name="workflow_status",
            length=16,
        ),
        server_default=text("'draft'"),
    )
    current_version_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )

    owner: Mapped[User] = relationship(back_populates="workflows")
    versions: Mapped[list[WorkflowVersion]] = relationship(
        back_populates="workflow",
        foreign_keys="WorkflowVersion.workflow_id",
        passive_deletes="all",
        order_by="WorkflowVersion.version_number",
    )
    current_version: Mapped[WorkflowVersion | None] = relationship(
        primaryjoin=(
            "and_(Workflow.id == WorkflowVersion.workflow_id, "
            "Workflow.current_version_id == WorkflowVersion.id)"
        ),
        foreign_keys=[current_version_id],
        viewonly=True,
        uselist=False,
    )


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "version_number", name="uq_workflow_versions_workflow_number"
        ),
        UniqueConstraint("workflow_id", "id", name="uq_workflow_versions_workflow_id"),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        CheckConstraint("schema_version = '1.0'", name="schema_version_supported"),
        CheckConstraint("jsonb_typeof(definition_json) = 'object'", name="definition_object"),
        CheckConstraint(
            "definition_json ->> 'schema_version' IS NOT NULL "
            "AND jsonb_typeof(definition_json -> 'schema_version') = 'string' "
            "AND definition_json ->> 'schema_version' = schema_version",
            name="definition_schema_matches",
        ),
        Index("ix_workflow_versions_created_by", "created_by"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"))
    version_number: Mapped[int]
    definition_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schema_version: Mapped[str] = mapped_column(String(10), server_default=text("'1.0'"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow: Mapped[Workflow] = relationship(back_populates="versions", foreign_keys=[workflow_id])
    creator: Mapped[User] = relationship(back_populates="created_versions")
