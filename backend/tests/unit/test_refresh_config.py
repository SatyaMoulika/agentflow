"""Refresh credential primitives and explicit safe cookie/origin configuration."""

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import ConfigurationError, Settings, load_settings
from app.core.refresh_tokens import new_opaque_token, token_digest, valid_opaque_token


def test_random_opaque_tokens_and_digests_hide_credentials() -> None:
    first, second = new_opaque_token(), new_opaque_token()
    assert first != second
    assert valid_opaque_token(first.get_secret_value())
    assert len(token_digest(first)) == 64
    assert token_digest(first) == token_digest(SecretStr(first.get_secret_value()))
    assert first.get_secret_value() not in repr(first) + token_digest(first)


@pytest.mark.parametrize("value", ["", "x" * 42, "x" * 44, "a" * 42 + "!", "é" * 43])
def test_rejects_malformed_cookie_values(value: str) -> None:
    assert not valid_opaque_token(value)


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "*",
        "https://*.example.com",
        "https://a.test/",
        "https://a.test/p",
        "https://u:p@a.test",
        "ftp://a.test",
        "https://a.test:99999",
    ],
)
def test_rejects_non_origin_configuration(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(auth_allowed_origins=(origin,))


def test_production_requires_secure_cookies_and_https_auth_origins() -> None:
    with pytest.raises(ValidationError, match="refresh_cookie_secure"):
        Settings(environment="production", refresh_cookie_secure=False)
    with pytest.raises(ValidationError, match="HTTPS origins"):
        Settings(environment="production", jwt_secret_key=SecretStr("test-only-" * 5))
    settings = Settings(
        environment="production",
        jwt_secret_key=SecretStr("test-only-" * 5),
        auth_allowed_origins=("https://app.example.com",),
    )
    assert settings.refresh_cookie_secure is True


@pytest.mark.parametrize("seconds", [299, 2592001])
def test_refresh_ttl_is_bounded(seconds: int) -> None:
    with pytest.raises(ValidationError):
        Settings(refresh_token_ttl_seconds=seconds)


def test_origin_list_environment_and_safe_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_AUTH_ALLOWED_ORIGINS", '["https://api.example.com"]')
    assert load_settings().auth_allowed_origins == ("https://api.example.com",)
    monkeypatch.setenv("AGENTFLOW_AUTH_ALLOWED_ORIGINS", '["https://private.invalid/path"]')
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "private.invalid" not in str(error.value)


def test_malformed_origin_json_is_reported_without_raw_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTFLOW_AUTH_ALLOWED_ORIGINS", "private-invalid-json")
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "private-invalid-json" not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_local_frontend_proxy_origins_are_explicit_and_bounded() -> None:
    origins = Settings().auth_allowed_origins
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
    assert "http://untrusted.example:5173" not in origins
