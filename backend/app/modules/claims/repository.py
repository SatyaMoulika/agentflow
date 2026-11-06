"""Run-row locked claims and database-time fencing; callers own every transaction."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import WorkflowRun
from app.modules.claims.models import RunClaim
from app.modules.executions.retry_models import NodeRetry
from app.modules.executions.state import RunStatus


@dataclass(frozen=True)
class Claim:
    run_id: UUID
    token: UUID
    generation: int


class ClaimLostError(Exception):
    """The claim is absent, expired, cancelled or replaced."""


class ClaimRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _bounds(seconds: int) -> None:
        if type(seconds) is not int or not 5 <= seconds <= 3600:
            raise ValueError("Invalid claim lease duration")

    def _lock_run(self, run_id: UUID) -> WorkflowRun | None:
        return self.session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def acquire(self, run_id: UUID, *, lease_seconds: int = 30) -> Claim | None:
        """Acquire a queued run; this transport primitive does not authorize execution."""
        return self._acquire(run_id, lease_seconds=lease_seconds, recover_running=False)

    def acquire_for_recovery(self, run_id: UUID, *, lease_seconds: int = 30) -> Claim | None:
        """Also allow expired, previously claimed running runs.

        The caller must authorize the owner and establish that the entire saved graph
        is pure before using this primitive. Unclaimed synchronous runs cannot be taken
        over. Claiming never executes or reconciles an attempt by itself.
        """
        return self._acquire(run_id, lease_seconds=lease_seconds, recover_running=True)

    def _acquire(self, run_id: UUID, *, lease_seconds: int, recover_running: bool) -> Claim | None:
        self._bounds(lease_seconds)
        run = self._lock_run(run_id)
        allowed = {RunStatus.QUEUED, RunStatus.RUNNING} if recover_running else {RunStatus.QUEUED}
        if run is None or run.status not in allowed:
            return None
        existing = self.session.get(RunClaim, run_id, populate_existing=True)
        if run.status == RunStatus.RUNNING and existing is None:
            return None
        now = self.session.scalar(select(func.clock_timestamp()))
        assert now is not None
        if (
            self.session.scalar(
                select(NodeRetry.node_run_id)
                .where(
                    NodeRetry.workflow_run_id == run_id,
                    NodeRetry.resumed_at.is_(None),
                    NodeRetry.cancelled_at.is_(None),
                    NodeRetry.due_at > now,
                )
                .limit(1)
            )
            is not None
        ):
            return None
        if existing is not None and existing.lease_until is not None and existing.lease_until > now:
            return None
        token = uuid4()
        if existing is None:
            existing = RunClaim(
                run_id=run_id,
                generation=1,
                lease_token=token,
                lease_until=now + timedelta(seconds=lease_seconds),
            )
            self.session.add(existing)
        else:
            existing.generation += 1
            existing.lease_token = token
            existing.lease_until = now + timedelta(seconds=lease_seconds)
        self.session.flush()
        return Claim(run_id, token, existing.generation)

    def assert_current(self, claim: Claim) -> WorkflowRun:
        """Hold the run lock until the caller commits the fenced state mutation."""
        run = self._lock_run(claim.run_id)
        slot = self.session.get(RunClaim, claim.run_id, populate_existing=True)
        now = self.session.scalar(select(func.clock_timestamp()))
        if (
            run is None
            or run.status not in {RunStatus.QUEUED, RunStatus.RUNNING}
            or slot is None
            or slot.lease_token != claim.token
            or slot.generation != claim.generation
            or slot.lease_until is None
            or now is None
            or slot.lease_until <= now
        ):
            raise ClaimLostError()
        return run

    def renew(self, claim: Claim, *, lease_seconds: int = 30) -> None:
        self._bounds(lease_seconds)
        self.assert_current(claim)
        slot = self.session.get(RunClaim, claim.run_id)
        assert slot is not None
        now = self.session.scalar(select(func.clock_timestamp()))
        assert now is not None
        slot.lease_until = now + timedelta(seconds=lease_seconds)
        self.session.flush()

    def release(self, claim: Claim) -> None:
        self.assert_current(claim)
        slot = self.session.get(RunClaim, claim.run_id)
        assert slot is not None
        slot.lease_token = None
        slot.lease_until = None
        self.session.flush()
