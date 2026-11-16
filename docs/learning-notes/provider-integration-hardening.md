# Phase 7 — provider hardening and authorized generation

Groq requests now expose explicit provider failures, sanitized quota guidance and
actual reported token usage. Workflow generation can use selected owned HTTP
connections. Proposals remain review-only; generating never contacts those HTTP
endpoints, writes workflows or executes nodes.

Apply additive migration **0010** before restarting the API. It extends the
run/attempt failure-code constraints while preserving old records. It refuses a
downgrade that would discard a provider failure. No new environment setting is
required; the existing configured Groq model/key and optional connection encryption
key remain server-side. This task did not change the private `.env` or development
database.

## Selecting connections

On Create workflow, expand **Allow AI to use HTTP connections** and choose up to ten
active connections. The selection starts empty. The UI explains that selected
names and endpoint URLs go to Groq; credentials and ciphertext never do. The
server selects only ID/name/endpoint columns and verifies ownership/revocation
before the provider call and again before returning the proposal. Missing, unowned
and revoked selections return the same 404 before consuming provider quota.

Both generate and edit requests accept optional `connection_ids` (UUID strings,
unique, maximum ten). Edits also authorize the existing saved HTTP bindings, with
at most twenty unique connections in the combined catalog. The editor discloses
that existing connection metadata is included. A stale save still rejects the
proposal through the normal expected-version check.

The prompt names canonical registry types and supplies a valid HTTP example when
connections are authorized. Returned HTTP configs must reference the exact approved
UUID set. A model cannot invent a URL, credential, method or connection. Revocation
during generation rejects the result; revocation after a proposal is returned still
blocks execution. The review shows the authorized endpoint names, URLs and IDs next
to the proposed graph. Saving does not imply that an endpoint is reachable.

## Provider behavior

The adapter makes one request to the configured Groq completion endpoint, with no
automatic transport retry, redirect, environment proxy or paid provider fallback.
It bounds prompt bytes (64 KiB), upstream response bytes (512 KiB), content size and
the persisted output envelope (256 KiB). The connect timeout is capped at five seconds (or the smaller remaining request budget), while read/write/pool timeouts retain the configured provider budget. This leaves time for normal address fallback when an IPv6 route stalls. Elapsed response-body reading is checked against its deadline. This
does not introduce a hard elapsed deadline for an entire workflow or interrupt an
OS DNS lookup.

Workflow generation and edit proposals have a 4,096-token completion budget because
the provider returns a complete graph. Other JSON requests retain 2,048 tokens and
ordinary text/agent calls retain 1,024. This is a ceiling, not a guarantee: large
graphs or model reasoning can still exhaust the budget or account quota. Truncated
responses are rejected without automatic retry. The planner explains that conditions
output booleans, earlier fields need explicit input mappings, and numeric thresholds
require numeric comparisons; proposals still require human review.

Malformed/duplicate JSON, invalid usage counters, unexpected tool calls, credential
echoes and truncated responses fail explicitly. Provider reasoning, request IDs,
fingerprints and arbitrary upstream error bodies/headers are excluded. Responses
report the actual response model separately from the requested model.

| Outcome                                | Public API status/code           |
| -------------------------------------- | -------------------------------- |
| Missing key                            | 503 `PROVIDER_NOT_CONFIGURED`    |
| Invalid credentials/permissions        | 503 `PROVIDER_AUTH_FAILED`       |
| Missing/decommissioned/forbidden model | 503 `PROVIDER_MODEL_UNAVAILABLE` |
| Quota exhausted                        | 429 `PROVIDER_RATE_LIMITED`      |
| Context/input too large                | 422 `PROVIDER_CONTEXT_LIMIT`     |
| Upstream outage                        | 503 `PROVIDER_UNAVAILABLE`       |
| Malformed response                     | 502 `PROVIDER_INVALID_RESPONSE`  |
| Output budget exhausted                | 502 `PROVIDER_OUTPUT_LIMIT`      |
| Timeout                                | 504 `DEADLINE_EXCEEDED`          |

Provider authentication failures do not become AgentFlow 401s or end a valid user
session. Rate limits propagate only validated `Retry-After` delta seconds, 1–86400;
invalid headers are omitted. The UI shows the wait guidance. Requests are not
automatically resubmitted, and the adapter does not sleep holding a worker or
database transaction. This is fail-fast quota handling, not distributed quota
reservation or a persistent cooldown across API instances.

Generation retains at most one validation repair. A provider failure or 429 never
starts a repair. A repair sends the original request/catalog and static validator
codes, excluding the rejected model response. Up to two per-call timeout budgets
can therefore be used for one generation request.

## Usage and execution history

Completions return `metadata`; generation/edit responses return `provider_calls`
(up to two) and the authorized `connections` metadata. Only token fields actually
reported by Groq are shown. Missing usage remains unknown; costs are not invented.

Workflow node business output stays unchanged (`model`/`content`, or the existing
classify/extract fields). Validated operational metadata is added to the same
immutable `node.status_changed` event transaction as its result/failure. Owned run
details derive the attempt's optional `provider` field from these events. The UI
shows requested/actual model, duration, reported usage and quota/error metadata.

Cancellation wins over a late provider result. Usage from an interrupted or
cancelled call may remain unknown; this is not a billing reconciliation ledger.
Groq and HTTP nodes remain excluded from automatic retries and worker recovery.
Existing idempotent command replay returns stored results without another call.

## Verification

Final verification: **1254 backend tests passed** with isolated PostgreSQL/Redis;
Ruff lint/format checked 200 files and Pyright reported zero errors/warnings.
Frontend: **133 tests passed**, plus lint, TypeScript and production build.
Only the Redis test service started for this task was stopped/removed afterward;
the pre-existing PostgreSQL test/development services were preserved.

Offline tests cover status/error privacy, bounded responses, missing/inconsistent
usage, truncation, timeouts without replay, write-only catalog access, owner denial,
unselected IDs, concurrent revocation, review-only edits, provider event persistence
and migration preservation/downgrade refusal. Frontend tests cover explicit empty
selection, metadata-sharing disclosure, unknown versus reported-zero usage and
quota guidance without session loss or automatic replay.

The live public JSON check and configured Groq completion passed. After correcting
the planner's missing canonical HTTP type, a synthetic HTTP proposal passed without
repair. A separate live API exercise, confined to a guarded disposable PostgreSQL
schema, passed create connection → authorize generation → save → execute → replay
→ revoke. It issued one real HTTP request; replay and revocation caused no second
request. The temporary schema was removed. No private business data was sent.

The initial live generation attempts produced an invalid proposal and an unexpected
result before the prompt/catalog correction. One successful live exercise is an
observation, not a guaranteed model-quality rate. Human review remains required.
Browser access was retried, but its host is unavailable; visual/browser acceptance
is still outstanding.

Optional repeatable synthetic checks (network and free-plan quota are used only
with `--live`; no database writes):

```bash
uv run --directory backend --locked python -m scripts.smoke_integrations
uv run --directory backend --locked python -m scripts.smoke_integrations --live --http
uv run --directory backend --locked python -m scripts.smoke_integrations --live --groq --generate
```

Further expansion includes OAuth/credential rotation, dynamic requests and mutating
methods with side-effect reconciliation. Distributed quota coordination and broader
model-quality evaluations remain separate work; none is represented as implemented.

References: [Groq error codes](https://console.groq.com/docs/errors),
[rate-limit headers](https://console.groq.com/docs/rate-limits),
[completion usage](https://console.groq.com/docs/api-reference),
[HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/).
