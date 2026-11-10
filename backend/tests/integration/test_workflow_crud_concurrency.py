"""Independent transactions preserve metadata intent and archive policy with cached rows."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, get_ident, local
from uuid import UUID

import pytest
from sqlalchemy import text

from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.workflows.exceptions import WorkflowArchivedError
from app.modules.workflows.models import Workflow, WorkflowStatus
from app.modules.workflows.repository import WorkflowRepository
from app.modules.workflows.schemas import WorkflowUpdateRequest
from app.modules.workflows.service import WorkflowService

pytestmark = pytest.mark.integration


def seed(database: Database) -> tuple[UUID, UUID]:
    with database.unit_of_work() as session:
        owner = UserRepository(session).add(
            email="metadata-race@example.com", password_hash="fixture", display_name="Race"
        )
        row = WorkflowRepository(session).add(
            owner_id=owner.id, name="Original", description="Original description"
        )
        return owner.id, row.id


def test_concurrent_partial_updates_preserve_disjoint_fields(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id, workflow_id = seed(repository_database)
    barrier = Barrier(2, timeout=5)
    pids: set[int] = set()
    original = WorkflowRepository.lock_owned

    def synchronize(self, **kwargs):
        self.session.execute(text("SET LOCAL lock_timeout = '5s'"))
        self.session.execute(text("SET LOCAL statement_timeout = '8s'"))
        pids.add(int(self.session.scalar(text("SELECT pg_backend_pid()"))))
        barrier.wait()
        return original(self, **kwargs)

    monkeypatch.setattr(WorkflowRepository, "lock_owned", synchronize)

    def update(data: WorkflowUpdateRequest) -> None:
        WorkflowService(repository_database).update(
            workflow_id=workflow_id, owner_id=owner_id, data=data
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(update, data)
            for data in [
                WorkflowUpdateRequest(name="Changed"),
                WorkflowUpdateRequest(description="Changed description"),
            ]
        ]
        for future in futures:
            future.result(timeout=12)
    assert len(pids) == 2
    with repository_database.session() as session:
        row = session.get(Workflow, workflow_id)
        assert (
            row is not None and row.name == "Changed" and row.description == "Changed description"
        )


@pytest.mark.parametrize("first", ["archive", "update"])
@pytest.mark.parametrize("save", [False, True])
def test_cached_draft_is_refreshed_before_metadata_or_archive_policy(
    repository_database: Database,
    monkeypatch: pytest.MonkeyPatch,
    first: str,
    save: bool,
) -> None:
    owner_id, workflow_id = seed(repository_database)
    barrier = Barrier(2, timeout=5)
    committed = Event()
    context = local()
    pids: dict[int, int] = {}
    original = WorkflowRepository.lock_owned

    def cache_before_lock(self: WorkflowRepository, **kwargs) -> Workflow | None:
        if self.session.info.get("archive_race_synchronized"):
            return original(self, **kwargs)
        self.session.info["archive_race_synchronized"] = True
        self.session.execute(text("SET LOCAL lock_timeout = '5s'"))
        self.session.execute(text("SET LOCAL statement_timeout = '8s'"))
        pids[get_ident()] = int(self.session.scalar(text("SELECT pg_backend_pid()")))
        cached = self.get_owned(**kwargs)
        assert cached is not None and cached.status == WorkflowStatus.DRAFT
        barrier.wait()  # Both Sessions hold a stale-capable draft identity-map entry.
        if context.operation != first:
            assert committed.wait(timeout=8)
        return original(self, **kwargs)

    monkeypatch.setattr(WorkflowRepository, "lock_owned", cache_before_lock)

    def mutate(operation: str) -> str:
        context.operation = operation
        try:
            service = WorkflowService(repository_database)
            if operation == "archive":
                service.archive(workflow_id=workflow_id, owner_id=owner_id)
            else:
                service.update(
                    workflow_id=workflow_id,
                    owner_id=owner_id,
                    data=WorkflowUpdateRequest.model_validate(
                        {
                            "name": "Changed",
                            **(
                                {
                                    "expected_version": 0,
                                    "definition": {
                                        "schema_version": "1.0",
                                        "nodes": [],
                                        "edges": [],
                                    },
                                }
                                if save
                                else {}
                            ),
                        }
                    ),
                )
            if operation == first:
                committed.set()
            return "success"
        except WorkflowArchivedError:
            return "archived"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            operation: executor.submit(mutate, operation) for operation in ("archive", "update")
        }
        results = {operation: future.result(timeout=12) for operation, future in futures.items()}
    assert len(set(pids.values())) == 2
    assert results["archive"] == "success"
    assert results["update"] == ("archived" if first == "archive" else "success")
    with repository_database.session() as session:
        row = session.get(Workflow, workflow_id)
        assert row is not None and row.status == WorkflowStatus.ARCHIVED
        assert row.name == ("Original" if first == "archive" else "Changed")

    detail = WorkflowService(repository_database).get(workflow_id=workflow_id, owner_id=owner_id)
    assert detail.current_version_number == (1 if save and first == "update" else 0)
