# Phase 8B — authorized HTTP agent tools

The **Tool Agent** combines the local calculator with explicitly selected HTTP GET connections. Existing calculator-only saved versions continue to work with no HTTP capabilities. Phase 8C adds [persistent checkpoints and explicit continuation](agent-checkpoints.md).

## Review this flow with sample data

Restart the backend and frontend. Use your existing configured Groq model/key and sign in with one consistent hostname. Do not replace the private `.env`. This flow sends only synthetic messages and public sample JSON to Groq.

1. In **Integrations → HTTP connections**, create a connection named **Sample slideshow**, endpoint **https://httpbin.org/json**, authentication **None**. Creating it makes no HTTP request.
2. Create a workflow named **HTTP Agent Review**. In **Definition JSON**, paste [the sample workflow](../examples/http-agent.workflow.json). It deliberately starts with no selected connection IDs.
3. Switch back to **Visual editor** and select the **Inspect sample slideshow** node on the canvas. Expand **Allow this agent to fetch HTTP connections** and select **Sample slideshow**. The inspector also shows selected IDs so missing/revoked bindings can be removed. Read the data-sharing notice before saving: endpoint metadata and fetched JSON will go to Groq; results are stored in execution history. The endpoint receives no workflow input.
4. **Save**, then **Validate**. Structural validation does not contact the endpoint or check its reachability; execution rechecks authorization.
5. Paste [the sample input](../examples/http-agent.input.json) into **Manual run input** and choose **Run saved version**:

```json
{
  "message": "Fetch the selected sample slideshow using http_get. Count the slides in its returned JSON, then use calculator to multiply the count by 10. Report the slideshow title, count and result."
}
```

