"""Synthetic live checks must be explicitly requested and never print payloads."""

from app.core.config import Settings
from scripts import smoke_integrations as smoke


def test_default_cli_neither_loads_private_settings_nor_calls_network(monkeypatch, capsys) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("Live checks need explicit opt-in")

    for name in ("load_settings", "get_json", "complete", "generate"):
        monkeypatch.setattr(smoke, name, forbidden)
    assert smoke.main([]) == 0
    assert smoke.main(["--groq"]) == 0
    assert "No requests sent" in capsys.readouterr().out


def test_live_provider_still_requires_configuration(monkeypatch, capsys) -> None:
    monkeypatch.setattr(smoke, "load_settings", lambda: Settings())

    def forbidden(*args, **kwargs):
        raise AssertionError("Missing configuration must not contact the provider")

    monkeypatch.setattr(smoke, "complete", forbidden)
    assert smoke.main(["--live", "--groq"]) == 2
    assert "not_configured" in capsys.readouterr().out
