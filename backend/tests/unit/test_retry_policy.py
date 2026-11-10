"""Bounded delay policy rejects invalid state without sleeping or network calls."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.executions.retry_policy import retry_delay


@pytest.mark.parametrize(
    ("number", "base", "maximum", "expected"),
    [(1, 5, 60, 5), (2, 5, 60, 10), (2, 5, 7, 7), (2, 300, 300, 300)],
)
def test_bounded_exponential_delay(number, base, maximum, expected) -> None:
    assert retry_delay(number, base_seconds=base, max_seconds=maximum) == expected


@pytest.mark.parametrize(
    ("number", "base", "maximum"),
    [(0, 5, 60), (4, 5, 60), (True, 5, 60), (1, 0, 60), (1, 301, 1000), (1, 5, 4), (1, 5, 3601)],
)
def test_invalid_policy_is_rejected(number, base, maximum) -> None:
    with pytest.raises(ValueError):
        retry_delay(number, base_seconds=base, max_seconds=maximum)


def test_config_defaults_and_invalid_policy() -> None:
    settings = Settings()
    assert settings.worker_retry_base_seconds == 5 and settings.worker_retry_max_seconds == 60
    with pytest.raises(ValidationError, match="must be at least"):
        Settings(worker_retry_base_seconds=30, worker_retry_max_seconds=20)
