"""Bounded native JSON snapshots; no coercion, payload logging or guessed redaction."""

import json
import math
from typing import Any


class InvalidExecutionPayloadError(Exception):
    def __init__(self) -> None:
        super().__init__("Execution payloads must be bounded JSON objects.")


def copy_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InvalidExecutionPayloadError()
    pending: list[tuple[Any, int]] = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise InvalidExecutionPayloadError()
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise InvalidExecutionPayloadError()
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
        elif type(item) not in (str, bool, int, float, type(None)):
            raise InvalidExecutionPayloadError()
        elif isinstance(item, float) and not math.isfinite(item):
            raise InvalidExecutionPayloadError()
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 262144:
            raise InvalidExecutionPayloadError()
        return json.loads(encoded)
    except (ValueError, TypeError, UnicodeError):
        raise InvalidExecutionPayloadError() from None
