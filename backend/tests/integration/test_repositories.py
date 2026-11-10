"""Repository queries and caller-owned transactions on real isolated PostgreSQL."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from app.infrastructure.database.models import User, Workflow, WorkflowVersion
from app.infrastructure.database.session import Database
from app.modules.auth.repository import UserRepository
from app.modules.workflows.exceptions import WorkflowNotFoundError, WorkflowVersionConflictError
from app.modules.workflows.repository import WorkflowRepository

pytestmark = pytest.mark.integration
DEFINITION = {"schema_version": "1.0", "nodes": [], "edges": []}


def create_workflow(database: Database) -> tuple[UUID, UUID, UUID]:
    with database.unit_of_work() as session:
        user = UserRepository(session).add(
            email="owner@example.com", password_hash="test-only-hash", display_name="Owner"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=user.id, name="Invoice")
        first = workflows.append_version(
            workflow_id=workflow.id, owner_id=user.id, expected_version=0, definition=DEFINITION
        )
        return user.id, workflow.id, first.id


def test_commits_user_workflow_and_first_version_together_and_closes_session(
    repository_database: Database,
) -> None:
    user_id, workflow_id, version_id = create_workflow(repository_database)
    with repository_database.unit_of_work() as session:
        users = UserRepository(session)
        workflows = WorkflowRepository(session)
        user = users.get_by_id(user_id)
        assert user is not None and user.email == "owner@example.com"
        assert users.get_by_email("owner@example.com") is user
        assert users.get_by_email("missing@example.com") is None
        assert users.get_by_id(uuid4()) is None
        workflow = workflows.get_owned(workflow_id=workflow_id, owner_id=user_id)
        assert workflow is not None and workflow.current_version_id == version_id
        assert (
            workflows.get_version_owned(
                workflow_id=workflow_id, version_id=version_id, owner_id=user_id
            )
            is not None
        )
    with pytest.raises(InvalidRequestError):
        session.execute(text("SELECT 1"))


@pytest.mark.parametrize("failure", ["business", "constraint"])
def test_failure_rolls_back_all_repository_writes(
    repository_database: Database, failure: str
) -> None:
    expected_error = ValueError if failure == "business" else IntegrityError
    with pytest.raises(expected_error), repository_database.unit_of_work() as session:
        user = UserRepository(session).add(
            email="rollback@example.com", password_hash="fixture", display_name="Rollback"
        )
        workflows = WorkflowRepository(session)
        workflow = workflows.add(owner_id=user.id, name="Discarded")
        workflows.append_version(
            workflow_id=workflow.id, owner_id=user.id, expected_version=0, definition=DEFINITION
        )
        if failure == "business":
            raise ValueError("operation rejected after repository writes")
        UserRepository(session).add(
            email=user.email, password_hash="fixture", display_name="Duplicate"
        )

    with repository_database.unit_of_work() as reader:
        for model in (User, Workflow, WorkflowVersion):
            assert reader.scalar(select(func.count()).select_from(model)) == 0
        # A fresh unit of work can commit after the failed one, not inherit its state.
        UserRepository(reader).add(
            email="recovered@example.com", password_hash="fixture", display_name="Recovered"
        )
    with repository_database.unit_of_work() as reader:
        assert UserRepository(reader).get_by_email("recovered@example.com") is not None


def test_repositories_flush_without_implicitly_committing(repository_database: Database) -> None:
    with repository_database.session() as session:
        created = UserRepository(session).add(
            email="uncommitted@example.com", password_hash="fixture", display_name="Uncommitted"
        )
        assert created.id is not None
        # A second connection cannot see a repository's uncommitted insert.
        with repository_database.unit_of_work() as observer:
            assert UserRepository(observer).get_by_email(created.email) is None
    with repository_database.unit_of_work() as observer:
        assert UserRepository(observer).get_by_email("uncommitted@example.com") is None


def test_owned_queries_and_append_hide_other_owners_resources(
    repository_database: Database,
) -> None:
    owner_id, workflow_id, version_id = create_workflow(repository_database)
    with repository_database.unit_of_work() as session:
        stranger = UserRepository(session).add(
            email="stranger@example.com", password_hash="fixture", display_name="Stranger"
        )
        stranger_id = stranger.id
        other = WorkflowRepository(session).add(owner_id=stranger_id, name="Other")
        other_id = other.id
    with repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        assert repo.get_owned(workflow_id=workflow_id, owner_id=stranger_id) is None
        assert (
            repo.get_version_owned(
                workflow_id=workflow_id, version_id=version_id, owner_id=stranger_id
            )
            is None
        )
        assert (
            repo.get_version_owned(
                workflow_id=other_id, version_id=version_id, owner_id=stranger_id
            )
            is None
        )
        assert (
            repo.get_version_owned(workflow_id=workflow_id, version_id=uuid4(), owner_id=owner_id)
            is None
        )
        assert [row.id for row in repo.list_owned(owner_id=stranger_id)] == [other_id]
    with pytest.raises(WorkflowNotFoundError), repository_database.unit_of_work() as session:
        WorkflowRepository(session).append_version(
            workflow_id=workflow_id, owner_id=stranger_id, expected_version=1, definition=DEFINITION
        )
    with pytest.raises(WorkflowNotFoundError), repository_database.unit_of_work() as session:
        WorkflowRepository(session).append_version(
            workflow_id=uuid4(), owner_id=owner_id, expected_version=0, definition=DEFINITION
        )


def test_list_is_bounded_owner_scoped_and_deterministic(repository_database: Database) -> None:
    with repository_database.unit_of_work() as session:
        owner = UserRepository(session).add(
            email="list@example.com", password_hash="fixture", display_name="List owner"
        )
        owner_id = owner.id
        repo = WorkflowRepository(session)
        rows = [repo.add(owner_id=owner_id, name=f"Workflow {index}") for index in range(3)]
        # PostgreSQL now() is the same within this transaction: ID is the tie-breaker.
        expected = sorted([row.id for row in rows], reverse=True)
    with repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        assert [row.id for row in repo.list_owned(owner_id=owner_id, limit=2)] == expected[:2]
        assert [row.id for row in repo.list_owned(owner_id=owner_id, offset=2)] == expected[2:]
        assert repo.list_owned(owner_id=uuid4()) == []


@pytest.mark.parametrize("limit,offset", [(0, 0), (101, 0), (1, -1)])
def test_invalid_list_bounds_are_rejected(
    repository_database: Database, limit: int, offset: int
) -> None:
    with pytest.raises(ValueError), repository_database.unit_of_work() as session:
        WorkflowRepository(session).list_owned(owner_id=uuid4(), limit=limit, offset=offset)


def test_append_preserves_history_copies_input_and_refreshes_cached_navigation(
    repository_database: Database,
) -> None:
    owner_id, workflow_id, first_id = create_workflow(repository_database)
    definition: dict[str, Any] = DEFINITION | {"nodes": [{"id": "new"}]}
    with repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        workflow = repo.get_owned(workflow_id=workflow_id, owner_id=owner_id)
        assert workflow is not None
        assert workflow.current_version is not None and workflow.current_version.id == first_id
        assert len(workflow.versions) == 1
        before = workflow.updated_at
        workflow.description = "Pending metadata edit"
        second = repo.append_version(
            workflow_id=workflow_id, owner_id=owner_id, expected_version=1, definition=definition
        )
        second_id = second.id
        definition["nodes"][0]["id"] = "changed-after-save"
        assert second.definition_json["nodes"][0]["id"] == "new"
        assert workflow.current_version is not None and workflow.current_version.id == second.id
        assert len(workflow.versions) == 2
        assert workflow.updated_at > before
        assert workflow.description == "Pending metadata edit"
    with repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        first = repo.get_version_owned(
            workflow_id=workflow_id, version_id=first_id, owner_id=owner_id
        )
        second = repo.get_version_owned(
            workflow_id=workflow_id, version_id=second_id, owner_id=owner_id
        )
        assert first is not None and first.definition_json == DEFINITION
        assert second is not None and second.version_number == 2
        assert second.definition_json["nodes"][0]["id"] == "new"


def test_stale_save_rolls_back_other_pending_edits_without_creating_a_version(
    repository_database: Database,
) -> None:
    owner_id, workflow_id, first_id = create_workflow(repository_database)
    with pytest.raises(WorkflowVersionConflictError), repository_database.unit_of_work() as session:
        repo = WorkflowRepository(session)
        workflow = repo.get_owned(workflow_id=workflow_id, owner_id=owner_id)
        assert workflow is not None
        workflow.name = "Should roll back"
        repo.append_version(
            workflow_id=workflow_id, owner_id=owner_id, expected_version=0, definition=DEFINITION
        )
    with repository_database.unit_of_work() as session:
        workflow = WorkflowRepository(session).get_owned(workflow_id=workflow_id, owner_id=owner_id)
        assert workflow is not None and workflow.name == "Invoice"
        assert workflow.current_version_id == first_id
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 1


@pytest.mark.parametrize("definition", [{}, {"schema_version": "2.0"}])
def test_invalid_snapshot_does_not_advance_pointer_or_persist_partial_work(
    repository_database: Database,
    definition: dict[str, Any],
) -> None:
    owner_id, workflow_id, first_id = create_workflow(repository_database)
    with pytest.raises(IntegrityError), repository_database.unit_of_work() as session:
        WorkflowRepository(session).append_version(
            workflow_id=workflow_id, owner_id=owner_id, expected_version=1, definition=definition
        )
    with repository_database.unit_of_work() as session:
        workflow = WorkflowRepository(session).get_owned(workflow_id=workflow_id, owner_id=owner_id)
        assert workflow is not None and workflow.current_version_id == first_id
        assert session.scalar(select(func.count()).select_from(WorkflowVersion)) == 1
