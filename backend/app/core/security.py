"""Password hashing/verification; credentials never become log messages or public DTOs."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY
from pydantic import SecretStr

_password_hasher = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
# Public, non-account hash: unknown emails still perform one real Argon2 check.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$lIrE97T8DaZOM7IGiqURug$"
    "n78PqyTnFnRuQ5ikMtE2ogpmEQhR3obmUb+EjZv03rw"
)


def hash_password(password: SecretStr) -> str:
    """Argon2id with a generated salt; reveal plaintext only at the hashing boundary."""
    return _password_hasher.hash(password.get_secret_value())


def verify_password(password: SecretStr, encoded_hash: str | None) -> bool:
    """Keep unknown-account verification costly; never authenticate the dummy hash."""
    try:
        verified = _password_hasher.verify(
            encoded_hash if encoded_hash is not None else _DUMMY_HASH,
            password.get_secret_value(),
        )
    except (InvalidHashError, VerificationError):
        return False
    return verified and encoded_hash is not None
