"""Strict configuration contracts only; no evaluation, reference resolution or execution."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

NODE_ID_PATTERN = r"[A-Za-z_][A-Za-z0-9_-]{0,63}"
OUTPUT_REFERENCE_PATTERN = rf"^\$\.{NODE_ID_PATTERN}\.output(?:\.{NODE_ID_PATTERN}){{0,16}}$"
OutputReference = Annotated[
    str,
    Field(
        min_length=1,
        max_length=512,
        pattern=OUTPUT_REFERENCE_PATTERN,
        description="Exact node output/dictionary path; no arrays, wildcards or expressions.",
    ),
]
MAX_ABS_NUMBER = 1_000_000_000_000
MAX_TEXT_LENGTH = 4096
Number = Annotated[int | float, Field(ge=-MAX_ABS_NUMBER, le=MAX_ABS_NUMBER)]
Text = Annotated[str, Field(max_length=MAX_TEXT_LENGTH)]
FieldName = Annotated[str, Field(min_length=1, max_length=200)]


class NodeConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ManualConfig(NodeConfig):
    """Manual input belongs to the run request, not trigger configuration."""


class EndConfig(NodeConfig):
    """An end copies its resolved input to the final run output."""


class MergeConfig(NodeConfig):
    """Exclusive-branch reconvergence copies only the chosen incoming output."""


class ApprovalConfig(NodeConfig):
    """The workflow owner reviews the resolved input before a selected branch continues."""

    title: str = Field(min_length=1, max_length=200)
    expires_in_seconds: int = Field(default=86400, ge=60, le=604800)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Provide an approval title")
        return value


class GroqConfig(NodeConfig):
    """Send a string field from the node's resolved input to the configured model."""

    instruction: str = Field(min_length=1, max_length=2000)
    input_field: str = Field(min_length=1, max_length=200)

    @field_validator("instruction", "input_field")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value


class HttpConfig(NodeConfig):
    """A fixed, owner-authorized GET endpoint; credentials belong to the connection."""

    connection_id: str = Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


class GmailReadConfig(NodeConfig):
    """Read one selected message from an owned Gmail connection."""

    connection_id: str = Field(pattern=r"^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
    message_id_field: str = Field(min_length=1, max_length=200)

    @field_validator("message_id_field")
    @classmethod
    def field_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value


class AgentConfig(GroqConfig):
    """Synchronous bounded tools; HTTP capabilities require explicit saved bindings."""

    max_tool_rounds: int = Field(default=3, ge=1, le=5)
    connection_ids: list[str] = Field(default_factory=list, max_length=10)
    pause_after_tools: bool = False

    @field_validator("connection_ids")
    @classmethod
    def valid_connections(cls, value: list[str]) -> list[str]:
        try:
            normalized = [str(UUID(identity)) for identity in value]
        except ValueError:
            raise ValueError("Select valid connection identities") from None
        if len(set(normalized)) != len(normalized):
            raise ValueError("Select each connection once")
        return normalized


class IdentityTransformConfig(NodeConfig):
    operation: Literal["identity"]


class JsonParserConfig(NodeConfig):
    """Parse a selected text field into a JSON object."""

    input_field: str = Field(min_length=1, max_length=200)

    @field_validator("input_field")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value


class ClassifyConfig(NodeConfig):
    input_field: str = Field(min_length=1, max_length=200)
    labels: list[FieldName] = Field(min_length=2, max_length=20)

    @field_validator("input_field")
    @classmethod
    def input_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value

    @field_validator("labels")
    @classmethod
    def labels_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not label.strip() for label in value):
            raise ValueError("Labels must be unique and nonblank")
        return value


class ExtractConfig(NodeConfig):
    input_field: str = Field(min_length=1, max_length=200)
    fields: list[FieldName] = Field(min_length=1, max_length=20)

    @field_validator("input_field")
    @classmethod
    def input_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value

    @field_validator("fields")
    @classmethod
    def fields_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not field.strip() for field in value):
            raise ValueError("Fields must be unique and nonblank")
        return value


class PickFieldsTransformConfig(NodeConfig):
    operation: Literal["pick_fields"]
    fields: list[FieldName] = Field(
        min_length=1, max_length=100, json_schema_extra={"uniqueItems": True}
    )

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Selected fields must be unique")
        return value


TransformConfig = Annotated[
    IdentityTransformConfig | PickFieldsTransformConfig, Field(discriminator="operation")
]


class EqualityConditionConfig(NodeConfig):
    field: OutputReference
    operator: Literal["equals", "not_equals"]
    value: Text | bool | Number | None


class OrderedConditionConfig(NodeConfig):
    field: OutputReference
    operator: Literal["greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"]
    value: Number


class ContainsConditionConfig(NodeConfig):
    field: OutputReference
    operator: Literal["contains"]
    value: Text


ConditionConfig = Annotated[
    EqualityConditionConfig | OrderedConditionConfig | ContainsConditionConfig,
    Field(discriminator="operator"),
]


class LiteralNumberOperand(NodeConfig):
    kind: Literal["literal"]
    value: Number


class OutputNumberOperand(NodeConfig):
    kind: Literal["output"]
    path: OutputReference


NumericOperand = Annotated[LiteralNumberOperand | OutputNumberOperand, Field(discriminator="kind")]


class FoldCalculatorConfig(NodeConfig):
    operation: Literal["add", "multiply"]
    operands: list[NumericOperand] = Field(min_length=2, max_length=20)


class BinaryCalculatorConfig(NodeConfig):
    operation: Literal["subtract", "divide"]
    operands: list[NumericOperand] = Field(min_length=2, max_length=2)


CalculatorConfig = Annotated[
    FoldCalculatorConfig | BinaryCalculatorConfig, Field(discriminator="operation")
]
