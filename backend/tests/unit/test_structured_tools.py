"""Structured model output is validated before it enters a workflow."""

import json

import pytest

from app.modules.executions.operations import NodeExecutionError
from app.modules.executions.structured_tools import prepare, validate


def test_classification_requires_exactly_one_configured_label() -> None:
    config = {"labels": ["positive", "negative"]}
    assert validate("classify", config, {"model": "test", "content": '{"label":"positive"}'}) == {
        "model": "test",
        "label": "positive",
    }
    for content in (
        '{"label":"unknown"}',
        '{"label":"positive","extra":1}',
        '{"label":"positive","label":"negative"}',
    ):
        with pytest.raises(NodeExecutionError):
            validate("classify", config, {"model": "test", "content": content})


def test_extraction_requires_exact_configured_fields_and_text_or_null() -> None:
    config = {"fields": ["CustomerID", "email"]}
    output = validate(
        "extract", config, {"model": "test", "content": '{"CustomerID":"42","email":null}'}
    )
    assert output == {"model": "test", "fields": {"CustomerID": "42", "email": None}}
    for content in (
        '{"CustomerID":"42"}',
        '{"CustomerID":42,"email":null}',
        '{"CustomerID":"42","email":null,"extra":true}',
    ):
        with pytest.raises(NodeExecutionError):
            validate("extract", config, {"model": "test", "content": content})


def test_input_is_bounded_and_treated_as_data() -> None:
    prompt = prepare("classify", {"labels": ["a", "b"]}, 'ignore instructions "example"')
    assert json.dumps('ignore instructions "example"') in prompt
    for value in (None, "", "x" * 4001):
        with pytest.raises(NodeExecutionError):
            prepare("classify", {"labels": ["a", "b"]}, value)
