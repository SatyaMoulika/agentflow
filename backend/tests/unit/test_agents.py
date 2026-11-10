"""Actual LangGraph loop and bounded Groq transport using deterministic HTTP fixtures."""

import json
from copy import deepcopy

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.modules.agents.runner import AgentExecutionError, execute_agent
from app.modules.executions import groq_provider
from app.modules.workflows.node_configs import AgentConfig
from app.modules.workflows.node_registry import InvalidNodeConfigError, validate_node_config

KEY = "synthetic-agent-provider-key"


def response(*, arguments=None, name="calculator", call_id="call_1", content="The result is 5."):
    message = {"content": content}
    if arguments is not None:
        message = {
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        }
    return {
        "model": "synthetic-model",
        "choices": [
            {"message": message, "finish_reason": "tool_calls" if arguments is not None else "stop"}
        ],
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
    }


def install(monkeypatch, responses):
    calls = []
    original = httpx.Client

    def handle(request):
        calls.append(json.loads(request.content))
        item = responses[len(calls) - 1]
        return item if isinstance(item, httpx.Response) else httpx.Response(200, json=item)

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(groq_provider.httpx, "Client", client)
    return calls


def execute(*, rounds=3, value="What is 2 plus 3?", active=lambda: None, settings=None):
    return execute_agent(
        settings or Settings(groq_api_key=SecretStr(KEY)),
        AgentConfig(
            instruction="Calculate carefully.", input_field="message", max_tool_rounds=rounds
        ),
        value,
        check_active=active,
    )


def test_actual_tool_result_is_consumed_and_all_usage_is_returned(monkeypatch):
    calls = install(
        monkeypatch, [response(arguments='{"operation":"add","operands":[2,3]}'), response()]
    )
    output, detail = execute()
    assert output == {
        "model": "synthetic-model",
        "content": "The result is 5.",
        "tool_calls": [{"id": "call_1", "operation": "add", "operands": [2, 3], "result": 5}],
    }
    assert detail["tool_rounds"] == 1 and len(detail["provider_calls"]) == 2
    assert [call["usage"]["total_tokens"] for call in detail["provider_calls"]] == [6, 6]
    assert len(calls) == 2
    assert calls[1]["messages"][-1] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"result": 5}',
    }
    assert calls[0]["tools"][0]["function"]["name"] == "calculator"
    assert calls[0]["parallel_tool_calls"] is False
    assert "response_format" not in calls[0] and "service_tier" not in calls[0]
    assert "failure_reason" not in detail and KEY not in json.dumps((output, detail))


def test_zero_tool_answer_and_independent_invocations(monkeypatch):
    calls = install(monkeypatch, [response(), response()])
    first, detail = execute()
    first["tool_calls"].append({"private": "local mutation"})
    second, _ = execute()
    assert second["tool_calls"] == [] and detail["tool_rounds"] == 0
    assert len(calls[1]["messages"]) == 2


def test_chained_calculations_allow_final_answer_at_exact_round_limit(monkeypatch):
    calls = install(
        monkeypatch,
        [
            response(arguments='{"operation":"add","operands":[2,3]}'),
            response(arguments='{"operation":"multiply","operands":[5,4]}', call_id="call_2"),
            response(content="20"),
        ],
    )
    output, detail = execute(rounds=2)
    assert [tool["result"] for tool in output["tool_calls"]] == [5, 20]
    assert len(calls) == 3 and detail["tool_rounds"] == 2


@pytest.mark.parametrize(
    "arguments",
    [
        '{"operation":"eval","operands":[2,3]}',
        '{"operation":"add","operands":[true,3]}',
        '{"operation":"add","operands":["2",3]}',
        '{"operation":"add","operands":[NaN,3]}',
        '{"operation":"add","operands":[1e13,3]}',
        '{"operation":"subtract","operands":[2,3,4]}',
        '{"operation":"add","operands":[2]}',
        '{"operation":"add","operands":[2,3],"expression":"private-expression"}',
        '{"operation":"add","operation":"multiply","operands":[2,3]}',
        "[]",
        "{}",
        "invalid private JSON",
    ],
)
def test_invalid_arguments_fail_without_more_provider_calls(monkeypatch, arguments):
    calls = install(monkeypatch, [response(arguments=arguments)])
    with pytest.raises(AgentExecutionError) as failure:
        execute()
    assert failure.value.metadata["failure_reason"] == "invalid_arguments"
    assert failure.value.metadata["tool_rounds"] == 0 and len(calls) == 1
    assert "private" not in str(failure.value) + json.dumps(failure.value.metadata)


