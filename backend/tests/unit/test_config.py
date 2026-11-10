"""Settings precedence, validation and safe failure reporting."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import BACKEND_ENV_FILE, ConfigurationError, Settings, load_settings
from app.main import create_app


def test_defaults_need_no_external_service_configuration() -> None:
    settings = load_settings()

    assert settings.app_name == "AgentFlow API"
    assert settings.environment == "development"
    assert settings.debug is False
    assert settings.docs_enabled is True
    assert settings.log_level == "INFO"


def test_environment_values_are_parsed_and_name_is_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_APP_NAME", "  Local API  ")
    monkeypatch.setenv("AGENTFLOW_ENVIRONMENT", "testing")
    monkeypatch.setenv("AGENTFLOW_DEBUG", "true")
    monkeypatch.setenv("AGENTFLOW_DOCS_ENABLED", "false")
    monkeypatch.setenv("AGENTFLOW_LOG_LEVEL", "DEBUG")

    settings = load_settings()

    assert settings.app_name == "Local API"
    assert settings.environment == "testing"
    assert settings.debug is True
    assert settings.docs_enabled is False
    assert settings.log_level == "DEBUG"


def test_explicit_values_override_environment_which_overrides_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        'AGENTFLOW_APP_NAME="File API"\nAGENTFLOW_DOCS_ENABLED=false\nUNRELATED_KEY=ignored\n',
        encoding="utf-8",
    )

    # Configure the temporary source explicitly; Pydantic's synthesized type
    # signature exposes model fields, not every BaseSettings runtime keyword.
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    assert Settings().app_name == "File API"
    monkeypatch.setenv("AGENTFLOW_APP_NAME", "Environment API")
    settings = Settings()
    assert settings.app_name == "Environment API"
    assert settings.docs_enabled is False
    assert Settings(app_name="Explicit API").app_name == "Explicit API"
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    assert Settings().docs_enabled is True


def test_configured_dotenv_path_is_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dotenv = tmp_path / "configured.env"
    dotenv.write_text("AGENTFLOW_APP_NAME=Configured API\n", encoding="utf-8")
    working_directory = tmp_path / "elsewhere"
    working_directory.mkdir()
    (working_directory / ".env").write_text("AGENTFLOW_APP_NAME=Wrong API\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", dotenv)
    monkeypatch.chdir(working_directory)

    assert load_settings().app_name == "Configured API"
    assert BACKEND_ENV_FILE.is_absolute()
    assert BACKEND_ENV_FILE == Path(__file__).resolve().parents[2] / ".env"


@pytest.mark.parametrize(
    ("key", "value", "field"),
    [
        ("AGENTFLOW_APP_NAME", "  ", "app_name"),
        ("AGENTFLOW_APP_NAME", "x" * 101, "app_name"),
        ("AGENTFLOW_ENVIRONMENT", "invalid-private-value", "environment"),
        ("AGENTFLOW_DEBUG", "invalid-private-value", "debug"),
        ("AGENTFLOW_DOCS_ENABLED", "invalid-private-value", "docs_enabled"),
        ("AGENTFLOW_LOG_LEVEL", "invalid-private-value", "log_level"),
    ],
)
def test_invalid_configuration_fails_before_app_creation_without_echoing_values(
    monkeypatch: pytest.MonkeyPatch, key: str, value: str, field: str
) -> None:
    monkeypatch.setenv(key, value)

    with pytest.raises(ConfigurationError) as error:
        create_app()

    assert field in str(error.value)
    assert "invalid-private-value" not in str(error.value)
    assert "x" * 101 not in str(error.value)
    assert error.value.__suppress_context__ is True


def test_production_rejects_debug_but_allows_safe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_ENVIRONMENT", "production")
    assert load_settings().debug is False
    monkeypatch.setenv("AGENTFLOW_DEBUG", "true")

    with pytest.raises(ConfigurationError, match="debug must be disabled in production"):
        create_app()


def test_validated_settings_cannot_be_mutated() -> None:
    settings = Settings()

    with pytest.raises(ValidationError, match="frozen"):
        settings.debug = True


def test_factories_read_settings_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTFLOW_APP_NAME", "First API")
    first = create_app()
    monkeypatch.setenv("AGENTFLOW_APP_NAME", "Second API")
    second = create_app()

    assert first.state.settings.app_name == "First API"
    assert second.state.settings.app_name == "Second API"
    assert first.state.settings is not second.state.settings
