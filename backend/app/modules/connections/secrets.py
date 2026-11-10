"""Authenticated encryption bound to the owning connection, never to workflow JSON."""

import json
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr


class ConnectionUnavailableError(Exception):
    """Missing configuration, revoked connection or unusable protected credential."""


def cipher(key: SecretStr | None) -> Fernet:
    if key is None:
        raise ConnectionUnavailableError()
    try:
        return Fernet(key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError):
        raise ConnectionUnavailableError() from None


def encrypt(key: SecretStr | None, owner: UUID, connection: UUID, secret: SecretStr) -> str:
    envelope = json.dumps([str(owner), str(connection), secret.get_secret_value()])
    return cipher(key).encrypt(envelope.encode()).decode("ascii")


def decrypt(key: SecretStr | None, owner: UUID, connection: UUID, token: str) -> SecretStr:
    try:
        envelope = json.loads(cipher(key).decrypt(token.encode("ascii")))
        if (
            not isinstance(envelope, list)
            or len(envelope) != 3
            or envelope[:2] != [str(owner), str(connection)]
            or not isinstance(envelope[2], str)
        ):
            raise ValueError()
        return SecretStr(envelope[2])
    except (InvalidToken, ValueError, UnicodeError, TypeError):
        raise ConnectionUnavailableError() from None