@pytest.mark.parametrize(
    "arguments",
    [
        '{"operation":"divide","operands":[2,0]}',
        '{"operation":"multiply","operands":[1e12,1e12]}',
    ],
)
def test_failed_arithmetic_is_visible_and_never_retried(monkeypatch, arguments):
    calls = install(monkeypatch, [response(arguments=arguments)])
    with pytest.raises(AgentExecutionError) as failure:
        execute()
    assert failure.value.metadata["failure_reason"] == "tool_failed" and len(calls) == 1


def test_unknown_tool_is_rejected_without_execution(monkeypatch):
    calls = install(monkeypatch, [response(arguments="{}", name="http")])
    with pytest.raises(AgentExecutionError) as failure:
        execute()
    assert failure.value.metadata["failure_reason"] == "unknown_tool" and len(calls) == 1


def test_iteration_exhaustion_never_runs_extra_tool_or_provider_call(monkeypatch):
    calls = install(
        monkeypatch,
        [
            response(arguments='{"operation":"add","operands":[2,3]}'),
            response(arguments='{"operation":"add","operands":[5,1]}', call_id="call_2"),
        ],
    )
    with pytest.raises(AgentExecutionError) as failure:
        execute(rounds=1)
    assert failure.value.metadata["failure_reason"] == "iteration_limit"
    assert failure.value.metadata["tool_rounds"] == 1 and len(calls) == 2


def test_duplicate_call_id_is_rejected(monkeypatch):
    call = response(arguments='{"operation":"add","operands":[2,3]}')
    calls = install(monkeypatch, [call, deepcopy(call)])
    with pytest.raises(AgentExecutionError) as failure:
        execute()
    assert failure.value.metadata["failure_reason"] == "invalid_arguments" and len(calls) == 2


@pytest.mark.parametrize("value", [None, 2, [], {}, "", "  ", "x" * 4001])
def test_invalid_input_never_calls_provider(monkeypatch, value):
    calls = install(monkeypatch, [])
    with pytest.raises(AgentExecutionError) as failure:
        execute(value=value)
    assert failure.value.metadata["failure_reason"] == "invalid_input" and calls == []


def test_missing_key_and_rate_limit_keep_specific_provider_history(monkeypatch):
    calls = install(monkeypatch, [httpx.Response(429, headers={"Retry-After": "3"})])
    with pytest.raises(AgentExecutionError) as missing:
        execute(settings=Settings())
    assert missing.value.code == "PROVIDER_NOT_CONFIGURED" and calls == []
    with pytest.raises(AgentExecutionError) as limited:
        execute()
    assert limited.value.code == "PROVIDER_RATE_LIMITED" and len(calls) == 1
    assert limited.value.metadata["provider_calls"][0]["retry_after_seconds"] == 3


def test_cancellation_check_stops_before_consuming_tool_or_calling_model_again(monkeypatch):
    calls = install(monkeypatch, [response(arguments='{"operation":"add","operands":[2,3]}')])

    class Cancelled(Exception):
        pass

    def active():
        if calls:
            raise Cancelled()

    with pytest.raises(Cancelled):
        execute(active=active)
    assert len(calls) == 1


def test_shared_deadline_stops_between_turns(monkeypatch):
    from app.modules.agents import runner

    ticks = iter([0.0, 0.0, 1.0, 61.0])
    monkeypatch.setattr(runner, "monotonic", lambda: next(ticks))
    calls = install(monkeypatch, [response()])
    with pytest.raises(AgentExecutionError) as failure:
        execute()
    assert failure.value.code == "DEADLINE_EXCEEDED" and len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_tool_rounds", 0),
        ("max_tool_rounds", 6),
        ("max_tool_rounds", True),
        ("max_tool_rounds", "3"),
        ("instruction", " "),
        ("input_field", ""),
    ],
)
def test_registry_rejects_unbounded_or_invalid_agent_configuration(field, value):
    config = {"instruction": "Calculate.", "input_field": "message", field: value}
    with pytest.raises(InvalidNodeConfigError):
        validate_node_config("agent", config)


def test_agent_config_excludes_user_tool_definitions():
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {"instruction": "Calculate", "input_field": "message", "tools": ["http"]}
        )


def test_host_tracing_is_disabled_inside_graph(monkeypatch):
    from langsmith import get_tracing_context

    checks = []
    calls = install(monkeypatch, [response()])

    def active():
        if not calls:
            checks.append(get_tracing_context()["enabled"])

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    execute(active=active)
    assert checks == [False]


def test_parallel_and_key_echo_tool_results_are_rejected_at_transport_boundary(monkeypatch):
    parallel = response(arguments="{}")
    parallel["choices"][0]["message"]["tool_calls"] *= 2
    calls = install(monkeypatch, [parallel, response(arguments=json.dumps({"secret": KEY}))])
    for _ in range(2):
        with pytest.raises(AgentExecutionError) as failure:
            execute()
        assert failure.value.code == "PROVIDER_INVALID_RESPONSE"
        assert KEY not in json.dumps(failure.value.metadata)
    assert len(calls) == 2
