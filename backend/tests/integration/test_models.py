"""Database-enforced invariants and actual ORM relationships on migrated PostgreSQL."""

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.infrastructure.database.models import User, Workflow, WorkflowStatus, WorkflowVersion

pytestmark = pytest.mark.integration

DEFINITION = {"schema_version": "1.0", "nodes": [], "edges": []}


@pytest.fixture
def seeded_session(
    migrated_connection: Connection,
) -> Iterator[tuple[Session, User, Workflow, WorkflowVersion]]:
    with Session(migrated_connection) as session:
        user = User(
            email="owner@example.com", password_hash="$argon2id$test-fixture", display_name="Owner"
        )
        workflow = Workflow(owner=user, name="Invoice workflow")
        session.add(workflow)
        session.flush()
        version = WorkflowVersion(
            workflow=workflow, creator=user, version_number=1, definition_json=DEFINITION.copy()
        )
        session.add(version)
        session.flush()
        workflow.current_version_id = version.id
        session.commit()
        yield session, user, workflow, version


def test_orm_roundtrip_relationships_json_and_utc_defaults(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
) -> None:
    session, user, workflow, version = seeded_session
    session.expire_all()
    loaded = session.scalars(
        select(Workflow).options(
            selectinload(Workflow.owner),
            selectinload(Workflow.versions),
            selectinload(Workflow.current_version),
        )
    ).one()

    assert isinstance(loaded.id, UUID)
    assert loaded.owner.id == user.id
    assert loaded.owner.is_active is True
    assert loaded.status == WorkflowStatus.DRAFT
    assert loaded.description == ""
    assert [item.id for item in loaded.versions] == [version.id]
    assert loaded.current_version is not None and loaded.current_version.id == version.id
    assert loaded.versions[0].creator.id == user.id
    assert loaded.versions[0].definition_json == DEFINITION
    assert loaded.created_at.utcoffset() == timedelta(0)
    assert loaded.updated_at.utcoffset() == timedelta(0)
    assert version.created_at.utcoffset() == timedelta(0)


def test_user_email_uniqueness_and_normalization_are_database_enforced(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
) -> None:
    session, user, _, _ = seeded_session
    for email in (user.email, "Owner@example.com", " owner@example.com "):
        with pytest.raises(IntegrityError), session.begin_nested():
            session.execute(
                insert(User).values(email=email, password_hash="hash", display_name="Other")
            )


@pytest.mark.parametrize(
    "values",
    [
        {"name": " "},
        {"status": "unknown"},
        {"owner_id": uuid4()},
    ],
)
def test_workflow_field_and_owner_constraints(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
    values: dict[str, Any],
) -> None:
    session, user, _, _ = seeded_session
    data = {"name": "Other workflow", "owner_id": user.id} | values
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(insert(Workflow).values(**data))


@pytest.mark.parametrize(
    "values",
    [
        {"version_number": 0},
        {"version_number": 1},
        {"schema_version": "2.0"},
        {"definition_json": []},
        {"definition_json": None},
        {"definition_json": {}},
        {"definition_json": {"schema_version": None}},
        {"definition_json": {"schema_version": 1.0}},
        {"definition_json": {"schema_version": "2.0"}},
        {"created_by": uuid4()},
        {"workflow_id": uuid4()},
    ],
)
def test_version_number_schema_and_foreign_key_constraints(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
    values: dict[str, Any],
) -> None:
    session, user, workflow, _ = seeded_session
    data = {
        "workflow_id": workflow.id,
        "created_by": user.id,
        "version_number": 2,
        "definition_json": DEFINITION.copy(),
    } | values
    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(insert(WorkflowVersion).values(**data))


def test_current_pointer_rejects_another_workflows_version(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
) -> None:
    session, user, workflow, version = seeded_session
    other = Workflow(owner_id=user.id, name="Other")
    session.add(other)
    session.flush()
    other_version = WorkflowVersion(
        workflow_id=other.id,
        created_by=user.id,
        version_number=1,
        definition_json=DEFINITION.copy(),
    )
    session.add(other_version)
    session.flush()

    with pytest.raises(IntegrityError), session.begin_nested():
        session.execute(
            update(Workflow)
            .where(Workflow.id == workflow.id)
            .values(current_version_id=other_version.id)
        )
    session.refresh(workflow)
    assert workflow.current_version_id == version.id
    assert other.current_version_id is None  # A deliberately versionless draft is valid.


@pytest.mark.parametrize("operation", ["orm_update", "sql_update", "delete", "truncate"])
def test_saved_versions_are_immutable_in_database_and_orm(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
    operation: str,
) -> None:
    session, _, _, version = seeded_session
    with (
        pytest.raises(IntegrityError, match="Workflow versions are immutable"),
        session.begin_nested(),
    ):
        if operation == "orm_update":
            version.definition_json = {"schema_version": "1.0", "nodes": [{"id": "changed"}]}
            session.flush()
        elif operation == "sql_update":
            session.execute(text("UPDATE workflow_versions SET version_number = 20"))
        elif operation == "delete":
            session.execute(delete(WorkflowVersion).where(WorkflowVersion.id == version.id))
        else:
            session.execute(text("TRUNCATE workflow_versions CASCADE"))

    session.refresh(version)
    assert version.version_number == 1
    assert version.definition_json == DEFINITION


@pytest.mark.parametrize("entity", ["user", "workflow"])
def test_historical_rows_are_not_cascade_deleted(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
    entity: str,
) -> None:
    session, user, workflow, _ = seeded_session
    # Load collections too: passive_deletes='all' must preserve database decisions.
    assert user.workflows and workflow.versions
    with pytest.raises(IntegrityError), session.begin_nested():
        session.delete(user if entity == "user" else workflow)
        session.flush()


def test_appending_version_and_archiving_preserve_previous_snapshot(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
) -> None:
    session, user, workflow, first = seeded_session
    first_created = first.created_at
    before = workflow.updated_at
    second = WorkflowVersion(
        workflow_id=workflow.id,
        created_by=user.id,
        version_number=2,
        definition_json=DEFINITION | {"name": "Revised"},
    )
    session.add(second)
    session.flush()
    workflow.current_version_id = second.id
    workflow.status = WorkflowStatus.ARCHIVED
    session.commit()
    session.refresh(workflow)
    session.refresh(first)

    assert workflow.current_version_id == second.id
    assert workflow.updated_at > before
    assert first.definition_json == DEFINITION
    assert first.created_at == first_created
    assert session.scalar(select(WorkflowVersion).where(WorkflowVersion.id == first.id)) is not None


def test_raw_user_update_refreshes_timestamp_in_database(
    seeded_session: tuple[Session, User, Workflow, WorkflowVersion],
) -> None:
    session, user, _, _ = seeded_session
    before = user.updated_at
    session.execute(
        text("UPDATE users SET display_name = 'Renamed' WHERE id = :id"), {"id": user.id}
    )
    session.refresh(user)
    assert user.updated_at > before
