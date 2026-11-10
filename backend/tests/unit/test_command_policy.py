"""Command identity and bounded policy input without database access."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.executions.commands import key_digest, request_digest
from app.modules.executions.schemas import RunCreateRequest, RunRetryRequest


@pytest.mark.parametrize("value", [0, 4, True, "2", 1.5, None])
@pytest.mark.parametrize("schema", [RunCreateRequest, RunRetryRequest])
def test_attempt_budget_is_strict_and_bounded(value: object, schema: type) -> None:
    data = {"max_attempts": value}
    if schema is RunCreateRequest:
        data.update(workflow_version_id=uuid4(), input={})
    with pytest.raises(ValidationError):
        schema.model_validate(data)


def test_command_identity_ignores_object_order_but_preserves_types_and_policy() -> None:
    workflow, version = uuid4(), uuid4()
    a = RunCreateRequest(workflow_version_id=version, input={"A": 1, "b": False})
    b = RunCreateRequest(workflow_version_id=version, input={"b": False, "A": 1})
    assert request_digest(workflow, a, None) == request_digest(workflow, b, None)
    for changed in [
        a.model_copy(update={"input": {"A": True, "b": False}}),
        a.model_copy(update={"max_attempts": 2}),
        a.model_copy(update={"workflow_version_id": uuid4()}),
    ]:
        assert request_digest(workflow, a, None) != request_digest(workflow, changed, None)
    assert request_digest(workflow, a, None) != request_digest(workflow, a, uuid4())


@pytest.mark.parametrize("key", ["", "with space", "x" * 129, "é", "line\nbreak"])
def test_invalid_keys_never_become_receipts(key: str) -> None:
    with pytest.raises(ValueError):
        key_digest(key)
