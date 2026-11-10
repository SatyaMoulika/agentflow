# Phase 4C — node registry and typed configuration

Current follow-on: [Phase 5C branch execution](branch-execution.md) adds conditions/calculators, selected-route merges and persisted completion skips. All six registered types are now execution-ready. Scope and verification below record the original increment.

Current follow-on: [Phase 5B first runner](first-runner.md) implements actual manual/transform/end execution and run APIs. Scope/results below record the original increment.

Newer increment: [Phase 4D workflow validation/compiler](workflow-validation.md) now uses these contracts for read-only saved/candidate validation. This note retains the Phase 4C implementation/verification; node execution remains unavailable.

Verified 2 November 2026. This increment implements authenticated node-contract discovery and internal typed configuration validation. Phase 4B draft/version storage is unchanged. No executor, graph compiler, provider call or frontend wiring is introduced. To inspect your own stored backend data now, use the [real backend walkthrough](../real-backend-walkthrough.md).

## Design and boundary

A node registry is the server's code-owned list of contracts. It gives a future compiler and editor one source for type IDs, configuration schemas and output handles. The client cannot register Python code, provide a module path or enable an executor by changing JSON. Configuration validity and execution availability are separate facts.

GET /api/v1/node-types requires the existing active-user Bearer JWT. It returns NodeTypeCatalog with schema_version "1.0" and items in stable registration order. Each item has type, name, lowercase category, description, output_handles, config_schema, capabilities and execution_ready. Every capability list currently contains only validate_config, and execution_ready is always false. No input/output runtime schema, fake model ID, credential or future connector capability is advertised. There are now **12 implemented operations across nine paths** in the API.

| Type       | Strict configuration                                                                                       | Declared output handles |
| ---------- | ---------------------------------------------------------------------------------------------------------- | ----------------------- |
| manual     | Empty object. Future run input belongs to a run request.                                                   | default                 |
| transform  | operation identity, or pick_fields with 1–100 unique literal top-level field names, each 1–200 characters. | default                 |
| condition  | field output reference, operator, and an explicitly typed comparison value.                                | true, false             |
| calculator | operation add/multiply with 2–20 operands, or subtract/divide with exactly two operands.                   | default                 |
| merge      | Empty object; intended for exclusive-branch reconvergence.                                                 | default                 |
| end        | Empty object.                                                                                              | none                    |

Config models forbid unknown keys and coercion, reject non-finite numeric values, and revalidate previously constructed models passed through the internal boundary. Expression, prompt, timeout/retries and old editor aliases do not silently become supported config fields. The catalog omits llm, agent, http, classify, extract, parser, approval, webhook and schedule until their contracts/capabilities arrive in their owning increments. They can still be stored in an unfinished draft: save acceptance is not graph validation.

No new package, environment variable, model, table or migration is needed. Revision remains 0002. Registry discovery performs no database mutation; its existing authentication dependency reads the current active account. Successful responses use no-store. Missing credentials return the existing 401/challenge; unavailable auth configuration/storage gives the existing safe 503.

## Typed operations and output references

Transform examples:

```json
{ "operation": "identity" }
```

```json
{ "operation": "pick_fields", "fields": ["CustomerID", "invoice_total"] }
```

Field names are literal top-level business keys, preserved with case/whitespace/dots intact; they are not expressions or paths. Configuration validation does not inspect the actual runtime input or promise selected-field output values.

Condition example:

```json
{ "field": "$.start.output.amount", "operator": "greater_than", "value": 50000 }
```

Ordered operators are greater_than, greater_than_or_equal, less_than and less_than_or_equal; their value is a finite number, not a numeric string or boolean. Contains requires a string. Equals/not_equals accept an explicit JSON scalar (string, bool, number or null); tests verify that 1, 1.0, "1", true and null preserve their supplied types. Strings are at most 4096 characters. Numbers in these initial contracts are bounded to [-1000000000000, 1000000000000]. The future executor owns runtime comparison behavior and checks actual resolved values.

Calculator example:

```json
{
  "operation": "multiply",
  "operands": [
    { "kind": "output", "path": "$.start.output.amount" },
    { "kind": "literal", "value": 1.18 }
  ]
}
```

Each operand explicitly chooses literal/value or output/path; mixing both shapes is forbidden. Literal numeric bounds apply as above. Validation stores no result and performs no arithmetic: even a literal zero divisor is a syntactically valid config at this boundary. Execution must check resolved types/ranges, zero division, finite/bounded results and classified failures when implemented. No expression string, eval, attribute traversal or template interpolation is provided.

