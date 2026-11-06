"""Renew a run lease with independent short sessions while pure computation runs."""

from threading import Event, Thread
from types import TracebackType

from app.modules.claims.repository import ClaimLostError
from app.modules.executions.worker_state import WorkerState


class LeaseHeartbeat:
    def __init__(self, worker: WorkerState, *, lease_seconds: int, enabled: bool) -> None:
        self.worker = worker
        self.interval = lease_seconds / 3
        self.lease_seconds = lease_seconds
        self.enabled = enabled
        self.stopped = Event()
        self.lost = Event()
        self.thread: Thread | None = None

    def __enter__(self) -> "LeaseHeartbeat":
        if self.enabled:
            self.thread = Thread(target=self._renew, name="agentflow-run-lease", daemon=True)
            self.thread.start()
        return self

    def _renew(self) -> None:
        while not self.stopped.wait(self.interval):
            try:
                self.worker.renew(lease_seconds=self.lease_seconds)
            except Exception:
                # Treat storage uncertainty conservatively, without logging driver
                # exceptions or attempting to resurrect a possibly expired claim.
                self.lost.set()
                return

    def check(self) -> None:
        if self.lost.is_set():
            raise ClaimLostError()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stopped.set()
        if self.thread is not None:
            self.thread.join()
