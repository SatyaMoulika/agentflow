"""Live evaluation must be explicit, bounded, and never leak provider errors."""

import sys

import pytest

from app.core.config import Settings
from app.modules.executions.groq_provider import GroqError
from app.modules.workflows.generation import InvalidProposalError
from scripts import evaluate_workflows


def test_cli_lists_cases_without_loading_configuration_or_calling_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_workflows"])

    def forbidden(*args, **kwargs):
        raise AssertionError("No configuration or provider access without --live")

    monkeypatch.setattr(evaluate_workflows, "load_settings", forbidden)
    monkeypatch.setattr(evaluate_workflows, "generate", forbidden)
    assert evaluate_workflows.main() == 0
    assert "branch_amount" in capsys.readouterr().out


def test_cli_stops_after_rate_limit_without_exposing_exception(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_workflows", "--live"])
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-test-secret")
    monkeypatch.setattr(evaluate_workflows, "load_settings", Settings)
    calls = []

    def limited(settings: Settings, prompt: str):
        calls.append(prompt)
        raise GroqError(429)

    monkeypatch.setattr(evaluate_workflows, "generate", limited)
    assert evaluate_workflows.main() == 1
    result = capsys.readouterr().out
    assert len(calls) == 1 and "rate_limited" in result
    assert "synthetic-test-secret" not in result and calls[0] not in result


def test_cli_fails_without_key_without_calling_provider(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_workflows", "--live"])
    monkeypatch.setattr(evaluate_workflows, "load_settings", Settings)

    def forbidden(*args, **kwargs):
        raise AssertionError("No provider access without key")

    monkeypatch.setattr(evaluate_workflows, "generate", forbidden)
    assert evaluate_workflows.main() == 2
    assert "GROQ_API_KEY" in capsys.readouterr().err


def test_cli_reports_only_safe_validation_categories(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["evaluate_workflows", "--live", "--case", "branch_amount"])
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-test-secret")
    monkeypatch.setattr(evaluate_workflows, "load_settings", Settings)

    def invalid(settings: Settings, prompt: str):
        raise InvalidProposalError("invalid_graph", ("INVALID_OUTPUT_HANDLES",))

    monkeypatch.setattr(evaluate_workflows, "generate", invalid)
    assert evaluate_workflows.main() == 1
    output = capsys.readouterr().out
    assert "invalid_proposal:invalid_graph:INVALID_OUTPUT_HANDLES" in output
    assert "synthetic-test-secret" not in output
