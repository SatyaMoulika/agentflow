"""User queries and inserts in a caller-owned Session; no hashing or commits."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.database.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, *, email: str, password_hash: str, display_name: str) -> User:
        """Persist already-normalized input and an already-computed password hash."""
        user = User(email=email, password_hash=password_hash, display_name=display_name)
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_id(self, user_id: UUID) -> User | None:
        return self.session.get(User, user_id)

    def get_by_email(self, normalized_email: str) -> User | None:
        """Exact lookup; normalization/validation belongs to the auth input boundary."""
        return self.session.scalar(select(User).where(User.email == normalized_email))
