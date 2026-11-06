"""Short transactions and fenced leases for at-least-once outbox publication."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.modules.outbox.models import OutboxMessage


@dataclass(frozen=True)
class ClaimedMessage:
    id: UUID
    lease_token: UUID
    kind: str = "transport_probe"


class OutboxRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def enqueue_probe(self) -> UUID:
        """The caller owns commit; a rollback also rolls back this intent."""
        row = OutboxMessage(kind="transport_probe")
        self.session.add(row)
        self.session.flush()
        return row.id

    def enqueue_workflow(self, run_id: UUID) -> UUID:
        """Only an existing durable workflow dispatch can be a target."""
        row = OutboxMessage(kind="workflow_run", workflow_run_id=run_id)
        self.session.add(row)
        self.session.flush()
        return row.id

    def claim(self, *, limit: int = 20, lease_seconds: int = 30) -> list[ClaimedMessage]:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(lease_seconds) is not int
            or not 5 <= lease_seconds <= 3600
        ):
            raise ValueError("Invalid outbox claim bounds")
        rows = self.session.scalars(
            select(OutboxMessage)
            .where(
                OutboxMessage.published_at.is_(None),
                or_(
                    OutboxMessage.lease_until.is_(None),
                    OutboxMessage.lease_until <= func.clock_timestamp(),
                ),
            )
            .order_by(OutboxMessage.created_at, OutboxMessage.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        claimed = []
        for row in rows:
            token = uuid4()
            row.lease_token = token
            row.lease_until = self.session.scalar(
                select(func.clock_timestamp() + timedelta(seconds=lease_seconds))
            )
            row.attempts += 1
            claimed.append(ClaimedMessage(row.id, token, row.kind))
        self.session.flush()
        return claimed

    def mark_published(self, claim: ClaimedMessage) -> bool:
        result = self.session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == claim.id,
                OutboxMessage.lease_token == claim.lease_token,
                OutboxMessage.published_at.is_(None),
                OutboxMessage.lease_until > func.clock_timestamp(),
            )
            .values(published_at=func.clock_timestamp(), lease_token=None, lease_until=None)
            .returning(OutboxMessage.id)
        )
        return result.scalar_one_or_none() is not None

    def release(self, claim: ClaimedMessage) -> bool:
        result = self.session.execute(
            update(OutboxMessage)
            .where(
                OutboxMessage.id == claim.id,
                OutboxMessage.lease_token == claim.lease_token,
                OutboxMessage.published_at.is_(None),
                OutboxMessage.lease_until > func.clock_timestamp(),
            )
            .values(lease_token=None, lease_until=None)
            .returning(OutboxMessage.id)
        )
        return result.scalar_one_or_none() is not None
