# Phase 5C — conditions, calculators and exclusive routing

Implemented 3 November 2026. Saved workflows now execute all six registered pure node types: manual, transform, condition, calculator, merge and end. A condition selects one route; the runner never executes both arms. Actual results, chosen-route history and skipped attempts are persisted in PostgreSQL. The existing synchronous run POST/item GET remain the only run endpoints: **15 operations across 12 paths**, migration **0003** unchanged.

Historical Phase 5C scope excluded frontend integration. The subsequent [frontend integration](frontend-api.md) now connects the real UI and adds run listing (16 operations/13 paths); the earlier phase-specific counts below remain historical. Worker, retry/idempotency/cancellation, provider, approval and SSE remain pending. Use [the real-data walkthrough](../real-backend-walkthrough.md) to inspect actual results.

## A runnable graph

Authenticate in Swagger and create a workflow with POST /api/v1/workflows. Use the following definition as its definition field, alongside your own name:

```json
{
  "schema_version": "1.0",
  "nodes": [
    { "id": "start", "type": "manual", "config": {} },
    {
      "id": "choose",
      "type": "condition",
      "config": { "field": "$.start.output.amount", "operator": "greater_than", "value": 10 }
    },
    {
      "id": "double",
      "type": "calculator",
      "config": {
        "operation": "multiply",
        "operands": [
          { "kind": "output", "path": "$.start.output.amount" },
          { "kind": "literal", "value": 2 }
        ]
      }
    },
    {
      "id": "plus",
      "type": "calculator",
      "config": {
        "operation": "add",
        "operands": [
          { "kind": "output", "path": "$.start.output.amount" },
          { "kind": "literal", "value": 1 }
        ]
      }
    },
    { "id": "join", "type": "merge", "config": {} },
    { "id": "finish", "type": "end", "config": {} }
  ],
  "edges": [
    { "id": "e1", "source": "start", "target": "choose" },
    { "id": "e2", "source": "choose", "source_handle": "true", "target": "double" },
    { "id": "e3", "source": "choose", "source_handle": "false", "target": "plus" },
    { "id": "e4", "source": "double", "target": "join" },
    { "id": "e5", "source": "plus", "target": "join" },
    { "id": "e6", "source": "join", "target": "finish" }
  ]
}
```

Validation with {} returns valid true/execution_ready true. Then POST /api/v1/workflows/{workflow_id}/runs with the saved version UUID and input object. These are editable examples, not preloaded development fixtures:

| input           | Final output                  | Executed branch | Skipped branch                                        |
| --------------- | ----------------------------- | --------------- | ----------------------------------------------------- |
| {"amount":11}   | {"result":22}                 | double          | plus                                                  |
| {"amount":4}    | {"result":5}                  | plus            | double                                                |
| {"amount":"11"} | null; failed/EXECUTION_FAILED | neither         | No completion skips; only start/choose attempts exist |

The body is still `{"workflow_version_id":"<saved-uuid>","input":{"amount":11}}`. Success or persisted domain failure returns 201; inspect run.status/error_code. Follow Location or GET /api/v1/runs/{run_id} for exact-version history. Every POST creates a distinct run, and Idempotency-Key is still rejected until supported in 5D.

## Exact operation rules

condition reads its field from the compiler-declared upstream output binding and returns {"result":true/false}. That boolean selects the true or false output handle; other nodes use default, and end terminates the selected route. No arbitrary truthiness conversion is used.

| Operator                                                              | Runtime behavior                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| equals / not_equals                                                   | Compare supported scalar categories: number, boolean, string, null. Int/float share numeric equality; bool is separate, so true does not equal 1. Different categories are unequal; strings retain case/whitespace. Lists/objects fail rather than being structurally compared. |
| greater_than / greater_than_or_equal / less_than / less_than_or_equal | Both values must be finite native int/float in [-10^12,10^12], excluding bool. Numeric strings/null/containers fail with EXECUTION_FAILED.                                                                                                                                      |
| contains                                                              | Case-sensitive substring on two strings, each at most 4096 characters. No array-membership or implicit string conversion.                                                                                                                                                       |

