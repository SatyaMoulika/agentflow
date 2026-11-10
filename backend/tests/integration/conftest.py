"""Require an explicit, local test target; never read the private backend dotenv."""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import Connection, make_url

from app.core.config import Settings
from app.infrastructure.database.session import Database


@pytest.fixture
def test_database_url() -> SecretStr:
    raw = os.environ.get("TEST_DATABASE_URL")
    if not raw:
        pytest.fail("Set TEST_DATABASE_URL for the isolated agentflow_test database", pytrace=False)
    try:
        settings = Settings(database_url=SecretStr(raw))
    except ValidationError:
        pytest.fail("TEST_DATABASE_URL is not a supported PostgreSQL URL", pytrace=False)
    url = make_url(raw)
    if url.database != "agentflow_test" or url.host not in {"localhost", "127.0.0.1"} or url.query:
        pytest.fail(
            "Integration tests require local agentflow_test with no URL query overrides",
            pytrace=False,
        )
    assert settings.database_url is not None
    return settings.database_url


@pytest.fixture
def database(test_database_url: SecretStr) -> Iterator[Database]:
    database = Database(test_database_url)
    try:
        database.check_connection()
        yield database
    finally:
        database.dispose()


@pytest.fixture
def migration_environment(database: Database) -> Iterator[tuple[Connection, Config]]:
    """Run migrations only in a random schema of the guarded local test database."""
    schema = f"test_{uuid4().hex}"
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with database.engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        connection.exec_driver_sql(f'SET search_path TO "{schema}", public')
        connection.commit()
        config.attributes["connection"] = connection
        try:
            yield connection, config
        finally:
            connection.rollback()
            connection.exec_driver_sql("SET search_path TO public")
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            connection.commit()


@pytest.fixture
def migrated_connection(migration_environment: tuple[Connection, Config]) -> Connection:
    connection, config = migration_environment
    command.upgrade(config, "head")
    return connection


@pytest.fixture
def repository_database(database: Database, migrated_connection: Connection) -> Database:
    """Independent pooled sessions target the migrated schema, not one shared connection."""
    schema = migrated_connection.exec_driver_sql("SELECT current_schema()").scalar_one()
    migrated_connection.commit()
    database.engine = database.engine.execution_options(schema_translate_map={None: schema})
    database.session_factory.configure(bind=database.engine)
    return database
