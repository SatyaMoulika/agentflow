"""Authentication is opt-in, with no default signing secret or permissive lifetime."""

import pytest
from pydantic import SecretStr

from app.core.config import ConfigurationError, Settings, load_settings


def test_auth_defaults_and_private_key_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().jwt_secret_key is None
    assert Settings().access_token_ttl_seconds == 900
    key = "test-only-long-random-key-placeholder-123456789"
    monkeypatch.setenv("AGENTFLOW_JWT_SECRET_KEY", key)
    monkeypatch.setenv("AGENTFLOW_JWT_ISSUER", "local-issuer")
    monkeypatch.setenv("AGENTFLOW_JWT_AUDIENCE", "local-audience")
    monkeypatch.setenv("AGENTFLOW_ACCESS_TOKEN_TTL_SECONDS", "120")
    settings = load_settings()
    assert settings.jwt_secret_key == SecretStr(key)
    assert settings.jwt_issuer == "local-issuer" and settings.jwt_audience == "local-audience"
    assert settings.access_token_ttl_seconds == 120
    assert key not in repr(settings) + settings.model_dump_json()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AGENTFLOW_JWT_SECRET_KEY", ""),
        ("AGENTFLOW_JWT_SECRET_KEY", "private-short-key"),
        ("AGENTFLOW_JWT_SECRET_KEY", " " + "k" * 32),
        ("AGENTFLOW_JWT_SECRET_KEY", "k" * 4097),
        ("AGENTFLOW_ACCESS_TOKEN_TTL_SECONDS", "59"),
        ("AGENTFLOW_ACCESS_TOKEN_TTL_SECONDS", "3601"),
        ("AGENTFLOW_JWT_ISSUER", " "),
        ("AGENTFLOW_JWT_AUDIENCE", " "),
    ],
)
def test_invalid_auth_configuration_is_safe(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str
) -> None:
    monkeypatch.setenv(key, value)
    with pytest.raises(ConfigurationError) as error:
        load_settings()
    assert "private-short-key" not in str(error.value)
    assert "k" * 32 not in str(error.value)
