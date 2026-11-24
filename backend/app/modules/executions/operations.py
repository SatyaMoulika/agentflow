"""Pure registered operations and compiled dictionary bindings; no storage or effects."""

import json
import math
from typing import Any

from app.core.tracing import traced
from app.modules.executions.payloads import InvalidExecutionPayloadError, copy_payload
from app.modules.executions.state import FailureCode
from app.modules.workflows.compiler import CompiledBinding, CompiledNode
from app.modules.workflows.node_configs import MAX_ABS_NUMBER, MAX_TEXT_LENGTH


class NodeExecutionError(Exception):
    def __init__(self, code: FailureCode = FailureCode.EXECUTION_FAILED) -> None:
        self.code = code
        super().__init__("The node could not produce a valid result.")


def resolve_reference(binding: CompiledBinding, outputs: dict[str, dict[str, Any]]) -> Any:
    value: Any = outputs.get(binding.source_node_id)
    if value is None:
        raise NodeExecutionError(FailureCode.INPUT_MAPPING_FAILED)
    for field in binding.field_path:
        if not isinstance(value, dict) or field not in value:
            raise NodeExecutionError(FailureCode.INPUT_MAPPING_FAILED)
        value = value[field]
    return value


def _bounded(value: dict[str, Any]) -> dict[str, Any]:
    try:
        return copy_payload(value)
    except InvalidExecutionPayloadError:
        raise NodeExecutionError(FailureCode.INPUT_MAPPING_FAILED) from None


def resolve_input(
    node: CompiledNode, incoming: dict[str, Any], outputs: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Explicit data mappings replace incoming input; config bindings are separate."""
    bindings = [binding for binding in node.bindings if binding.target_path[0] == "input_mapping"]
    if not bindings:
        return copy_payload(incoming)
    return _bounded(
        {str(binding.target_path[1]): resolve_reference(binding, outputs) for binding in bindings}
    )


def resolve_config(node: CompiledNode, outputs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Replace only compiler-declared config references in a fresh config object."""
    config = json.loads(node.config_json)
    for binding in node.bindings:
        if binding.target_path[0] != "config":
            continue
        container = config
        for key in binding.target_path[1:-1]:
            container = container[key]
        container[binding.target_path[-1]] = resolve_reference(binding, outputs)
    return _bounded(config)


def _number(value: Any) -> int | float:
    if type(value) not in (int, float) or not -MAX_ABS_NUMBER <= value <= MAX_ABS_NUMBER:
        raise NodeExecutionError()
    if isinstance(value, float) and not math.isfinite(value):
        raise NodeExecutionError()
    return value


def _scalar_kind(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) in (int, float):
        _number(value)
        return "number"
    if type(value) is str and len(value) <= MAX_TEXT_LENGTH:
        return "string"
    raise NodeExecutionError()


def _condition(config: dict[str, Any]) -> dict[str, bool]:
    left, right, operation = config["field"], config["value"], config["operator"]
    if operation in {"equals", "not_equals"}:
        equal = _scalar_kind(left) == _scalar_kind(right) and left == right
        return {"result": equal if operation == "equals" else not equal}
    if operation == "contains":
        if _scalar_kind(left) != "string" or _scalar_kind(right) != "string":
            raise NodeExecutionError()
        return {"result": right in left}
    left, right = _number(left), _number(right)
    comparisons = {
        "greater_than": left > right,
        "greater_than_or_equal": left >= right,
        "less_than": left < right,
        "less_than_or_equal": left <= right,
    }
    if operation not in comparisons:
        raise NodeExecutionError()
    return {"result": comparisons[operation]}


def _calculator(config: dict[str, Any]) -> dict[str, int | float]:
    values = [
        _number(operand["value"] if operand["kind"] == "literal" else operand["path"])
        for operand in config["operands"]
    ]
    return calculate(config["operation"], values)


@traced("agentflow.calculator")
def calculate(operation: str, values: list[int | float]) -> dict[str, int | float]:
    """Shared bounded arithmetic for deterministic nodes and the agent's only tool."""
    if operation not in {"add", "subtract", "multiply", "divide"} or not 2 <= len(values) <= 20:
        raise NodeExecutionError()
    if operation in {"subtract", "divide"} and len(values) != 2:
        raise NodeExecutionError()
    values = [_number(value) for value in values]
    result = values[0]
    for value in values[1:]:
        if operation == "add":
            result += value
        elif operation == "multiply":
            result *= value
        elif operation == "subtract":
            result -= value
        elif operation == "divide":
            if value == 0:
                raise NodeExecutionError()
            result /= value
        else:
            raise NodeExecutionError()
        result = _number(result)
    return {"result": result}


@traced("agentflow.pure_node")
def execute_node(
    node: CompiledNode, input_data: dict[str, Any], *, resolved_config: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Compute bounded pure output; config references must already be resolved."""
    if node.type in {"manual", "merge", "end"}:
        return copy_payload(input_data)
    config = resolved_config if resolved_config is not None else json.loads(node.config_json)
    if node.type in {"condition", "calculator"} and resolved_config is None:
        raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
    if node.type == "condition":
        return _condition(config)
    if node.type == "calculator":
        return _calculator(config)
    if node.type == "json_parser":
        value = input_data.get(config["input_field"])
        if not isinstance(value, str):
            raise NodeExecutionError()
        try:
            if len(value.encode("utf-8")) > 65536:
                raise ValueError()

            def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, item in pairs:
                    if key in result:
                        raise ValueError()
                    result[key] = item
                return result

            return copy_payload(json.loads(value, object_pairs_hook=unique_pairs))
        except (ValueError, UnicodeError, RecursionError, InvalidExecutionPayloadError):
            raise NodeExecutionError() from None
    if node.type == "transform":
        if config["operation"] == "identity":
            return copy_payload(input_data)
        if config["operation"] == "pick_fields":
            if any(field not in input_data for field in config["fields"]):
                raise NodeExecutionError()
            return copy_payload({field: input_data[field] for field in config["fields"]})
    raise NodeExecutionError()


def next_node_id(node: CompiledNode, output: dict[str, Any]) -> str | None:
    if node.type == "end":
        return None
    handle = "default"
    if node.type == "approval":
        decision = output.get("decision")
        if decision not in {"approved", "rejected"}:
            raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
        handle = decision
    if node.type == "condition":
        decision = output.get("result")
        if type(decision) is not bool:
            raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
        handle = "true" if decision else "false"
    targets = [route.target_node_id for route in node.routes if route.handle == handle]
    if len(targets) != 1:
        raise NodeExecutionError(FailureCode.INTERNAL_FAILURE)
    return targets[0]
