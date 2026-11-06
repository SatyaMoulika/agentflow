"""Bounded exponential delay; caller supplies the immutable run policy."""


def retry_delay(attempt_number: int, *, base_seconds: int, max_seconds: int) -> int:
    if (
        type(attempt_number) is not int
        or not 1 <= attempt_number <= 3
        or type(base_seconds) is not int
        or not 1 <= base_seconds <= 300
        or type(max_seconds) is not int
        or not base_seconds <= max_seconds <= 3600
    ):
        raise ValueError("Invalid retry policy")
    return min(base_seconds * 2 ** (attempt_number - 1), max_seconds)
