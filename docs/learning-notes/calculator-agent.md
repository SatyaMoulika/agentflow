# Phase 8A — bounded calculator agent

## Scope and request flow

The registered `agent` node uses LangGraph only inside one deterministic workflow step. Groq can request the code-owned `calculator` function, consume its actual result and return a final text answer. Only the selected input field and configured instruction are sent; unrelated business input fields are excluded. Agent runs are explicit and synchronous even when background execution is enabled.

The outer execution service authorizes the owner and immutable saved workflow version, creates the run/attempt and closes its transaction. Each agent model/tool boundary checks current cancellation in a short, separately closed transaction. The LangGraph model/tool loop does no storage work; its final output and validated operational metadata commit with the terminal node-status event. Cancellation prevents a late result from overwriting committed cancellation and stops subsequent turns once observed. A request already sent cannot be undone.

Files are owned by `app/modules/agents/` (`runner.py`, typed state, strict calculator arguments and metadata). The existing provider adapter supplies bounded, single-attempt Groq transport; deterministic nodes and the agent share bounded arithmetic in `executions/operations.py`. Registry/configuration lives in `workflows/`; execution persistence and API responses remain owned by `executions/`. The active editor and run details expose the new capability.

LangGraph is a locked dependency (1.2.20 at this increment); LangSmith is also declared directly for the explicit tracing-disable context. Its transitive LangChain/LangSmith packages do not select a second model provider. Invocation explicitly disables implicit LangSmith tracing/export, including when host tracing environment variables are set. No checkpoint saver is configured. This increment adds no table or migration; head remains **0010**.

## Bounds and failures

- Config: nonblank `instruction` (up to 2,000 characters), nonblank `input_field`, and strict integer `max_tool_rounds` from 1–5, default 3.
- Selected text: nonblank, at most 4,000 characters/16 KiB. Conversation bytes are bounded by the existing provider adapter.
- Each model turn may request at most one function call. At most the configured number of calculator calls and one additional final-answer model turn are allowed. LangGraph also receives a finite recursion limit.
- Calculator arguments are strict JSON with only `operation` and numeric `operands`; no expressions, code, boolean coercion, duplicate keys or extra fields. Add/multiply accept 2–20 operands; subtract/divide require exactly two. All inputs and intermediate results must remain finite and within ±10^12. Division by zero fails.
- A shared 60-second budget is checked between steps and caps each provider I/O timeout by the remaining budget. OS DNS resolution retains the provider adapter's documented interruption limitation.
- Unknown tools, malformed arguments, arithmetic errors and iteration exhaustion fail with `EXECUTION_FAILED` and a static `agent.failure_reason`. Provider failures retain specific existing provider codes and validated wait guidance. No automatic provider/node retry or full-workflow retry is enabled for agent graphs.

The model may answer without calling a tool and can misstate an answer even after receiving a correct result. Inspect the returned tool results; no semantic model-quality guarantee is claimed. An agent cannot select an HTTP connection, use server secrets, run arbitrary code, access another account or change the outer graph.

## Try it

Restart the updated API and frontend after locked dependency synchronization. In the editor add **Calculator Agent**, connect manual → agent → end, save and validate. The starter config selects `message` and allows three tool rounds. Equivalent definition:

```json
{
  "schema_version": "1.0",
  "nodes": [
    { "id": "start", "type": "manual", "config": {} },
    {
      "id": "calculate",
      "type": "agent",
      "config": {
        "instruction": "Use the calculator for arithmetic and explain its result.",
        "input_field": "message",
        "max_tool_rounds": 3
      }
    },
    { "id": "finish", "type": "end", "config": {} }
  ],
  "edges": [
    { "id": "a", "source": "start", "target": "calculate", "source_handle": "default" },
    { "id": "b", "source": "calculate", "target": "finish", "source_handle": "default" }
  ]
}
```

Run explicitly with synthetic input:

```json
{ "message": "Add 12 and 8, then multiply the result by 3." }
```

The existing configured Groq model/key must support local function calling and your account's limits. No new key or paid fallback is introduced. A successful business output contains `model`, `content` and `tool_calls`; each actual calculation records its call ID, operation, operands and numeric result. The run attempt's separate `agent` details show completed tool rounds and every validated provider call's reported usage/duration. Usage remains unknown where the provider did not report it.

Failed attempts retain the stop reason, completed tool count and provider-call metadata in their immutable status event; failed attempt output remains null. Intermediate tool arguments/results are not durable checkpoints. Interrupted/cancelled calls may have unknown usage; crashes do not automatically resume or replay an agent. Retrying the same committed command key returns existing history without another model call. A fresh command can consume quota again.

## Verification and remaining work

Deterministic HTTP fixtures exercise the actual LangGraph loop: a consumed arithmetic result, chained calls, a zero-tool answer, exact bounds, malformed/unknown/parallel/repeated calls, key-echo rejection, 429/missing configuration, cancellation, deadline and host tracing disablement. Isolated PostgreSQL/API checks cover owner denial, synchronous mode despite background configuration, idempotent replay, per-call usage/history, failed-run retry refusal and output/event rollback together. Frontend checks cover agent defaults, stop details, actual usage and unavailable full-workflow retry.

See [current verification results](../verification.md). No live model call was made for this increment. Browser discovery was retried and remains unavailable, so browser/visual acceptance is pending.

Next: **8B**, an explicitly authorized HTTP agent tool, then **8C**, persistent checkpoint correlation/recovery. Approvals and external-effect reconciliation remain separate phases.

References: [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Groq local function calling](https://console.groq.com/docs/tool-use/local-tool-calling).

Exercise: set a one-round tool budget and ask for a calculation requiring two dependent calls. Predict the difference between a final answer after the first tool result and a second tool request, then inspect the persisted stop reason and request count.
