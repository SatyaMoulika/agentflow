"""Metadata, partial-update intent and bounded saved-definition contracts."""

import pytest
from pydantic import ValidationError

from app.modules.workflows.schemas import (
    WorkflowCreateRequest,
    WorkflowDefinition,
    WorkflowListParams,
    WorkflowUpdateRequest,
)


def test_create_trims_metadata_and_defaults_description() -> None:
    assert WorkflowCreateRequest(name="  Invoices  ").model_dump() == {
        "name": "Invoices",
        "description": "",
        "definition": None,
    }
    assert WorkflowCreateRequest(name="界" * 200, description="  text  ").description == "text"


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " "},
        {"name": "n" * 201},
        {"name": 123},
        {"name": "x", "description": None},
        {"name": "x", "description": "d" * 5001},
        {"name": "x", "owner_id": "injected"},
        {"name": "x", "status": "active"},
        {"name": "x", "definition": {}},
    ],
)
def test_create_rejects_invalid_or_privileged_fields(payload: dict) -> None:
    with pytest.raises(ValidationError):
        WorkflowCreateRequest.model_validate(payload)


def test_partial_patch_preserves_unset_fields_and_can_clear_description() -> None:
    name = WorkflowUpdateRequest(name="  Renamed  ")
    assert name.name == "Renamed" and name.description is None
    assert name.model_fields_set == {"name"}
    assert WorkflowUpdateRequest(description=" ").model_dump(exclude_unset=True) == {
        "description": ""
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": None},
        {"description": None},
        {"name": " "},
        {"description": 123},
        {"status": "draft"},
        {"current_version_id": "injected"},
        {"definition": {}},
    ],
)
def test_patch_rejects_empty_null_privilege_or_invalid_saves(payload: dict) -> None:
    with pytest.raises(ValidationError):
        WorkflowUpdateRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"page": 0},
        {"page": 1000001},
        {"page_size": 101},
        {"q": " "},
        {"status": "unknown"},
        {"owner_id": "injected"},
    ],
)
def test_listing_rejects_invalid_queries(payload: dict) -> None:
    with pytest.raises(ValidationError):
        WorkflowListParams.model_validate(payload)


DEFINITION = {"schema_version": "1.0", "nodes": [], "edges": []}


def test_definition_preserves_business_keys_and_accepts_incomplete_drafts() -> None:
    definition = {
        **DEFINITION,
        "nodes": [{"config": {"CustomerID": 12, "invoice_total": False, "nested": [None]}}],
        "EditorState": {"zoomLevel": 1.2},
    }
    saved = WorkflowCreateRequest.model_validate({"name": "Draft", "definition": definition})
    assert saved.definition is not None and saved.definition.model_dump() == definition
    patched = WorkflowUpdateRequest.model_validate(
        {"definition": definition, "expected_version": 0}
    )
    assert patched.expected_version == 0 and patched.name is None


@pytest.mark.parametrize(
    "definition",
    [
        {"schema_version": "2.0", "nodes": [], "edges": []},
        {"schema_version": 1, "nodes": [], "edges": []},
        {"schema_version": "1.0", "nodes": []},
        {**DEFINITION, "nodes": {}},
        {**DEFINITION, "nodes": ["node"]},
        {**DEFINITION, "edges": [False]},
        {**DEFINITION, "nodes": [{}] * 501},
        {**DEFINITION, "edges": [{}] * 2001},
        {**DEFINITION, "extra": float("nan")},
        {**DEFINITION, "extra": float("inf")},
        {**DEFINITION, "extra": (1, 2)},
        {**DEFINITION, "extra": {1: "value"}},
        {**DEFINITION, "extra": "界" * 90000},
        {**DEFINITION, "extra": "\ud800"},
        [],
    ],
)
def test_definition_rejects_invalid_envelopes_or_unbounded_json(definition: object) -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate(definition)


def test_definition_byte_and_depth_boundaries() -> None:
    # Definition size is canonical compact UTF-8, including envelope and keys.
    import json

    base = {**DEFINITION, "extra": ""}
    overhead = len(json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode())
    WorkflowDefinition.model_validate({**base, "extra": "a" * (262144 - overhead)})
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({**base, "extra": "a" * (262145 - overhead)})
    value = None
    for _ in range(31):
        value = [value]
    WorkflowDefinition.model_validate({**DEFINITION, "extra": value})
    with pytest.raises(ValidationError):
        WorkflowDefinition.model_validate({**DEFINITION, "extra": [value]})


@pytest.mark.parametrize(
    "payload",
    [
        {"definition": DEFINITION},
        {"expected_version": 0},
        {"name": "Renamed", "expected_version": 1},
        {"definition": None, "expected_version": 0},
        {"definition": DEFINITION, "expected_version": None},
        {"definition": DEFINITION, "expected_version": -1},
        {"definition": DEFINITION, "expected_version": True},
        {"definition": DEFINITION, "expected_version": "1"},
        {"definition": DEFINITION, "expected_version": 1.0},
        {"definition": DEFINITION, "expected_version": 2147483648},
    ],
)
def test_definition_save_requires_strict_expected_version_pair(payload: dict) -> None:
    with pytest.raises(ValidationError):
        WorkflowUpdateRequest.model_validate(payload)


def test_create_definition_cannot_be_explicit_null() -> None:
    with pytest.raises(ValidationError):
        WorkflowCreateRequest.model_validate({"name": "Draft", "definition": None})
