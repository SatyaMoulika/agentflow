"""One durable claim slot per run, with a monotonic fencing generation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.database.base import Base


class RunClaim(Base):
    __tablename__ = "run_claims"
    __table_args__ = (
        CheckConstraint("generation >= 1", name="generation_positive"),
        CheckConstraint("(lease_token IS NULL) = (lease_until IS NULL)", name="lease_pair"),
        Index(
            "ix_run_claims_lease_until",
            "lease_until",
            postgresql_where=text("lease_until IS NOT NULL"),
        ),
    )
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="RESTRICT"), primary_key=True
    )
    generation: Mapped[int] = mapped_column(BigInteger)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
