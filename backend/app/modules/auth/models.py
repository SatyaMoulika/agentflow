"""User storage, independent of HTTP response schemas and password hashing services."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, FetchedValue, String, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base

if TYPE_CHECKING:
    from app.modules.workflows.models import Workflow, WorkflowVersion


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(btrim(email)) AND length(email) > 0", name="email_normalized"
        ),
        CheckConstraint("length(btrim(password_hash)) > 0", name="password_hash_nonempty"),
        CheckConstraint("length(btrim(display_name)) > 0", name="display_name_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True, default=uuid4, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(1024))
    display_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=FetchedValue()
    )

    workflows: Mapped[list[Workflow]] = relationship(back_populates="owner", passive_deletes="all")
    created_versions: Mapped[list[WorkflowVersion]] = relationship(
        back_populates="creator", passive_deletes="all"
    )
