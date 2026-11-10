# Groq provider plan

Current implementation: the bounded HTTPX adapter uses the configured Groq model
and private key, returns explicit provider errors/quota guidance and actual reported
usage, and never falls back to a paid provider. Reviewed generation supports an
authorized selected-connection catalog. Workflow business outputs remain unchanged;
operational metadata is retained in immutable status events. See
[current behavior and verification](../learning-notes/provider-integration-hardening.md).
The Phase 0 research and proposals below are historical.

User preference: use `openai/gpt-oss-120b` as the configurable Groq model with the private `GROQ_API_KEY`. Synthetic live completion, reviewed HTTP generation and the complete API flow have now been verified. Account quota and model availability can still vary.

Phase 0 proposal, verified against public Groq documentation on 30 October 2026. No key was read, requested, installed in application configuration, or used for an inference request. Account availability remains to be tested privately during the provider increment.

## Initial recommendation

Use **Groq Free Plan** with configurable **`openai/gpt-oss-120b`** as the starting planner/agent model. `openai/gpt-oss-20b` is an optional evaluation alternative. Both appear in Groq's current free-plan limits. The initial recommendation is architectural, not a measured AgentFlow quality benchmark; test actual graph-generation accuracy, tool correctness and latency before deciding between them. [Groq rate limits](https://console.groq.com/docs/rate-limits), [supported models](https://console.groq.com/docs/models).

Do not copy older Llama defaults from tutorials: Groq's deprecation notice says `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` were retired for free/developer use on 16 August 2026. Enterprise listings do not establish Free Plan access. [Groq deprecations](https://console.groq.com/docs/deprecations).

The `openai/` prefix is Groq's hosted model identifier; it does not require an OpenAI-paid API account. Only the configured Groq endpoint is contacted. Keep the backend provider generic so a compatible local server can be selected later.

## Planned configuration

Illustrative names/values only; no `.env` file is created in Phase 0:

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=<private server-side Groq key>
LLM_MODEL=openai/gpt-oss-120b
LLM_TIMEOUT_SECONDS=30
LLM_MAX_OUTPUT_TOKENS=2048
```

Groq documents this base URL for use with OpenAI-compatible clients. Use the OpenAI-compatible Python SDK requested by the brief; a separate Groq SDK is unnecessary for the initial adapter. Keys stay on the backend, out of frontend bundles, localStorage, workflow definitions, logs, traces and committed configuration. [Groq OpenAI compatibility](https://console.groq.com/docs/openai).

## Separate planner and agent requests

- **Planner:** pass a compact allowed-node catalog and schema; request schema-constrained JSON; parse/validate with Pydantic, then validate graph semantics, mappings, capabilities and permissions. Return a review proposal only.
- **Edit proposals:** identify the exact owned base version, propose a bounded definition patch, validate its resulting graph, and apply only after user review plus an optimistic concurrency check.
- **LLM node:** use the configured task/prompt/output contract and actual input; persist real result/error and usage metadata when returned.
- **Agent:** use normal model tool calls; validate tool name/arguments, connection ownership, iteration/time/token budgets and tool authorization before execution. No provider-hosted browser, code-execution or remote tools are implicitly enabled.
- **Model capabilities:** check the configured model's structured-output and tool-calling behavior independently. Model discovery alone does not prove either works for this account/client/schema combination.

Groq lists strict structured outputs for both GPT-OSS choices, but currently documents that structured outputs cannot be combined with streaming or tool use. Therefore planner schema calls and agent tool calls use separate request modes; a final structured agent result can be a separate validated step if necessary. Schema conformity does not prove a graph is executable or authorized. [Groq structured outputs](https://console.groq.com/docs/structured-outputs).

## Free-plan limits and failure behavior

The public table currently lists both choices at 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute and 200,000 tokens/day; exact organization limits can differ. Groq returns 429 when a limit is exceeded and provides rate-limit headers. Budget planner catalogs, outputs and agent iterations for this shared quota, rather than assuming a model's context window is the available token budget. [Groq limits and headers](https://console.groq.com/docs/rate-limits).

Proposed policy to verify during Phase 7:

1. Bound request/total-operation deadlines and output tokens; keep the planner catalog limited to implemented nodes.
2. Have one owner for provider retries. Configure SDK automatic retries deliberately so SDK, service and Celery retries do not multiply into a request storm.
3. Honor `Retry-After` for 429s with a cap, bounded jitter/backoff and an overall deadline. Redis can coordinate quota usage across workers once needed.
4. Permit at most one validation-repair attempt for a malformed proposal initially; return readable structured errors after the limit. Repair is still an untrusted model response.
5. Distinguish invalid configuration/key, unavailable/forbidden model, quota exhaustion, transient outage, timeout, context limit, invalid JSON/schema, invalid graph and unauthorized tool requests.
6. Surface failure explicitly; do not substitute fixture output or silently switch to a paid model/provider.
7. Keep automated tests offline with a fake provider/HTTP responses. One opt-in live smoke test proves account/model access; it is not evidence that all prompts or tools work.
8. Capture response model, latency, token usage and actual tool calls when available. Do not expose hidden reasoning or invent missing cost/usage information.

## Suggested capability/evaluation checks

- List configured account models; fail clearly if the configured ID is unavailable.
- Generate a tiny strict JSON object, then a small valid workflow using only implemented nodes.
- Ask for a calculator tool call and verify its arguments without granting network/filesystem/code access.
- Test invoice threshold routing with typed values, unsupported node requests, prompt injection, invalid mappings, and a stale workflow-edit base version.
- Measure valid proposal rate, graph validity, authorized tool correctness, latency and token use on a small saved evaluation set. Compare 120B and 20B only if useful; never infer which is better from parameter count alone.

A free account/API key will be needed only when implementing/testing the real provider phase. The first foundation, database and deterministic execution phases do not depend on Groq being available.
