"""Access JWT signing/validation with an application-owned algorithm and claim policy."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from pydantic import SecretStr


class InvalidAccessTokenError(Exception):
    """Malformed, expired, incorrectly signed or inappropriate access credential."""


class AccessTokens:
    def __init__(self, *, secret: SecretStr, issuer: str, audience: str, ttl_seconds: int) -> None:
        self._secret = secret
        self.issuer = issuer
        self.audience = audience
        self.ttl_seconds = ttl_seconds

    def issue(self, user_id: UUID) -> str:
        now = int(datetime.now(UTC).timestamp())
        return jwt.encode(
            {
                "sub": str(user_id),
                "iss": self.issuer,
                "aud": self.audience,
                "iat": now,
                "nbf": now,
                "exp": now + self.ttl_seconds,
                "jti": str(uuid4()),
                "token_type": "access",
            },
            self._secret.get_secret_value(),
            algorithm="HS256",
            headers={"typ": "at+jwt"},
        )

    def subject(self, token: str) -> UUID:
        try:
            if len(token) > 8192:
                raise ValueError("Oversized token")
            decoded = jwt.decode_complete(
                token,
                self._secret.get_secret_value(),
                algorithms=["HS256"],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "require": ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "token_type"],
                    "strict_aud": True,
                },
            )
            claims = decoded["payload"]
            header = decoded["header"]
            if header.get("typ") != "at+jwt" or header.get("crit"):
                raise ValueError("Unsupported token header")
            if claims["token_type"] != "access":
                raise ValueError("Wrong token purpose")
            if any(type(claims[name]) is not int for name in ("iat", "nbf", "exp")):
                raise ValueError("Invalid numeric dates")
            if claims["nbf"] != claims["iat"] or not (
                0 < claims["exp"] - claims["iat"] <= self.ttl_seconds
            ):
                raise ValueError("Invalid token lifetime")
            subject = UUID(claims["sub"])
            token_id = UUID(claims["jti"])
            if str(subject) != claims["sub"] or str(token_id) != claims["jti"]:
                raise ValueError("Invalid token identity")
            return subject
        except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError):
            raise InvalidAccessTokenError() from None
