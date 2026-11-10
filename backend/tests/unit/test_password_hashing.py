"""Real Argon2id hashes are salted, verifiable, and preserve password bytes."""

import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import VerifyMismatchError
from argon2.profiles import RFC_9106_LOW_MEMORY
from pydantic import SecretStr

from app.core.security import hash_password


def test_real_hash_uses_argon2id_profile_with_unique_salts() -> None:
    password = "  Example private passphrase  "
    first = hash_password(SecretStr(password))
    second = hash_password(SecretStr(password))

    assert first.startswith("$argon2id$")
    assert first != second
    assert password not in first
    assert extract_parameters(first) == RFC_9106_LOW_MEMORY
    verifier = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)
    assert verifier.verify(first, password)
    with pytest.raises(VerifyMismatchError):
        verifier.verify(first, password.strip())


def test_password_verification_preserves_spaces_and_rejects_unknown_or_corrupt_hashes() -> None:
    from app.core.security import verify_password

    password = SecretStr("  private login passphrase  ")
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password(SecretStr(password.get_secret_value().strip()), encoded)
    assert not verify_password(password, None)
    assert not verify_password(SecretStr("public dummy verification input"), None)
    assert not verify_password(password, "malformed stored hash")
