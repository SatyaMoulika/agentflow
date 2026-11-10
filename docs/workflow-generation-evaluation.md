# Workflow generation evaluation

The evaluation set checks six synthetic requests: branching arithmetic (both paths),
multiplication with two inputs, field selection, a support-reply workflow, and
requests requiring email or a schedule. The unsupported cases expect an explicit
refusal rather than a workflow that silently drops the requested action.

List cases without loading a key or making network calls:

```bash
uv run --directory backend --locked python -m scripts.evaluate_workflows
```

To send one synthetic request to the configured Groq model:

```bash
uv run --directory backend --locked python -m scripts.evaluate_workflows --live --case branch_amount
```

Omit `--case` to run all six. Repeat `--case` to choose multiple cases. Live
generation uses `GROQ_API_KEY` and `AGENTFLOW_GROQ_MODEL` from the backend settings,
consumes provider quota, and stops after a rate-limit response. A malformed or
invalid proposal gets at most one regeneration: the original request and static
validation codes are sent again, but the rejected response is not. Thus a case can
make up to two generation requests. Provider failures and rate limits are not retried.
It does not create workflows or write to the database. Only case names and static
outcome codes are printed; a passing case is labeled when regeneration was needed.

If both proposals fail, `invalid_proposal:invalid_schema`, `invalid_sample`, or
`invalid_graph` identifies the stage. Graph failures can also list static compiler
codes. The previous evaluator did not retain responses, so it cannot recover the
exact cause of an earlier `invalid_proposal` result.

Ready proposals must compile and execute using the actual pure-node operations.
Each deterministic case compares actual outputs to expected values, including both
branches where applicable. A Groq node is **stubbed locally** during evaluation:
the harness verifies that the selected message reaches it, but does not call Groq
to produce the node's answer or judge that answer's quality. Suggested sample input
must also execute with the stub. Unsupported cases check the returned status and
absence of a graph, not the truth or completeness of the natural-language explanation.

Results are a small, repeatable measurement, not a guarantee: model output varies,
and passing these inputs does not establish that a generated workflow matches every
user request or behaves correctly for all inputs. Graphs still require human review.
The regular automated tests exercise the evaluator offline and never use a real key.

On 4 November 2026, one live run with `openai/gpt-oss-120b` passed 6/6 cases.
This is one observation, not a promised pass rate or provider availability guarantee.
