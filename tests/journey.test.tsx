import { describe, expect, it } from 'vitest';
import { renderToString } from 'react-dom/server';
import { starterWorkflow, setupIssues, isGitHubReadEndpoint } from '../src/api/journey';
import { readInputFields, buildInput } from '../src/api/workflowInputs';
import { WorkflowJourney, WorkflowReadiness } from '../src/api/WorkflowJourney';
import { NodeConfiguration } from '../src/api/NodeConfiguration';

describe('guided workflow journey', () => {
  it('creates isolated opt-in calculator drafts with a numeric input contract', () => {
    const first = starterWorkflow('calculator');
    const second = starterWorkflow('calculator');
    first.definition.nodes[1].config.operation = 'add';
    expect(second.definition.nodes[1].config).toEqual({
      operation: 'multiply',
      operands: [
        { kind: 'output', path: '$.start.output.amount' },
        { kind: 'literal', value: 2 },
      ],
    });
    expect(buildInput(readInputFields(second.definition)!, { amount: '12' })).toEqual({
      amount: 12,
    });
    expect(setupIssues(second.definition)).toEqual([]);
    expect(second.definition.edges.map((e) => [e.source, e.target])).toEqual([
      ['start', 'double'],
      ['double', 'finish'],
    ]);
  });
  it('requires a connection and preserves its exact identifier in a bounded GitHub agent', () => {
    expect(() => starterWorkflow('github')).toThrow('Choose an active GitHub connection');
    const id = '12345678-1234-1234-1234-123456789abc';
    const draft = starterWorkflow('github', id);
    expect(draft.definition.nodes[1].config.connection_ids).toEqual([id]);
    expect(draft.definition.nodes[1].config.max_tool_rounds).toBe(3);
    expect(readInputFields(draft.definition)?.[0].name).toBe('request');
  });
  it('only offers supported fixed GitHub collection endpoints', () => {
    expect(isGitHubReadEndpoint('https://api.github.com/repos/example/repo/issues')).toBe(true);
    expect(isGitHubReadEndpoint('https://api.github.com/repos/example/repo/pulls')).toBe(true);
    for (const url of [
      'https://evil.example/repos/x/y/issues',
      'https://api.github.com/repos/x/y/issues/1',
      'https://api.github.com/repos/x/y/issues?page=2',
      'http://api.github.com/repos/x/y/issues',
    ])
      expect(isGitHubReadEndpoint(url)).toBe(false);
  });
  it('reports setup gaps without claiming provider readiness', () => {
    const draft = starterWorkflow('github', '12345678-1234-1234-1234-123456789abc');
    draft.definition.nodes[1].config.instruction = '';
    expect(setupIssues(draft.definition)).toContain('Read and brief: write instructions.');
    const html = renderToString(<WorkflowReadiness definition={draft.definition} saved={false} />);
    expect(html).toContain('Save your changes');
    expect(html).toContain('checked at run time');
    expect(html).not.toContain('validation passed');
  });
  it('marks only the current stage and exposes common controls without changing config', () => {
    expect(
      renderToString(<WorkflowJourney stage="run" />).match(/aria-current="step"/g),
    ).toHaveLength(1);
    const draft = starterWorkflow('github', '12345678-1234-1234-1234-123456789abc');
    const before = JSON.stringify(draft);
    const html = renderToString(
      <NodeConfiguration
        node={draft.definition.nodes[1]}
        disabled={false}
        onChange={() => {
          throw Error('unexpected mutation');
        }}
        renderJson={() => null}
      />,
    );
    expect(html).toContain('Instructions');
    expect(html).toContain('Input field name');
    expect(html).toContain('Advanced configuration');
    expect(JSON.stringify(draft)).toBe(before);
  });
});
