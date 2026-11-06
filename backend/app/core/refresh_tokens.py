"""High-entropy opaque credentials; persist only digests, never the raw values."""

import hashlib
import re
import secrets
from dataclasses import dataclass

from pydantic import SecretStr

_FORMAT = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def new_opaque_token() -> SecretStr:
    return SecretStr(secrets.token_urlsafe(32))


def valid_opaque_token(value: str) -> bool:
    return _FORMAT.fullmatch(value) is not None


def token_digest(value: SecretStr) -> str:
    return hashlib.sha256(value.get_secret_value().encode("ascii")).hexdigest()


@dataclass(frozen=True)
class RefreshCredentials:
    refresh_token: SecretStr
    csrf_token: SecretStr