The shared reference grammar is `$.<node_id>.output` followed by zero to sixteen `.field` segments, at most 512 ASCII characters overall. Each node/field segment starts with an ASCII letter or underscore and then contains letters, digits, underscore or hyphen, max 64 characters. Example: $.node_1-a.output.CustomerID. No array index, wildcard, quoted/bracket key, arithmetic, space or newline is accepted. Arbitrary business JSON remains saveable; keys outside this path subset cannot be addressed by this initial reference grammar. A field such as **class** is a dictionary key, never a Python attribute. The future resolver must enforce dictionary-only access.

This increment validates syntax, not whether a referenced node exists, is upstream, is authorized or actually emits that field. Those graph/mapping checks belong to Phase 4D, and actual output checks belong to execution. Merge handles do not implement parallel fan-out or a join scheduler.

## Files and functions

- app/modules/workflows/node_configs.py defines strict NodeConfig defaults, the reusable OutputReference/number constraints, empty structural configs, discriminated transform/condition/calculator variants and operand variants. PickFieldsTransformConfig.unique_fields enforces the uniqueness also declared in its JSON Schema. Discriminators select a variant using operation, operator or kind; validation never guesses from unrelated fields.
- app/modules/workflows/node_registry.py holds frozen registrations in a tuple and a read-only lookup map. TypeAdapter instances compile the typed contracts once. node_type_catalog generates fresh DTOs/self-contained JSON Schemas so a caller changing one response cannot mutate the catalog. validate_node_config returns a validated model for the later compiler, or a static UnsupportedNodeTypeError/InvalidNodeConfigError without the raw config or underlying validator text.
- app/api/v1/node_types.py exposes the read-only catalog, reuses get_current_user, declares the response/error/security contract and sets no-store. app/api/router.py includes the router. No workflow save/service/repository policy changes were required.
- tests/unit/test_node_registry.py checks config operations, strict scalar types, bounds, discriminator/extra-field rejection, reference grammar, unknown capabilities, local JSON-Schema references, catalog mutation isolation, changed-model revalidation and continued incomplete draft saves.
- tests/api/test_node_types.py checks Bearer-only discovery, public DTOs/handles/readiness/no-store and OpenAPI. Existing health/registration/logout/workflow inventories now include the single new route. The PostgreSQL workflow suite also verifies actual two-user discovery, inactive-user rejection and absence of workflow/version mutations.

The HTTP flow is Bearer verification → current active account lookup → fresh catalog/schema DTOs → no-store response. No request config is executed. The separate internal flow is lookup node type → select the typed config adapter → strict validation → validated model or static domain error. Phase 4D will call it while validating an owned saved/candidate graph.

[Pydantic TypeAdapter](https://docs.pydantic.dev/latest/concepts/type_adapter/) provides validation and schema generation for the union contracts. [Discriminated unions](https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions) select a named variant without trying to coerce every alternative. Each schema's local $defs/$ref remains inside that config_schema object; clients should resolve it there, not under the API's component schemas.

## Actual verification

Complete backend checker with real isolated PostgreSQL: **465 passed**. Ordinary checker: **321 passed, 144 skipped**. Added 74 ordinary cases and one PostgreSQL case. Focused registry/config/API run: 74 passed. Ruff lint/format passes 90 Python files, Pyright reports zero errors/warnings and locked offline synchronization passes. Existing version immutability, migrations/drift/round trips, auth, rollback, ownership and concurrency tests remain green.

Live real Uvicorn verified catalog 401 before login, real registration/login/Bearer discovery, all six schemas and handles, validate_config-only capabilities/readiness false, no-store, saving incomplete/unsupported draft configurations without treating them as executable, catalog and draft persistence across restart, 12 operations/nine paths, private key/password/token/config omission from logs, request-ID correlation and graceful shutdown. Only the shared Database resource was pointed at a disposable migrated test schema; the signing key was process-local. No development account/data/private .env was read or edited. No browser UI or Groq execution was claimed.

Cleanup found zero random test schemas and zero public test tables. Temporary server/factory/script/test container were removed; development PostgreSQL remains running. Documentation formatting and relative links passed.

## Review and next increment

Next: Phase 4D, authoritative graph validation/compiler and the owned workflow validation endpoint. It will use these strict contracts while preserving draft-save behavior. Actual deterministic execution follows in Phase 5; Groq integration follows in its provider phase with a configured Free Plan model. The complete remaining roadmap and real-data viewing instructions are in the [walkthrough](../real-backend-walkthrough.md).

Exercise (no solution supplied): validate a calculator config with one output-reference operand and one numeric literal, then replace the literal with a numeric string and assert a static config error. Confirm the unfinished version still saves as a draft. Use isolated fixtures, not development data.

Review questions, one at a time:

1. Why can a configuration be valid while execution_ready remains false?
2. Why must graph validation check an output reference beyond its syntax?
3. Why should a failed executable-config check not prevent saving an unfinished draft?
4. Why expose only implemented configuration contracts rather than every node shown by the demo UI?
