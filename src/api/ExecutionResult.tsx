import type { RunDetail } from './types';
import { RunOutput } from './RunOutput';
import { failureGuidance } from './failureGuidance';

export function ExecutionResult({ run }: { run: RunDetail }) {
  const latest = new Map<string, RunDetail['node_runs'][number]>();
  for (const attempt of run.node_runs) {
    const previous = latest.get(attempt.node_id);
    if (!previous || attempt.attempt_number > previous.attempt_number)
      latest.set(attempt.node_id, attempt);
  }
  const failed = [...latest.values()].filter((row) => row.status === 'failed');
  const paused = [...latest.values()].some((row) => row.checkpoint?.status === 'paused');
  const title =
    run.status === 'succeeded'
      ? 'Your result'
      : run.status === 'failed'
        ? 'This run needs attention'
        : run.status === 'cancelled'
          ? 'Execution cancelled'
          : paused
            ? 'Agent paused — ready to continue'
            : run.status === 'queued'
              ? 'Waiting to start'
              : run.status === 'waiting_approval'
                ? 'Execution waiting'
                : 'Execution in progress';
  return (
    <section className="card api-panel execution-result" aria-labelledby="execution-result-title">
      <h2 id="execution-result-title">{title}</h2>
      {run.status === 'succeeded' ? (
        <RunOutput
          output={run.output}
          attempts={run.node_runs}
          nodes={run.version.definition.nodes}
        />
      ) : (
        <>
          <p>
            {run.status === 'failed'
              ? failed.length
                ? 'The workflow stopped before producing a final result. Review the failed step below.'
                : failureGuidance(run.error_code)
              : run.status === 'cancelled'
                ? 'No completed final result is available for this cancelled execution. Completed step history is preserved below.'
                : run.status === 'waiting_approval'
                  ? 'Execution is waiting. Review the step details below for its recorded state.'
                  : paused
                    ? 'A tool result has been saved. Open the paused step below and select Continue agent to continue making model requests.'
                    : 'The final result will appear here after the execution succeeds. This page updates automatically while it is active.'}
          </p>
          {run.status === 'failed' && failed.length > 0 && (
            <ul className="execution-failures">
              {failed.map((row) => (
                <li key={row.id}>
                  <strong>
                    {run.version.definition.nodes.find((node) => node.id === row.node_id)?.label ||
                      row.node_id}
                  </strong>
                  <p>{failureGuidance(row.error_code)}</p>
                  <a
                    href={`#attempt-${row.id}`}
                    onClick={() => {
                      const target = document.getElementById(`attempt-${row.id}`);
                      if (target instanceof HTMLDetailsElement) target.open = true;
                    }}
                  >
                    Inspect step details
                  </a>
                  {row.error_code && <small className="muted">Code: {row.error_code}</small>}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
