"""Real signatures and hostile claims exercise the access-token trust boundary."""

from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from pydantic import SecretStr

from app.core.tokens import AccessTokens, InvalidAccessTokenError

KEY = "test-only-signing-key-not-a-deployment-secret-12345"


@pytest.fixture
def tokens() -> AccessTokens:
    return AccessTokens(
        secret=SecretStr(KEY), issuer="agentflow", audience="agentflow-api", ttl_seconds=900
    )


@pytest.fixture
def claims(tokens: AccessTokens) -> dict:
    return jwt.decode(tokens.issue(uuid4()), KEY, algorithms=["HS256"], audience="agentflow-api")


def test_issued_token_has_bounded_lifetime_unique_id_and_no_account_secrets(
    tokens: AccessTokens,
) -> None:
    user_id = uuid4()
    first, second = tokens.issue(user_id), tokens.issue(user_id)
    assert tokens.subject(first) == user_id
    assert first != second
    decoded = jwt.decode_complete(first, KEY, algorithms=["HS256"], audience="agentflow-api")
    assert decoded["header"] == {"alg": "HS256", "typ": "at+jwt"}
    data = decoded["payload"]
    assert set(data) == {"sub", "iss", "aud", "iat", "nbf", "exp", "jti", "token_type"}
    assert data["exp"] - data["iat"] == 900
    assert data["nbf"] == data["iat"]
    assert data["token_type"] == "access"


@pytest.mark.parametrize("missing", ["sub", "iss", "aud", "iat", "nbf", "exp", "jti", "token_type"])
def test_rejects_missing_required_claim(tokens: AccessTokens, claims: dict, missing: str) -> None:
    del claims[missing]
    token = jwt.encode(claims, KEY, algorithm="HS256", headers={"typ": "at+jwt"})
    with pytest.raises(InvalidAccessTokenError):
        tokens.subject(token)


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "other-service"},
        {"aud": "other-audience"},
        {"aud": ["agentflow-api", "other-audience"]},
        {"token_type": "refresh"},
        {"sub": "not-a-uuid"},
        {"sub": None},
        {"jti": "not-a-uuid"},
        {"iat": True},
        {"iat": "123"},
        {"exp": float("inf")},
        {"exp": "9999999999"},
        {"exp": 9999999999},
        {"nbf": int(datetime.now(UTC).timestamp()) + 3600},
        {"iat": int(datetime.now(UTC).timestamp()) + 3600},
        {"iat": 1, "nbf": 1, "exp": 2},
    ],
)
def test_rejects_inappropriate_claims(tokens: AccessTokens, claims: dict, overrides: dict) -> None:
    token = jwt.encode(claims | overrides, KEY, algorithm="HS256", headers={"typ": "at+jwt"})
    with pytest.raises(InvalidAccessTokenError):
        tokens.subject(token)


@pytest.mark.parametrize(
    ("algorithm", "key", "headers"),
    [
        ("none", None, {"typ": "at+jwt"}),
        ("HS512", KEY * 2, {"typ": "at+jwt"}),
        ("HS256", "different-test-signing-secret-of-at-least-32-bytes", {"typ": "at+jwt"}),
        ("HS256", KEY, {"typ": "JWT"}),
        ("HS256", KEY, {"typ": "at+jwt", "crit": ["unknown"]}),
    ],
)
def test_rejects_wrong_signature_algorithm_and_header(
    tokens: AccessTokens, claims: dict, algorithm: str, key: str | None, headers: dict
) -> None:
    token = jwt.encode(claims, key if key is not None else "", algorithm=algorithm, headers=headers)
    with pytest.raises(InvalidAccessTokenError):
        tokens.subject(token)


@pytest.mark.parametrize("token", ["", "private-invalid-token", "a.b.c", "x" * 8193])
def test_malformed_tokens_become_a_safe_domain_failure(tokens: AccessTokens, token: str) -> None:
    with pytest.raises(InvalidAccessTokenError) as error:
        tokens.subject(token)
    assert str(error.value) == ""