All equality values have the same scalar bounds: finite numbers within ±10^12 and strings at most 4096 Unicode characters. Null equals null; a missing dictionary key is a lookup failure, not a null value. Mismatched valid scalar categories compare unequal, while unsupported values fail.

calculator supports add/multiply over 2–20 operands and subtract/divide over exactly two, as already declared in the configuration schemas. Each operand is an explicit literal or compiler-declared output reference. It returns {"result":number}. Runtime operands and every intermediate/final result must be finite int/float within ±10^12; bool, strings, null and containers are refused. Division by zero, including -0.0, and intermediate overflow fail with EXECUTION_FAILED. Division uses Python float; these are ordinary int/float operations, not a decimal currency engine.

merge copies only the chosen incoming output. It does not concatenate results, wait for the unselected arm or implement parallel scheduling. An explicit input_mapping still replaces that incoming object. References after a merge must be available on every possible incoming path; a branch-local output remains invalid even if a particular run would choose that branch. The compiler's existing dominator rules enforce this before run creation.

Node input stores the resolved data-flow payload, not a synthesized operand list. For example, a calculator immediately after a condition receives {"result":true} by default, but its declared operands can read amount from start. Config reference values resolve separately from the immutable saved config and already completed outputs. They are not guessed from strings that happen to look like references.

manual, transform and end retain the [Phase 5B semantics](first-runner.md). Explicit input mappings use dictionary keys only, preserve arbitrary target-key case/dots, and receive bounded copied JSON objects. Missing source/field or non-dictionary traversal in input/config bindings yields INPUT_MAPPING_FAILED before execution, with failed-attempt input {} and no start time. Present but invalid numeric/comparison values fail after start with EXECUTION_FAILED. Raw exception messages are never persisted or returned.

## Routing and skipped history

The compiler's topological order includes both possible arms. WorkflowRunner now walks from entry_node_id through the selected CompiledRoute instead of executing that entire order. It retains a local visited set and executed outputs. Validated acyclicity and bounded graph size limit traversal; a defensive check also refuses a repeated or missing target. Compilation still validates the entire saved graph before creation, including the unselected arm's config shape and reference availability.

Only visited nodes have their data/config bindings resolved or executor invoked. An unselected division-by-zero or missing runtime field therefore causes no execution failure. Nested conditions, early terminal arms, shared merges and two different handles reaching the same merge are supported. A merge visited on the chosen path is never skipped merely because another incoming arm was not chosen.

When a selected end succeeds, one final unit of work commits:

1. The end attempt's actual result/event.
2. A pending → skipped attempt and its two events for every unvisited saved node, in canonical plan order.
3. The succeeded run/output/event.

Skipped attempts have input {}, output/error_code null, no started_at, duration_ms 0, revision 1 and completion time. They were not executed and contain no fabricated output. Executed successful attempts have revision 2. The existing Phase 5A schema already supports these states; no migration or new event type is required.

On a selected-route failure, execution stops with its actual failed attempt/run. Nodes not visited after that failure retain no attempt rows, consistent with 5B. Completion skips are created only when an end successfully finishes. If a final skip write fails, the entire final transaction rolls back: the previously committed end start remains running with no output, no partial skipped rows and no succeeded run. HTTP 503 identifies a known committed run through Location; no automatic replay/recovery is claimed.

Events remain metadata-only and use the locked per-run cursor. Run detail reads are owner scoped and coherent with cooperating writers. Historical results/skips remain tied to the exact saved version after another definition save, archive or API restart. No mutable Session crosses threads, and input/config resolution and pure computation run outside operation transactions.

## Files and flow