Expected route: **manual → agent (http_get → calculator → final answer) → end**. At verification time, [the public sample](https://httpbin.org/json) has title **Sample Slide Show**, two slides and therefore calculated result **20**. Use the actual fetched JSON as the source if the public endpoint changes. The model may choose a different tool sequence or answer without a tool; a text answer alone does not prove the expected flow.

In execution details, inspect:

- **Succeeded**, **Synchronous execution**, the exact saved version, and succeeded `start`/`inspect`/`finish` attempts.
- Run output `tool_calls`: an `http_get` entry containing the selected `connection_id`, HTTP status and actual JSON body; then a calculator entry with operands `[2, 10]` and result `20` (equivalent arithmetic is possible).
- The agent attempt: completed tool count, HTTP tool attempts, per-connection status, and the separate Groq request metadata/usage. The expected path uses one HTTP call, one calculator call and three model requests. Reported token usage remains unknown where absent.

### Check revocation

After recording the successful run, revoke **Sample slideshow** in Integrations. Reopen the editor and issue a **fresh** run of the saved version. Expect `CONNECTION_UNAVAILABLE`, agent stop reason `connection_unavailable`, and no HTTP/provider call. The earlier successful history remains readable. Replaying an already committed command key returns the old stored run; it does not retest revocation. Create a replacement connection to continue and explicitly select/save it in a new version.

### Check calculator compatibility

Create a separate calculator-only agent with empty `connection_ids`, or remove the HTTP binding and change its instruction to **Use the calculator for arithmetic**. Run:

```json
{ "message": "Use the calculator to add 2 and 3." }
```

Expected calculator result: **5**, with zero HTTP attempts. Do not use the slideshow instruction for this compatibility check, because it asks for a capability you removed.

## Authorization and request flow

Agent configuration adds `connection_ids`: a strict list of up to ten unique UUID strings, empty by default. The saved immutable version freezes that allowlist. Owner authentication and exact-version run authorization remain in the execution service.

Before the first model request, the agent resolves only ID/name/endpoint metadata for the selected active owned connections. Missing, unowned and revoked bindings all fail with `CONNECTION_UNAVAILABLE` before consuming model quota. Credentials are neither selected nor decrypted for the catalog. The model sees a code-owned `http_get` schema accepting only one selected `connection_id`; it cannot provide a URL, method, headers, queries, body or credentials.

Immediately before HTTP, the adapter checks the selected identity and owner/revocation again, closes its storage session, decrypts any configured credential, and invokes the existing controlled executor. Network/DNS/TLS and response parsing hold no database transaction. Metadata is reauthorized before each later model turn, so observed revocation after an HTTP result prevents sending that result in another Groq request. Cancellation checks run between model/tool steps and before final persistence; a request already authorized/in progress cannot be retracted.

The HTTP executor retains public-address validation and DNS pinning, HTTPS port 443/certificate checks, fixed GET, no redirects/proxies and rejection of private/mixed DNS answers, duplicate JSON keys, nonfinite values, compressed/invalid responses and usable credential echoes. All DNS answers are validated before selecting an address; IPv4 is preferred, and TCP setup may try another validated address within the shared deadline before any HTTP request is sent. TLS/HTTP requests are never replayed. Authentication remains server-side; the fixed endpoint receives no run input or arbitrary headers.

## Bounds, history and failures

- The existing 1–5 tool-round limit is shared by calculator and HTTP calls; model requests remain bounded by rounds + 1, within the shared 60-second agent budget. HTTP has its existing maximum 20-second operation budget, capped by the agent's remaining time. OS DNS interruption retains the existing limitation.
- An endpoint can be fetched once per agent invocation, including when multiple selected connection IDs point to it. A second request fails `duplicate_http_call`. A different agent node or fresh run is a separate invocation; this is not an exactly-once delivery guarantee.
- Agent HTTP responses are limited to 16 KiB rather than the standalone HTTP node's 64 KiB. A serialized result is checked again before it enters the model conversation; cumulative conversation growth is bounded before the next provider call. Invalid/oversized HTTP responses fail rather than being truncated.
- Successful output preserves existing calculator entries and adds HTTP entries with `id`, `tool: "http_get"`, `connection_id`, `status_code` and `body`, preserving business JSON keys. Model answer content can still be inaccurate; inspect actual tool results.
- The immutable terminal attempt event stores bounded agent metadata: completed `tool_rounds`, `http_tool_attempts`, `http_calls` (selected ID and recorded status/error), provider-call metadata and optional static `failure_reason`. HTTP tool attempts include a selected call refused during reauthorization; they are not a guaranteed count of completed external requests. These summaries remain on a failed attempt even when its output is null.
- Errors retain `CONNECTION_UNAVAILABLE`, `HTTP_TARGET_BLOCKED`, `HTTP_REQUEST_FAILED` or `DEADLINE_EXCEEDED`; the static agent stop reason distinguishes capability denial, HTTP failure, duplicate fetch, oversized result and normal existing agent failures. Endpoint response bodies and credentials never enter operational error messages.
- HTTP/agent graphs stay synchronous with no automatic node/provider/full-workflow retry or worker recovery. Command replay returns committed history. Crashes/cancellation can leave an issued request or its usage unknown; only explicit post-tool pauses are eligible for checkpoint continuation.

## Reviewed generation and editing

The existing explicit proposal connection selection now authorizes both standalone HTTP nodes and agent `connection_ids`. A model cannot introduce another owned-but-unselected ID. Edits authorize saved agent bindings as well as newly selected connections, and recheck them after generation. Generation never decrypts credentials, fetches endpoints, saves a workflow or runs an agent. Proposal review displays authorized endpoints and explains that agent HTTP results go to Groq when run.

## Implementation and verification

`modules/agents/http_tools.py` owns owner-bound catalog/access; `agents/runner.py` routes code-owned tools inside the bounded LangGraph loop. The existing connection executor supplies network policy, and the execution repository persists validated metadata atomically with the attempt result. `workflows/connection_bindings.py` centralizes extraction for proposal authorization. The active frontend supplies explicit selection/disclosure and actual execution details. No migration, new provider, paid fallback, OAuth flow or mutating HTTP capability is added.

See [verification](../verification.md) for current results and browser limits. Fixtures exercise actual graph/tool conversations and isolated API/history behavior; they do not claim model reliability. See the [checkpoint guide](agent-checkpoints.md) for the continuation boundary.

Exercise: after a successful sample, revoke the connection and predict the difference between replaying the original command and creating a fresh run. Compare the retained old output with the new attempt's static failure metadata.
