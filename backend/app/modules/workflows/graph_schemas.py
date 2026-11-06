"""Executable DSL envelope within a permissive saved draft; no aliases or expressions."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.modules.workflows.node_configs import NODE_ID_PATTERN, FieldName, OutputReference

GraphId = Annotated[str, Field(min_length=1, max_length=64, pattern=rf"^{NODE_ID_PATTERN}$")]


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    x: int | float = Field(ge=-10000000, le=10000000)
    y: int | float = Field(ge=-10000000, le=10000000)


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: GraphId
    type: str = Field(min_length=1, max_length=64)
    config: dict[str, JsonValue]
    input_mapping: dict[FieldName, OutputReference] = Field(default_factory=dict, max_length=100)
    label: str = Field(default="", max_length=200)
    position: Position | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    id: GraphId
    source: GraphId
    target: GraphId
    source_handle: str = Field(default="default", min_length=1, max_length=64)
    label: str = Field(default="", max_length=200)
