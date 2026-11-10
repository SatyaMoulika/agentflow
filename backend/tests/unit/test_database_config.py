"""Database configuration accepts only the supported driver and hides credentials."""

import pytest
from pydantic import SecretStr

from app.core.config import ConfigurationError, Settings, load_settings


def test_database_is_optional_and_secret_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings().database_url is None
    url = "postgresql+psycopg://user:private-password@localhost:15432/agentflow"
    monkeypatch.setenv("AGENTFLOW_DATABASE_URL", url)
    settings = load_settings()

    assert isinstance(settings.database_url, SecretStr)
    assert settings.database_url.get_secret_value() == url
    assert "private-password" not in repr(settings)
    assert "private-password" not in settings.model_dump_json()


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///private-password.db",
        "postgresql://user:private-password@localhost/agentflow",
        "postgresql+psycopg://user:private-password@/agentflow",
        "postgresql+psycopg://user:private-password@localhost",
        "postgresql+psycopg://user:private-password@localhost:invalid/agentflow",
        "",
    ],
)
def test_invalid_database_urls_fail_without_echoing_secrets(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("AGENTFLOW_DATABASE_URL", url)

    with pytest.raises(ConfigurationError) as error:
        load_settings()

    assert "database_url" in str(error.value)
    assert "private-password" not in str(error.value)
