"""Code-owned node/configuration catalog; no dynamic plugins or executor claims."""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter, ValidationError

from app.modules.workflows.node_configs import (
    CalculatorConfig,
    ConditionConfig,
    EndConfig,
    GroqConfig,
    ManualConfig,
    MergeConfig,
    TransformConfig,
)

NodeTypeId = Literal["manual", "transform", "condition", "calculator", "merge", "end", "groq"]
NodeCategory = Literal["trigger", "logic", "tool"]
EXECUTION_READY_TYPES: frozenset[NodeTypeId] = frozenset(
    {"manual", "transform", "condition", "calculator", "merge", "end", "groq"}
)


class UnsupportedNodeTypeError(Exception):
    def __init__(self) -> None:
        super().__init__("The node type has no registered configuration contract.")


class InvalidNodeConfigError(Exception):
    def __init__(self) -> None:
        super().__init__("The node configuration does not match its registered contract.")


class NodeTypeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: NodeTypeId
    name: str
    category: NodeCategory
    description: str
    output_handles: list[str]
    config_schema: dict[str, JsonValue]
    capabilities: list[Literal["validate_config", "execute"]]
    execution_ready: bool


class NodeTypeCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    items: list[NodeTypeResponse]


@dataclass(frozen=True)
class _Registration:
    type: NodeTypeId
    name: str
    category: NodeCategory
    description: str
    output_handles: tuple[str, ...]
    adapter: TypeAdapter[Any]


_REGISTRATIONS = (
    _Registration(
        "manual",
        "Manual Trigger",
        "trigger",
        "Configuration for an on-demand start.",
        ("default",),
        TypeAdapter(ManualConfig),
    ),
    _Registration(
        "transform",
        "Transform Data",
        "logic",
        "Identity or top-level field selection.",
        ("default",),
        TypeAdapter(TransformConfig),
    ),
    _Registration(
        "condition",
        "Condition",
        "logic",
        "Typed comparison against a node output reference.",
        ("true", "false"),
        TypeAdapter(ConditionConfig),
    ),
    _Registration(
        "calculator",
        "Calculator",
        "tool",
        "Predefined bounded arithmetic operands.",
        ("default",),
        TypeAdapter(CalculatorConfig),
    ),
    _Registration(
        "groq",
        "Groq LLM",
        "tool",
        "Send a selected input field and instruction to the configured Groq model.",
        ("default",),
        TypeAdapter(GroqConfig),
    ),
    _Registration(
        "merge",
        "Merge",
        "logic",
        "Configuration for exclusive-branch reconvergence.",
        ("default",),
        TypeAdapter(MergeConfig),
    ),
    _Registration(
        "end",
        "End",
        "logic",
        "Configuration for workflow completion.",
        (),
        TypeAdapter(EndConfig),
    ),
)
_BY_TYPE = MappingProxyType({registration.type: registration for registration in _REGISTRATIONS})


def node_type_catalog() -> NodeTypeCatalog:
    """Fresh DTOs/schemas isolate caller mutations from the code-owned registry."""
    return NodeTypeCatalog(
        items=[
            NodeTypeResponse(
                type=registration.type,
                name=registration.name,
                category=registration.category,
                description=registration.description,
                output_handles=list(registration.output_handles),
                config_schema=registration.adapter.json_schema(),
                capabilities=["validate_config", "execute"]
                if registration.type in EXECUTION_READY_TYPES
                else ["validate_config"],
                execution_ready=registration.type in EXECUTION_READY_TYPES,
            )
            for registration in _REGISTRATIONS
        ]
    )


def validate_node_config(node_type: str, config: object) -> BaseModel:
    """Internal boundary for the later compiler; never include raw inputs in errors."""
    registration = _BY_TYPE.get(node_type)
    if registration is None:
        raise UnsupportedNodeTypeError()
    try:
        return registration.adapter.validate_python(config, strict=True)
    except ValidationError:
        raise InvalidNodeConfigError() from None


def node_output_handles(node_type: str) -> tuple[str, ...]:
    """Immutable declared routes without building JSON schemas or exposing adapters."""
    registration = _BY_TYPE.get(node_type)
    if registration is None:
        raise UnsupportedNodeTypeError()
    return registration.output_handles
