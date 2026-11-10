"""Explicit owner checks and short transactions; no network calls in this module."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, TimeoutError

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.modules.connections.models import Connection
from app.modules.connections.schemas import (
    ConnectionCreate,
    ConnectionPage,
    ConnectionResponse,
    PlannerConnection,
)
from app.modules.connections.secrets import ConnectionUnavailableError, decrypt, encrypt


class ConnectionNotFoundError(Exception):
    """Missing and unowned connections share the same outcome."""


@dataclass(frozen=True)
class AuthorizedConnection:
    endpoint_url: str
    auth_type: str
    secret: SecretStr | None = field(default=None, repr=False)


class ConnectionService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def planner_catalog(self, owner_id: UUID, identities: list[UUID]) -> list[PlannerConnection]:
        if not identities:
            return []
        if len(identities) > 20 or len(set(identities)) != len(identities):
            raise ValueError("Invalid planner connection selection")
        try:
            with self.database.session() as session:
                # Deliberately do not select ciphertext, authenticate, decrypt or call endpoints.
                rows = session.execute(
                    select(Connection.id, Connection.name, Connection.endpoint_url).where(
                        Connection.owner_id == owner_id,
                        Connection.revoked_at.is_(None),
                        Connection.id.in_(identities),
                    )
                ).mappings()
                catalog = {row["id"]: PlannerConnection.model_validate(dict(row)) for row in rows}
                if len(catalog) != len(identities):
                    raise ConnectionNotFoundError()
                return [catalog[identity] for identity in identities]
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def create(self, owner_id: UUID, data: ConnectionCreate) -> ConnectionResponse:
        identity = uuid4()
        protected = (
            encrypt(self.settings.connection_encryption_key, owner_id, identity, data.secret)
            if data.secret is not None
            else None
        )
        try:
            with self.database.unit_of_work() as session:
                row = Connection(
                    id=identity,
                    owner_id=owner_id,
                    name=data.name,
                    endpoint_url=data.endpoint_url,
                    auth_type=data.auth_type,
                    encrypted_secret=protected,
                )
                session.add(row)
                session.flush()
                return ConnectionResponse.model_validate(row)
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def list(self, owner_id: UUID, page: int, page_size: int) -> ConnectionPage:
        try:
            with self.database.session() as session:
                query = select(Connection).where(Connection.owner_id == owner_id)
                total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
                rows = session.scalars(
                    query.order_by(Connection.created_at.desc(), Connection.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
                return ConnectionPage(
                    items=[ConnectionResponse.model_validate(row) for row in rows],
                    page=page,
                    page_size=page_size,
                    total=total,
                )
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def get(self, owner_id: UUID, connection_id: UUID) -> ConnectionResponse:
        try:
            with self.database.session() as session:
                row = session.scalar(
                    select(Connection).where(
                        Connection.id == connection_id, Connection.owner_id == owner_id
                    )
                )
                if row is None:
                    raise ConnectionNotFoundError()
                return ConnectionResponse.model_validate(row)
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def revoke(self, owner_id: UUID, connection_id: UUID) -> None:
        try:
            with self.database.unit_of_work() as session:
                row = session.scalar(
                    select(Connection)
                    .where(Connection.id == connection_id, Connection.owner_id == owner_id)
                    .with_for_update()
                )
                if row is None:
                    raise ConnectionNotFoundError()
                if row.revoked_at is None:
                    row.revoked_at = session.scalar(select(func.clock_timestamp()))
                    row.encrypted_secret = None
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def authorize(self, owner_id: UUID, connection_id: UUID) -> AuthorizedConnection:
        try:
            with self.database.session() as session:
                row = session.scalar(
                    select(Connection).where(
                        Connection.id == connection_id,
                        Connection.owner_id == owner_id,
                        Connection.revoked_at.is_(None),
                    )
                )
                if row is None:
                    raise ConnectionUnavailableError()
                url, auth_type, token = row.endpoint_url, row.auth_type, row.encrypted_secret
            # Decryption and all later DNS/network operations own no storage transaction.
            secret = (
                decrypt(self.settings.connection_encryption_key, owner_id, connection_id, token)
                if token is not None
                else None
            )
            return AuthorizedConnection(url, auth_type, secret)
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None