- executions/operations.py contains NodeExecutionError, resolve_reference, resolve_input, resolve_config, execute_node and next_node_id, plus private numeric/scalar/condition/calculator helpers. It imports no database, HTTP, queue or provider adapter. Only compiler-declared bindings are replaced in copied input/config; saved plans and prior outputs are not mutated.
- executions/runner.py now defines WorkflowRunner. It retains the revisioned start/result/failure transactions from 5B, follows selected routes and commits final skipped history with completion. _fail preserves static failure codes and stops traversal.
- executions/service.py uses WorkflowRunner after copying/compiling the exact owned version and rechecking creation policy. API paths/DTO fields/status codes stay the same; api/v1/runs.py documents exclusive branching in OpenAPI.
- workflows/node_configs.py names shared MAX_ABS_NUMBER/MAX_TEXT_LENGTH constants without changing their existing config bounds. node_registry.py now advertises execute readiness for all six implemented pure types. Existing compiler validation/dominators are reused unchanged.
- tests/unit/test_branch_operations.py covers typed comparisons, arithmetic, reference/literal separation, routing and merge copying. tests/integration/test_branch_execution.py covers real selected-route outputs, skips, nested/early exits, failures, frozen history, independent concurrent runs and final-transaction rollback. Existing 5B tests now forward the explicit resolved_config argument; obsolete unsupported-condition/calculator cases are replaced by actual execution coverage.

## Actual verification — 3 November 2026

Full backend checks passed **845 tests** with real PostgreSQL. Default checks passed **598**, skipping **247** database cases. Ruff lint/format passed 118 Python files; Pyright reported zero errors/warnings. Locked offline dependency sync, documentation formatting and relative links passed. This increment adds 68 ordinary and 23 integration cases, replacing two former refusal cases for now-supported types (net +89 tests).

The suite includes 85 pure-operation cases, including previous 5B checks; focused PostgreSQL branch/linear regression tests passed 39 cases. Tests verify both handles, typed equality/numeric boundaries, no string/bool numeric coercion, zero/overflow failures, literal path strings, missing-config reference errors, chosen-predecessor merge behavior, nested branches/early ends/same-target convergence, no resolution/execution of unchosen runtime-invalid arms, exact skip timestamps/revisions/results, event cursor order, no checked-out operation Session during new executors, historical versions/archive, invalid branch-local references, opposite-route concurrent runs and rollback after a flushed skipped event.

Temporary real Uvicorn HTTP checks registered/logged in, saved the example, computed 22 and 5 through opposite routes, persisted corresponding skipped attempts and rejected a numeric-string condition as a failed run. After shutdown/restart, GET returned identical output/version/attempt histories for both successes and the failure. The catalog advertises six ready types; OpenAPI remains 15 operations/12 paths. Checked unauthorized access, private correlated logs and graceful application shutdowns. Only Database targeted a disposable migrated test schema with process-local signing key and explicit local HTTP cookie mode; no development fixture results or private .env access were used.

Read-only development inspection reports 0003 head with no drift; no data/schema/dependency changes were needed. Disposable schemas/public test tables, temporary server/factory/scripts and the owned test container were cleaned up; development PostgreSQL remains running. Earlier auth, compiler, ownership, migrations, lifecycle and rollback/concurrency checks remain green. The registration minimum remains the user-confirmed 8 characters.

## Review and next increment

Next is **Phase 5D: execution command idempotency, bounded pure-node retry, cancellation and failure hardening**. Run listing should be designed within that command/history slice so retained runs can be discovered without a remembered Location. Worker claims/leases/checkpoints/outbox and crash recovery remain Phase 6, followed by Groq/tools/agents, observability, approvals and frontend integration in their owning phases. No new endpoint beyond the two 5B run routes is claimed here.

Exercise (no solution supplied): extend the example with a nested condition whose false route ends early while the other routes share a merge. Predict actual outputs and the exact succeeded/skipped node sets for three inputs. Verify them through run GET, then save another version and confirm earlier results remain unchanged. Use your own test data, not credentials.

Review questions, one at a time:

1. Why is executing every node in topological order incorrect for exclusive branches?
2. How does merge receive a result without waiting for or reading the unchosen arm?
3. Why is a missing field different from a present null value in a typed condition?
4. Why must the end result, skipped attempts and run completion commit together?
