"""Separate PostgreSQL connections prove transaction races, not just sequential mocks."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.infrastructure.database.models import User, WorkflowVersion
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.workflows.exceptions import WorkflowVersionConflictError
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration
DEFINITION = {"schema_version": "1.0", "nodes": [], "edges": []}


def test_concurrent_stale_writers_create_exactly_one_new_version(
    repository_database: Database,
) -> None:
    with repository_database.unit_of_work() as session:
        user = UserRepository(session).add(
            email="writer@example.com", password_hash="fixture", display_name="Writer"
        )
        owner_id = user.id
        repo = WorkflowRepository(session)
        workflow = repo.add(owner_id=owner_id, name="Concurrent workflow")
        workflow_id = workflow.id
        first = repo.append_version(
            workflow_id=workflow_id, owner_id=owner_id, expected_version=0, definition=DEFINITION
        )
        first_id = first.id

    barrier = Barrier(2, timeout=5)

    def writer(label: str) -> tuple[str, int]:
        backend_pid = 0
        try:
            with repository_database.unit_of_work() as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '8s'"))
                backend_pid = int(session.scalar(text("SELECT pg_backend_pid()")))
                repo = WorkflowRepository(session)
                cached = repo.get_owned(workflow_id=workflow_id, owner_id=owner_id)
                assert cached is not None and cached.current_version_id == first_id
                assert (
                    cached.current_version is not None
                    and cached.current_version.version_number == 1
                )
                barrier.wait()
                repo.append_version(
                    workflow_id=workflow_id,
                    owner_id=owner_id,
                    expected_version=1,
                    definition=DEFINITION | {"writer": label},
                )
            return "committed", backend_pid
        except WorkflowVersionConflictError:
            return "conflict", backend_pid

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(writer, label) for label in ("first", "second")]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(result[0] for result in results) == ["committed", "conflict"]
    assert len({result[1] for result in results}) == 2
    with repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        workflow = repo.get_owned(workflow_id=workflow_id, owner_id=owner_id)
        assert workflow is not None and workflow.current_version is not None
        assert workflow.current_version.version_number == 2
        assert session.scalars(
            select(WorkflowVersion.version_number).order_by(WorkflowVersion.version_number)
        ).all() == [1, 2]
        first = repo.get_version_owned(
            workflow_id=workflow_id, version_id=first_id, owner_id=owner_id
        )
        assert first is not None and first.definition_json == DEFINITION


def test_duplicate_email_race_has_one_commit_and_one_clean_rollback(
    repository_database: Database,
) -> None:
    barrier = Barrier(2, timeout=5)

    def register_fixture() -> tuple[str, UUID | None]:
        try:
            with repository_database.unit_of_work() as session:
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                session.execute(text("SET LOCAL statement_timeout = '8s'"))
                barrier.wait()
                user = UserRepository(session).add(
                    email="race@example.com", password_hash="fixture", display_name="Race"
                )
                user_id = user.id
            return "committed", user_id
        except IntegrityError as error:
            assert (
                getattr(getattr(error.orig, "diag", None), "constraint_name", None)
                == "uq_users_email"
            )
            return "duplicate", None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(register_fixture) for _ in range(2)]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(result[0] for result in results) == ["committed", "duplicate"]
    with repository_database.unit_of_work() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 1
        user = UserRepository(session).get_by_email("race@example.com")
        assert user is not None and user.id in {result[1] for result in results}
