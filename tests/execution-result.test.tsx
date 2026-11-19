import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ExecutionResult } from '../src/api/ExecutionResult';
import { failureGuidance } from '../src/api/failureGuidance';
import { RunOutput } from '../src/api/RunOutput';
import { starterDefinition } from '../src/api/graph';
import type { NodeAttempt, RunDetail } from '../src/api/types';

function run(overrides: Partial<RunDetail> = {}): RunDetail {
  return {
    id: 'run',
    revision: 1,
    status: 'succeeded',
    input: {},
    output: { result: 24 },
    error_code: null,
    workflow_id: 'workflow',
    workflow_version_id: 'version',
    max_attempts: 1,
    parent_run_id: null,
    event_sequence: 0,
    created_at: '2026-11-19T00:00:00Z',
    updated_at: '2026-11-19T00:00:00Z',
    started_at: null,
    completed_at: null,
    version: {
      id: 'version',
      workflow_id: 'workflow',
      created_by: 'owner',
      version_number: 1,
      definition: starterDefinition(),
      created_at: '2026-11-19T00:00:00Z',
    },
    node_runs: [],
    ...overrides,
  };
}
function attempt(overrides: Partial<NodeAttempt> = {}): NodeAttempt {
  return {
    id: 'attempt',
    revision: 1,
    node_id: 'start',
    attempt_number: 1,
    status: 'failed',
    input: {},
    output: null,
    error_code: 'INPUT_MAPPING_FAILED',
    duration_ms: null,
    created_at: '',
    updated_at: '',
    started_at: null,
    completed_at: null,
    ...overrides,
  };
}

describe('execution result guidance', () => {
  it('shows the final structured result with exact business keys and falsy values', () => {
    const output = {
      'Business Key': 0,
      approved: false,
      optional: null,
      content: '# Plain business data',
      nested: { total: 24 },
    };
    const before = JSON.stringify(output);
    const html = renderToStaticMarkup(<RunOutput output={output} attempts={[]} nodes={[]} />);
    expect(html).toContain('<dt>Business Key</dt>');
    expect(html).toContain('<span>0</span>');
    expect(html).toContain('<span>false</span>');
    expect(html).toContain('<span>null</span>');
    expect(html).toContain('View structured value');
    expect(html).toContain('View raw output');
    expect(html).not.toContain('<h1>');
    expect(JSON.stringify(output)).toBe(before);
  });
  it('shows the failed step label and a link to its stored attempt', () => {
    const html = renderToStaticMarkup(
      <ExecutionResult
        run={run({
          status: 'failed',
          output: null,
          error_code: 'INPUT_MAPPING_FAILED',
          node_runs: [attempt()],
        })}
      />,
    );
    expect(html).toContain('This run needs attention');
    expect(html).toContain('Check this step');
    expect(html).toContain('href="#attempt-attempt"');
    expect(html).toContain('INPUT_MAPPING_FAILED');
    expect(html).not.toContain('Your result');
  });
  it('does not report an old failed attempt as a current failure after a later success', () => {
    const html = renderToStaticMarkup(
      <ExecutionResult
        run={run({
          status: 'failed',
          error_code: 'INTERNAL_FAILURE',
          node_runs: [
            attempt({ attempt_number: 2, status: 'succeeded', error_code: null }),
            attempt(),
          ],
        })}
      />,
    );
    expect(html).not.toContain('Inspect step details');
    expect(html).toContain('execution ID');
  });
  it.each(['queued', 'running', 'cancelled', 'waiting_approval'])(
    'does not present partial output as the final result for %s',
    (status) => {
      const html = renderToStaticMarkup(
        <ExecutionResult run={run({ status, output: { secretPartialMarker: 'partial' } })} />,
      );
      expect(html).not.toContain('secretPartialMarker');
      expect(html).not.toContain('Your result');
    },
  );
  it('surfaces a paused agent without treating it as a failed or completed run', () => {
    const html = renderToStaticMarkup(
      <ExecutionResult
        run={run({
          status: 'running',
          node_runs: [
            attempt({
              status: 'running',
              checkpoint: {
                status: 'paused',
                thread_id: 'thread',
                checkpoint_id: 'checkpoint',
                resume_count: 0,
              },
            }),
          ],
        })}
      />,
    );
    expect(html).toContain('Agent paused');
    expect(html).toContain('Continue agent');
    expect(html).not.toContain('This run needs attention');
  });
  it.each([null, 'UNKNOWN_CODE', 'toString', '__proto__'])(
    'provides honest fallback guidance for %s',
    (code) => {
      expect(failureGuidance(code)).toContain('cause is unclear');
    },
  );
  it('gives actionable connection/provider guidance without assuming a retry is safe', () => {
    expect(failureGuidance('CONNECTION_UNAVAILABLE')).toContain('Integrations');
    expect(failureGuidance('PROVIDER_AUTH_FAILED')).toContain('Do not paste API keys');
    expect(failureGuidance('DEADLINE_EXCEEDED')).toContain('external-call records');
  });
});
