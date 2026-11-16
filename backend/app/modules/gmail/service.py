"""Owner-scoped Gmail authorization with single-use state and short transactions."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, TimeoutError

from app.core.config import Settings
from app.infrastructure.database.session import Database
from app.modules.connections.secrets import ConnectionUnavailableError, decrypt, encrypt
from app.modules.gmail import provider
from app.modules.gmail.models import GmailAuthorization, GmailConnection
from app.modules.gmail.schemas import GmailConnectionResponse


class GmailAuthorizationRejected(Exception):
    """Expired, already consumed, missing or foreign authorization state."""


class GmailNotConfigured(Exception):
    """The operator has not configured Gmail OAuth and the callback origin."""


class GmailConnectionNotFound(Exception):
    """Missing and unowned connections have identical public behavior."""


class GmailService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def _configuration(self) -> tuple[str, SecretStr, str]:
        client, secret, redirect = (
            self.settings.gmail_client_id,
            self.settings.gmail_client_secret,
            self.settings.gmail_redirect_uri,
        )
        if not client or secret is None or not secret.get_secret_value().strip() or not redirect:
            raise GmailNotConfigured()
        if self.settings.connection_encryption_key is None:
            raise GmailNotConfigured()
        parsed = urlsplit(redirect)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self.settings.auth_allowed_origins or (
            self.settings.environment == "production" and parsed.scheme != "https"
        ):
            raise GmailNotConfigured()
        return client, secret, redirect

    def begin(self, owner_id: UUID) -> str:
        client, _, redirect = self._configuration()
        state, verifier, challenge = provider.oauth_parameters()
        attempt_id = uuid4()
        protected = encrypt(self.settings.connection_encryption_key, owner_id, attempt_id, verifier)
        try:
            with self.database.unit_of_work() as session:
                now = session.scalar(select(func.clock_timestamp()))
                assert now is not None
                session.add(
                    GmailAuthorization(
                        id=attempt_id,
                        owner_id=owner_id,
                        state_digest=hashlib.sha256(state.encode("ascii")).hexdigest(),
                        encrypted_verifier=protected,
                        created_at=now,
                        expires_at=now + timedelta(minutes=10),
                    )
                )
            return provider.authorization_url(
                client_id=client, redirect_uri=redirect, state=state, challenge=challenge
            )
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def complete(self, owner_id: UUID, state: str, code: SecretStr) -> GmailConnectionResponse:
        client, secret, redirect = self._configuration()
        try:
            with self.database.unit_of_work() as session:
                attempt = session.scalar(
                    select(GmailAuthorization)
                    .where(
                        GmailAuthorization.owner_id == owner_id,
                        GmailAuthorization.state_digest
                        == hashlib.sha256(state.encode("ascii")).hexdigest(),
                    )
                    .with_for_update()
                )
                now = session.scalar(select(func.clock_timestamp()))
                if (
                    attempt is None
                    or now is None
                    or attempt.consumed_at is not None
                    or attempt.expires_at <= now
                    or attempt.encrypted_verifier is None
                ):
                    raise GmailAuthorizationRejected()
                identity, encrypted_verifier = attempt.id, attempt.encrypted_verifier
                attempt.consumed_at, attempt.encrypted_verifier = now, None
            verifier = decrypt(
                self.settings.connection_encryption_key, owner_id, identity, encrypted_verifier
            )
            # The state is consumed before network I/O. Failed exchanges require fresh consent.
            token = provider.exchange_code(
                client_id=client,
                client_secret=secret,
                redirect_uri=redirect,
                code=code,
                verifier=verifier,
            )
            if token.refresh_token is None:
                raise provider.GmailProviderError("AUTHORIZATION_FAILED")
            connection_id = uuid4()
            protected = encrypt(
                self.settings.connection_encryption_key,
                owner_id,
                connection_id,
                token.refresh_token,
            )
            with self.database.unit_of_work() as session:
                connection = GmailConnection(
                    id=connection_id, owner_id=owner_id, encrypted_refresh_token=protected
                )
                session.add(connection)
                session.flush()
                return GmailConnectionResponse.model_validate(connection)
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def list_connections(self, owner_id: UUID) -> list[GmailConnectionResponse]:
        try:
            with self.database.session() as session:
                rows = session.scalars(
                    select(GmailConnection)
                    .where(GmailConnection.owner_id == owner_id)
                    .order_by(GmailConnection.created_at.desc(), GmailConnection.id)
                    .limit(100)
                )
                return [GmailConnectionResponse.model_validate(row) for row in rows]
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def revoke(self, owner_id: UUID, identity: UUID) -> None:
        try:
            with self.database.unit_of_work() as session:
                row = session.scalar(
                    select(GmailConnection)
                    .where(GmailConnection.id == identity, GmailConnection.owner_id == owner_id)
                    .with_for_update()
                )
                if row is None:
                    raise GmailConnectionNotFound()
                if row.revoked_at is None:
                    row.revoked_at = session.scalar(select(func.clock_timestamp()))
                    row.encrypted_refresh_token = None
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def _token(self, owner_id: UUID, identity: UUID) -> SecretStr:
        client, secret, _ = self._configuration()
        try:
            with self.database.session() as session:
                row = session.scalar(
                    select(GmailConnection).where(
                        GmailConnection.id == identity,
                        GmailConnection.owner_id == owner_id,
                        GmailConnection.revoked_at.is_(None),
                    )
                )
                if row is None or row.encrypted_refresh_token is None:
                    raise GmailConnectionNotFound()
                encrypted = row.encrypted_refresh_token
            refresh = decrypt(
                self.settings.connection_encryption_key, owner_id, identity, encrypted
            )
            token = provider.refresh_access_token(
                client_id=client, client_secret=secret, refresh_token=refresh
            )
            self._check_active(owner_id, identity)
            return token.access_token
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def _check_active(self, owner_id: UUID, identity: UUID) -> None:
        try:
            with self.database.session() as session:
                active = session.scalar(
                    select(GmailConnection.id).where(
                        GmailConnection.id == identity,
                        GmailConnection.owner_id == owner_id,
                        GmailConnection.revoked_at.is_(None),
                    )
                )
                if active is None:
                    raise GmailConnectionNotFound()
        except (OperationalError, TimeoutError):
            raise ConnectionUnavailableError() from None

    def list_messages(self, owner_id: UUID, identity: UUID) -> list[str]:
        token = self._token(owner_id, identity)
        messages = provider.list_message_ids(token)
        self._check_active(owner_id, identity)
        return messages

    def read_message(self, owner_id: UUID, identity: UUID, message_id: str) -> str:
        provider.validate_message_id(message_id)
        token = self._token(owner_id, identity)
        message = provider.read_message(token, message_id)
        self._check_active(owner_id, identity)
        return provider.plain_text_message(message)
