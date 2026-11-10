"""Real PostgreSQL session, transaction, and pool checks without application tables."""

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import InvalidRequestError

from app.infrastructure.database.session import Database

pytestmark = pytest.mark.integration


def test_connects_to_postgresql_without_creating_application_tables(database: Database) -> None:
    with database.session() as session:
        assert session.scalar(text("SELECT current_database()")) == "agentflow_test"
        assert str(session.scalar(text("SELECT version()"))).startswith("PostgreSQL 16.")
    assert inspect(database.engine).get_table_names(schema="public") == []


@pytest.mark.parametrize("outcome", ["commit", "no_commit", "exception"])
def test_sessions_require_explicit_commit_and_rollback_on_exit(
    database: Database, outcome: str
) -> None:
    # A connection-local temporary table tests actual writes without a migration
    # or any application-owned schema. This test uses one pooled connection.
    with database.engine.begin() as connection:
        connection.execute(text("CREATE TEMP TABLE phase2a_probe (value integer)"))
        backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))

    with database.session() as session:
        assert session.scalar(text("SELECT pg_backend_pid()")) == backend_pid
        session.rollback()
        if outcome == "exception":
            with pytest.raises(ValueError, match="cancel operation"):
                with session.begin():
                    session.execute(text("INSERT INTO phase2a_probe VALUES (42)"))
                    raise ValueError("cancel operation")
        else:
            session.execute(text("INSERT INTO phase2a_probe VALUES (42)"))
            if outcome == "commit":
                session.commit()

    # A permanently closed Session cannot silently be reused by another operation.
    with pytest.raises(InvalidRequestError):
        session.execute(text("SELECT 1"))
    with database.session() as reader:
        assert reader is not session
        assert reader.scalar(text("SELECT pg_backend_pid()")) == backend_pid
        assert reader.scalar(text("SELECT count(*) FROM phase2a_probe")) == (
            1 if outcome == "commit" else 0
        )


def test_overlapping_sessions_use_distinct_transactions_and_release_locks(
    database: Database,
) -> None:
    with database.session() as first, database.session() as second:
        assert first.scalar(text("SELECT pg_backend_pid()")) != second.scalar(
            text("SELECT pg_backend_pid()")
        )
        assert first.scalar(text("SELECT pg_try_advisory_xact_lock(2026103002)")) is True
        assert second.scalar(text("SELECT pg_try_advisory_xact_lock(2026103002)")) is False
        first.commit()
        assert second.scalar(text("SELECT pg_try_advisory_xact_lock(2026103002)")) is True
        second.rollback()
        assert first.scalar(text("SELECT pg_try_advisory_xact_lock(2026103002)")) is True


def test_dispose_closes_checked_in_dbapi_connections(database: Database) -> None:
    closed: list[bool] = []

    def on_close(connection: object, connection_record: object) -> None:
        closed.append(True)

    event.listen(database.engine, "close", on_close)
    with database.session() as session:
        session.execute(text("SELECT 1"))
    database.dispose()
    assert closed == [True]
