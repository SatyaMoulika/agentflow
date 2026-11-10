"""Persistence snapshots preserve JSON types without accepting arbitrary Python values."""

import json
from uuid import uuid4

import pytest

from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload


def test_payload_copy_preserves_business_keys_and_is_independent() -> None:
    data = {"CustomerID": 1, "amount": 1.25, "flag": False, "nested": [{"界": None}]}
    copied = copy_payload(data)
    assert copied == data and copied is not data and copied["nested"] is not data["nested"]
    copied["nested"].append("new")
    assert len(data["nested"]) == 1


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        "private-value",
        {1: "key"},
        {"x": uuid4()},
        {"x": (1, 2)},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": "\ud800"},
        {"x": "界" * 90000},
    ],
)
def test_invalid_payloads_fail_with_no_raw_input(value: object) -> None:
    with pytest.raises(InvalidExecutionPayloadError) as outcome:
        copy_payload(value)
    assert str(outcome.value) == "Execution payloads must be bounded JSON objects."


def test_payload_exact_byte_and_depth_boundaries() -> None:
    overhead = len(json.dumps({"data": ""}, separators=(",", ":")).encode())
    assert copy_payload({"data": "x" * (262144 - overhead)})
    with pytest.raises(InvalidExecutionPayloadError):
        copy_payload({"data": "x" * (262145 - overhead)})
    nested = None
    for _ in range(31):
        nested = [nested]
    assert copy_payload({"data": nested})
    with pytest.raises(InvalidExecutionPayloadError):
        copy_payload({"data": [nested]})
