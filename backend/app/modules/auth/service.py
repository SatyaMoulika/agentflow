"""Registration, credential verification and current active account resolution."""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError, OperationalError, TimeoutError

from app.core.refresh_tokens import RefreshCredentials, new_opaque_token, token_digest
from app.core.security import hash_password, verify_password
from app.core.tokens import AccessTokens
from app.infrastructure.database.session import Database
from app.modules.auth.exceptions import (
    AuthenticationError,
    AuthStorageUnavailableError,
    CsrfError,
    EmailAlreadyRegisteredError,
    RefreshRejectedError,
)
from app.modules.auth.refresh_repository import RefreshRepository
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import LoginRequest, LoginResponse, RegisterRequest, UserResponse


@dataclass(frozen=True)
class AuthResult:
    body: LoginResponse
    credentials: RefreshCredentials
    expires_at: datetime


def session_result(
    user: UserResponse, tokens: AccessTokens, credentials: RefreshCredentials, expires_at: datetime
) -> AuthResult:
    return AuthResult(
        body=LoginResponse(
            access_token=tokens.issue(user.id),
            csrf_token=credentials.csrf_token.get_secret_value(),
            expires_in=tokens.ttl_seconds,
            user=user,
        ),
        credentials=credentials,
        expires_at=expires_at,
    )


class AuthService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def register(self, data: RegisterRequest) -> UserResponse:
        """Use the unique constraint as the authority, including simultaneous signups."""
        password_hash = hash_password(data.password)
        try:
            with self.database.unit_of_work() as session:
                user = UserRepository(session).add(
                    email=str(data.email),
                    password_hash=password_hash,
                    display_name=data.display_name,
                )
                result = UserResponse.model_validate(user)
        except IntegrityError as error:
            original = error.orig
            constraint = getattr(getattr(original, "diag", None), "constraint_name", None)
            if getattr(original, "sqlstate", None) == "23505" and constraint == "uq_users_email":
                raise EmailAlreadyRegisteredError() from None
            raise
        except (OperationalError, TimeoutError):
            raise AuthStorageUnavailableError() from None
        return result

    def login(
        self, data: LoginRequest, tokens: AccessTokens, refresh_ttl_seconds: int
    ) -> AuthResult:
        """Close the read transaction before Argon2; recheck status before issuing."""
        try:
            with self.database.session() as session:
                user = UserRepository(session).get_by_email(str(data.email))
                user_id = user.id if user is not None else None
                encoded_hash = user.password_hash if user is not None else None
            verified = verify_password(data.password, encoded_hash)
            if not verified or user_id is None:
                raise AuthenticationError()
            with self.database.unit_of_work() as session:
                current = UserRepository(session).get_by_id(user_id)
                if (
                    current is None
                    or not current.is_active
                    or current.password_hash != encoded_hash
                ):
                    raise AuthenticationError()
                public_user = UserResponse.model_validate(current)
                credentials = RefreshCredentials(new_opaque_token(), new_opaque_token())
                expires_at = datetime.now(UTC) + timedelta(seconds=refresh_ttl_seconds)
                repository = RefreshRepository(session)
                family = repository.create_session(current.id, expires_at)
                repository.add_token(
                    family.id,
                    token_digest(credentials.refresh_token),
                    token_digest(credentials.csrf_token),
                )
                result = session_result(public_user, tokens, credentials, expires_at)
        except (OperationalError, TimeoutError):
            raise AuthStorageUnavailableError() from None
        return result

    def refresh(self, credentials: RefreshCredentials, tokens: AccessTokens) -> AuthResult:
        """Serialize per family; commit replay revocation before reporting rejection."""
        result: AuthResult | None = None
        try:
            with self.database.unit_of_work() as session:
                repository = RefreshRepository(session)
                digest = token_digest(credentials.refresh_token)
                locked = repository.lock_token(digest)
                if locked is None:
                    raise RefreshRejectedError()
                family, token = locked
                if not secrets.compare_digest(
                    token.csrf_hash, token_digest(credentials.csrf_token)
                ):
                    raise CsrfError()
                now = datetime.now(UTC)
                if token.consumed_at is not None:
                    repository.revoke_session(family, now)
                elif family.revoked_at is None and family.expires_at > now:
                    user = UserRepository(session).get_by_id(family.user_id)
                    if user is None or not user.is_active:
                        repository.revoke_session(family, now)
                    else:
                        replacement = RefreshCredentials(new_opaque_token(), new_opaque_token())
                        repository.consume(token, now)
                        repository.add_token(
                            family.id,
                            token_digest(replacement.refresh_token),
                            token_digest(replacement.csrf_token),
                        )
                        result = session_result(
                            UserResponse.model_validate(user),
                            tokens,
                            replacement,
                            family.expires_at,
                        )
                # Do not raise inside this context after revoking: that would roll it back.
        except (OperationalError, TimeoutError):
            raise AuthStorageUnavailableError() from None
        if result is None:
            raise RefreshRejectedError()
        return result

    def logout(self, credentials: RefreshCredentials) -> None:
        """Revoke one family, including through a consumed token; commit before clearing."""
        try:
            with self.database.unit_of_work() as session:
                repository = RefreshRepository(session)
                locked = repository.lock_token(token_digest(credentials.refresh_token))
                if locked is None:
                    return  # Unknown credentials cannot identify/revoke another family.
                family, token = locked
                if not secrets.compare_digest(
                    token.csrf_hash, token_digest(credentials.csrf_token)
                ):
                    raise CsrfError()
                repository.revoke_session(family, datetime.now(UTC))
        except (OperationalError, TimeoutError):
            raise AuthStorageUnavailableError() from None

    def current_user(self, user_id: UUID) -> UserResponse:
        """A signed subject alone does not prove the account still exists/is active."""
        try:
            with self.database.session() as session:
                user = UserRepository(session).get_by_id(user_id)
                if user is None or not user.is_active:
                    raise AuthenticationError()
                return UserResponse.model_validate(user)
        except (OperationalError, TimeoutError):
            raise AuthStorageUnavailableError() from None
