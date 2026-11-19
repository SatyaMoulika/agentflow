import type { Definition, Validation } from './types';
import { setupIssues } from './journey';
export function WorkflowJourney({ stage }: { stage: 'choose' | 'configure' | 'run' | 'results' }) {
  const current = { choose: 0, configure: 1, run: 3, results: 4 }[stage];
  return (
    <nav aria-label="Workflow journey" className="workflow-journey">
      <ol>
        {[
          'Choose a start',
          'Connect & configure',
          'Save & validate',
          'Run with input',
          'Review results',
        ].map((label, index) => (
          <li key={label} aria-current={index === current ? 'step' : undefined}>
            <span>{index + 1}</span>
            {label}
          </li>
        ))}
      </ol>
    </nav>
  );
}
export function WorkflowReadiness({
  definition,
  saved = true,
  validation,
}: {
  definition: Definition;
  saved?: boolean;
  validation?: Validation | null;
}) {
  const issues = setupIssues(definition);
  const external = definition.nodes.some((n) =>
    ['agent', 'groq', 'extract', 'classify', 'http', 'gmail_read'].includes(n.type),
  );
  return (
    <section className="card api-panel workflow-readiness" aria-label="Workflow readiness">
      <h2>Before you run</h2>
      <ul>
        <li>{saved ? 'Saved version selected.' : 'Save your changes before running.'}</li>
        {issues.map((issue) => (
          <li key={issue} className="api-inline-error">
            {issue}
          </li>
        ))}
        <li>
          {validation
            ? validation.execution_ready
              ? 'Server graph validation passed. It does not guarantee useful model output or provider availability.'
              : 'Server validation found issues. Fix them before running.'
            : 'Check the graph with the server. Every run also validates it before execution.'}
        </li>
      </ul>
      {external && (
        <p className="muted">
          This workflow can call external services and save inputs/results. Provider configuration
          and connection authorization are checked at run time. Viewing this checklist makes no
          provider call.
        </p>
      )}
      <p className="muted">
        Manual start only. Background processing is not a schedule or webhook. Sending messages and
        approval steps are not supported.
      </p>
    </section>
  );
}
