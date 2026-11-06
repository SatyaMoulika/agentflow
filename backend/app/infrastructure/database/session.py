"""Synchronous SQLAlchemy resources, shared factory and operation-local sessions."""

from collections.abc import Iterator
from contextlib import contextmanager

from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Own one process-local engine; never share a Session between operations."""

    def __init__(self, url: SecretStr) -> None:
        self.engine = create_engine(
            url.get_secret_value(),
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=5,
            pool_timeout=5,
            connect_args={"connect_timeout": 5},
            hide_parameters=True,
            echo=False,
        )
        self.session_factory = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False, close_resets_only=False
        )

    def check_connection(self) -> None:
        """Connect without creating schema or retaining a transaction."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Close/rollback on exit; services must explicitly begin/commit writes."""
        with self.session_factory() as session:
            yield session

    @contextmanager
    def unit_of_work(self) -> Iterator[Session]:
        """Caller-selected transaction: commit on success, rollback on failure, always close."""
        with self.session() as session, session.begin():
            yield session

    def dispose(self) -> None:
        """Release checked-in pooled connections during application shutdown."""
        self.engine.dispose()
