# Agent checkpoints and explicit continuation

The Tool Agent stores LangGraph state in a PostgreSQL checkpoint schema and correlates its thread with the workflow run and node attempt. Migration `0011` creates the application-owned invocation records; the LangGraph saver maintains its own tables in a separate schema. Set up both before running agent nodes:

```bash
uv run --directory backend --locked alembic upgrade head
uv run --directory backend --locked python scripts/setup_agent_checkpoints.py
```

Run these commands against the configured application database as an operator. The setup script creates the checkpoint schema and can be run again to apply the saver's setup. Runtime execution does not perform schema setup. Checkpoints may contain the agent's conversation and tool results, so protect and back up this schema as application data.

In the editor, enable **Pause after each tool** on a Tool Agent and save the workflow. After a tool finishes, execution pauses at a saved boundary. The execution details show the thread and provide **Continue**. Continuation uses the same run and node attempt, checks the current checkpoint and owner, and rechecks connection authorization. Earlier committed workflow results and completed tool calls are not rerun. At most five continuations are allowed, within the agent's existing tool and elapsed-time bounds.

The API equivalent is `POST /api/v1/runs/{run_id}/agent-resume` with `node_run_id` and `checkpoint_id` from the owned run details. A stale, already consumed, cancelled or concurrent continuation is rejected. After a lost response, inspect run history before continuing again. Events record checkpoint and continuation transitions.

Only an explicitly saved post-tool pause is eligible for continuation. A process interruption during an external request has an uncertain outcome and is not automatically resumed or replayed. Agent workflows remain synchronous and are not automatically recovered by background workers. Human approval and reconciliation of ambiguous external effects remain future work.
