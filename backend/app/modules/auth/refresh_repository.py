"""Caller-owned refresh persistence and a single family lock for every rotation."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import RefreshSession, RefreshToken


class RefreshRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(self, user_id: UUID, expires_at: datetime) -> RefreshSession:
        family = RefreshSession(user_id=user_id, expires_at=expires_at)
        self.session.add(family)
        self.session.flush()
        return family

    def add_token(self, session_id: UUID, token_hash: str, csrf_hash: str) -> RefreshToken:
        token = RefreshToken(session_id=session_id, token_hash=token_hash, csrf_hash=csrf_hash)
        self.session.add(token)
        self.session.flush()
        return token

    def find_token(self, token_hash: str) -> RefreshToken | None:
        return self.session.scalar(
            select(RefreshToken)
            .where(RefreshToken.token_hash == token_hash)
            .execution_options(populate_existing=True)
        )

    def lock_session(self, session_id: UUID) -> RefreshSession | None:
        return self.session.scalar(
            select(RefreshSession)
            .where(RefreshSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def lock_token(self, digest: str) -> tuple[RefreshSession, RefreshToken] | None:
        """Lock the shared family, then refresh a potentially stale token snapshot."""
        token = self.find_token(digest)
        if token is None:
            return None
        family = self.lock_session(token.session_id)
        token = self.find_token(digest)
        if family is None or token is None:
            return None
        return family, token

    def revoke_session(self, family: RefreshSession, now: datetime) -> None:
        """Caller holds the family lock; preserve the first revocation timestamp."""
        family.revoked_at = family.revoked_at or now
        self.session.flush()

    def consume(self, token: RefreshToken, now: datetime) -> None:
        token.consumed_at = now
        # Release the partial unique key before INSERTing its replacement.
        self.session.flush()
