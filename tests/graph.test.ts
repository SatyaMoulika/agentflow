import { describe, expect, it } from 'vitest';
import { fixtureWorkflows } from '../src/data/fixtures';
import { autoLayout, canConnect, validateNode, validateWorkflow } from '../src/lib/graph';
import type { Workflow } from '../src/types';

const invoice = () => structuredClone(fixtureWorkflows[0]);
const messages = (workflow: Workflow) => validateWorkflow(workflow).map((issue) => issue.message);

describe('workflow validation', () => {
  it.each(fixtureWorkflows.map((workflow) => [workflow.name, workflow] as const))(
    'accepts the complete %s fixture',
    (_, workflow) => {
      expect(validateWorkflow(workflow)).toEqual([]);
    },
  );

  it('reports missing configuration on the associated node and field', () => {
    const workflow = invoice();
    const extract = workflow.nodes.find((node) => node.type === 'extract')!;
    extract.config.prompt = '';
    expect(validateWorkflow(workflow)).toContainEqual({
      nodeId: extract.id,
      field: 'prompt',
      message: `${extract.label}: Prompt is required.`,
    });
  });

  it('identifies a disconnected step, cycles, and missing nodes', () => {
    const workflow = invoice();
    workflow.edges = workflow.edges.filter((edge) => edge.source !== 'invoice_trigger');
    expect(
      messages(workflow).some((message) => message.includes('connect this node to the trigger')),
    ).toBe(true);
    workflow.edges.push({ id: 'cycle', source: 'invoice_store', target: 'invoice_extract' });
    workflow.edges.push({ id: 'missing', source: 'invoice_end', target: 'not-a-node' });
    expect(messages(workflow).some((message) => message.includes('contains a cycle'))).toBe(true);
    expect(messages(workflow).some((message) => message.includes('missing node'))).toBe(true);
  });

  it('requires the true and false condition routes and both approval decisions', () => {
    const workflow = invoice();
    workflow.edges = workflow.edges.filter(
      (edge) =>
        !(edge.source === 'invoice_condition' && edge.sourceHandle === 'false') &&
        !(edge.source === 'invoice_approve' && edge.sourceHandle === 'rejected'),
    );
    expect(messages(workflow)).toContain('Amount exceeds ₹50,000?: connect the false branch.');
    expect(messages(workflow)).toContain('Finance approval: connect the rejected branch.');
  });

  it('rejects invalid branch names and duplicate connections loaded from storage', () => {
    const workflow = invoice();
    workflow.edges.push({
      id: 'bad-branch',
      source: 'invoice_condition',
      sourceHandle: 'maybe',
      target: 'invoice_end',
    });
    workflow.edges.push({ id: 'duplicate', source: 'invoice_store', target: 'invoice_end' });
    expect(messages(workflow).some((message) => message.includes('invalid output branch'))).toBe(
      true,
    );
    expect(
      messages(workflow).some((message) =>
        message.includes('each output can connect to one next step'),
      ),
    ).toBe(true);
  });

  it('validates HTTP JSON, URLs, and AI settings without rejecting mapped request bodies', () => {
    const workflow = invoice();
    const http = workflow.nodes.find((node) => node.type === 'http')!;
    http.config.url = 'ftp://example.com';
    http.config.headers = '{bad json}';
    expect(validateNode(http).map((issue) => issue.field)).toEqual(
      expect.arrayContaining(['url', 'headers']),
    );
    http.config = { url: 'https://example.com', headers: '{}', body: '{{ input }}' };
    expect(validateNode(http)).toEqual([]);
    const ai = workflow.nodes.find((node) => node.type === 'extract')!;
    ai.config.temperature = 3;
    ai.config.maxTokens = 0;
    expect(validateNode(ai).map((issue) => issue.field)).toEqual(
      expect.arrayContaining(['temperature', 'maxTokens']),
    );
  });
});

describe('connection guards', () => {
  it('prevents self-connections, cycles, duplicates, and incoming trigger connections', () => {
    const workflow = invoice();
    expect(canConnect(workflow, { source: 'invoice_extract', target: 'invoice_extract' })).toBe(
      false,
    );
    expect(canConnect(workflow, { source: 'invoice_store', target: 'invoice_trigger' })).toBe(
      false,
    );
    expect(canConnect(workflow, { source: 'invoice_trigger', target: 'invoice_extract' })).toBe(
      false,
    );
    expect(canConnect(workflow, { source: 'invoice_end', target: 'invoice_store' })).toBe(false);
    workflow.edges = workflow.edges.filter((edge) => edge.source !== 'invoice_store');
    expect(canConnect(workflow, { source: 'invoice_store', target: 'invoice_extract' })).toBe(
      false,
    );
    expect(canConnect(workflow, { source: 'invoice_store', target: 'invoice_end' })).toBe(true);
  });

  it('only accepts known output handles and a single destination per branch', () => {
    const workflow = invoice();
    workflow.edges = workflow.edges.filter((edge) => edge.source !== 'invoice_condition');
    expect(canConnect(workflow, { source: 'invoice_condition', target: 'invoice_approve' })).toBe(
      false,
    );
    expect(
      canConnect(workflow, {
        source: 'invoice_condition',
        target: 'invoice_approve',
        sourceHandle: 'maybe',
      }),
    ).toBe(false);
    expect(
      canConnect(workflow, {
        source: 'invoice_condition',
        target: 'invoice_approve',
        sourceHandle: 'true',
      }),
    ).toBe(true);
    workflow.edges.push({
      id: 'branch',
      source: 'invoice_condition',
      target: 'invoice_approve',
      sourceHandle: 'true',
    });
    expect(
      canConnect(workflow, {
        source: 'invoice_condition',
        target: 'invoice_end',
        sourceHandle: 'true',
      }),
    ).toBe(false);
    expect(
      canConnect(workflow, {
        source: 'invoice_condition',
        target: 'invoice_end',
        sourceHandle: 'false',
      }),
    ).toBe(true);
  });
});

describe('graph layout', () => {
  it('places dependencies left to right without changing the original configuration or edges', () => {
    const workflow = invoice();
    const original = structuredClone(workflow);
    const arranged = autoLayout(workflow);
    expect(workflow).toEqual(original);
    expect(arranged.edges).toEqual(original.edges);
    for (const edge of arranged.edges) {
      expect(arranged.nodes.find((node) => node.id === edge.source)!.position.x).toBeLessThan(
        arranged.nodes.find((node) => node.id === edge.target)!.position.x,
      );
    }
    expect(
      new Set(arranged.nodes.map((node) => `${node.position.x}:${node.position.y}`)).size,
    ).toBe(arranged.nodes.length);
    expect(validateWorkflow(arranged)).toEqual([]);
  });
});
