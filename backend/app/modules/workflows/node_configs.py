"""Strict configuration contracts only; no evaluation, reference resolution or execution."""

from typing import Annotated, Literal

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


class IdentityTransformConfig(NodeConfig):
    operation: Literal["identity"]


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
