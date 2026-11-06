"""Alembic environment using validated settings or an explicitly supplied connection."""

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import load_settings
from app.infrastructure.database import models  # noqa: F401 -- register all mapped tables
from app.infrastructure.database.base import Base
from app.infrastructure.database.session import Database

config = context.config


def migrate(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    # Offline DDL generation needs only the dialect, not a URL or credentials.
    context.configure(
        dialect_name="postgresql",
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        if not isinstance(supplied_connection, Connection):
            raise TypeError("Alembic connection attribute must be a SQLAlchemy Connection")
        migrate(supplied_connection)
    else:
        settings = load_settings()
        if settings.database_url is None:
            raise RuntimeError("Set AGENTFLOW_DATABASE_URL before running online migrations")
        database = Database(settings.database_url)
        try:
            with database.engine.connect() as connection:
                migrate(connection)
        except SQLAlchemyError:
            raise RuntimeError(
                "Database migration failed; verify connectivity and schema state."
            ) from None
        finally:
            database.dispose()
