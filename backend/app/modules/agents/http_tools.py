"""Bind an agent's selected HTTP tools to an authenticated owner; close storage before I/O."""

from time import monotonic
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.modules.connections.http_executor import get_json
from app.modules.connections.schemas import PlannerConnection
from app.modules.connections.secrets import ConnectionUnavailableError
from app.modules.connections.service import ConnectionNotFoundError, ConnectionService
from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.state import FailureCode

MAX_AGENT_HTTP_BYTES = 32768


class AgentHttpTools:
    def __init__(
        self, database: Database, settings: Settings, owner_id: UUID, connection_ids: list[str]
    ) -> None:
        self.service = ConnectionService(database, settings)
        self.owner_id = owner_id
        self.identities = tuple(UUID(identity) for identity in connection_ids)

    def catalog(self) -> list[PlannerConnection]:
        """Metadata only; this must not decrypt credentials or contact an endpoint."""
        try:
            return self.service.planner_catalog(self.owner_id, list(self.identities))
        except (ConnectionNotFoundError, ConnectionUnavailableError):
            raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE) from None

    def get(self, identity: str, remaining_seconds: float) -> dict[str, Any]:
        deadline = monotonic() + remaining_seconds
        selected = UUID(identity)
        if selected not in self.identities:
            raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE)
        try:
            connection = self.service.authorize(self.owner_id, selected)
        except ConnectionUnavailableError:
            raise NodeExecutionError(FailureCode.CONNECTION_UNAVAILABLE) from None
        # Authorization/decryption has closed its session; the HTTP executor pins public DNS.
        return get_json(
            connection,
            timeout_seconds=deadline - monotonic(),
            max_response_bytes=MAX_AGENT_HTTP_BYTES,
        )
