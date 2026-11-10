import { describe, expect, it } from 'vitest';
import { fixtureWorkflows } from '../src/data/fixtures';
import { validateWorkflow } from '../src/lib/graph';
import {
  createBlankWorkflow,
  generateMockWorkflow,
  type GeneratedWorkflow,
  type GenerationFixture,
} from '../src/services/generation';

const examples: { fixture: GenerationFixture; prompt: string }[] = [
  {
    fixture: 'invoice',
    prompt: 'Process invoices, extract the details, and request approval above ₹50,000.',
  },
  {
    fixture: 'email',
    prompt: 'Classify incoming emails by priority and route them to the team inbox.',
  },
  { fixture: 'email', prompt: 'Summarize incoming emails and classify each email by priority.' },
  {
    fixture: 'support',
    prompt: 'Classify customer support tickets and route them to the right team.',
  },
  { fixture: 'csv', prompt: 'Analyze uploaded CSV files and generate a concise summary report.' },
  { fixture: 'document', prompt: 'Summarize uploaded documents into concise actionable notes.' },
  { fixture: 'lead', prompt: 'Research and qualify leads before updating their CRM records.' },
  {
    fixture: 'report',
    prompt: 'Generate daily performance reports with a summary of the results.',
  },
];

function generate(prompt: string): GeneratedWorkflow {
  const result = generateMockWorkflow(prompt);
  if (!result.ok) throw new Error(result.error);
  return result;
}

describe('deterministic mock workflow generation', () => {
  it.each(examples)('produces a valid $fixture graph for "$prompt"', ({ fixture, prompt }) => {
    const result = generate(prompt);
    expect(result.fixture).toBe(fixture);
    expect(validateWorkflow(result.workflow)).toEqual([]);
    expect(result.workflow).toMatchObject({
      status: 'draft',
      version: 1,
      totalRuns: 0,
      successRate: 0,
    });
    expect(result.workflow.lastRun).toBeUndefined();
    expect(result.workflow.nodes.filter((node) => node.type === 'manual')).toHaveLength(1);
    expect(result.requiredIntegrations).toContain('AI provider (demo)');
    expect(result.configurationNotes.some((note) => note.includes('simulated data'))).toBe(true);
    expect(result.configurationNotes.some((note) => note.includes('demo template'))).toBe(true);
  });

  it('retains both condition branches and both approval outcomes in the invoice graph', () => {
    const { workflow } = generate(examples[0].prompt);
    const condition = workflow.nodes.find((node) => node.type === 'condition')!;
    const approval = workflow.nodes.find((node) => node.type === 'approval')!;
    const storage = workflow.nodes.find((node) => node.type === 'http')!;
    expect(condition.config).toMatchObject({
      variable: 'amount',
      operator: 'greater_than',
      value: '50000',
    });
    expect(workflow.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          source: condition.id,
          target: approval.id,
          sourceHandle: 'true',
        }),
        expect.objectContaining({
          source: condition.id,
          target: storage.id,
          sourceHandle: 'false',
        }),
        expect.objectContaining({
          source: approval.id,
          target: storage.id,
          sourceHandle: 'approved',
        }),
      ]),
    );
    const rejectedEdge = workflow.edges.find(
      (edge) => edge.source === approval.id && edge.sourceHandle === 'rejected',
    )!;
    expect(workflow.nodes.find((node) => node.id === rejectedEdge.target)?.type).toBe('end');
    expect(rejectedEdge.target).not.toBe(storage.id);
  });

  it('includes a configured summarization step when the email prompt requests summaries', () => {
    const { workflow } = generate('Summarize incoming emails and classify them by priority.');
    const summary = workflow.nodes.find((node) => node.type === 'llm')!;
    const classification = workflow.nodes.find((node) => node.type === 'classify')!;
    expect(summary.config.prompt).toMatch(/summarize.*email/i);
    expect(summary.config.model).toBeTruthy();
    expect(
      workflow.edges.some(
        (edge) => edge.source === summary.id && edge.target === classification.id,
      ),
    ).toBe(true);
    expect(classification.config.prompt).toMatch(/priority/i);
  });

  it('includes CSV parsing before analysis and uses a connected terminal node', () => {
    const { workflow } = generate('Analyze uploaded CSV files and summarize their key trends.');
    const parser = workflow.nodes.find((node) => node.type === 'parser')!;
    const analysis = workflow.nodes.find((node) => node.type === 'llm')!;
    expect(parser.config.input).toBe('{{trigger.csv}}');
    expect(analysis.config.prompt).toMatch(/csv records/i);
    expect(
      workflow.edges.some((edge) => edge.source === parser.id && edge.target === analysis.id),
    ).toBe(true);
    expect(workflow.nodes.at(-1)?.type).toBe('end');
  });

  it('isolates generated graphs from canonical fixtures and later generations', () => {
    const canonical = fixtureWorkflows.find((workflow) => workflow.id === 'wf_invoice')!;
    const original = structuredClone(canonical);
    const first = generate(examples[0].prompt).workflow;
    first.name = 'User-edited name';
    first.nodes.find((node) => node.type === 'condition')!.config.value = '999999';
    first.nodes[0].position.x = -500;
    first.edges[0].target = 'removed-by-user';

    const second = generate(examples[0].prompt).workflow;
    expect(canonical).toEqual(original);
    expect(second.id).not.toBe(first.id);
    expect(second.id).not.toBe(canonical.id);
    expect(second.name).toBe(original.name);
    expect(second.nodes).toEqual(original.nodes);
    expect(second.edges).toEqual(original.edges);
    expect(second.nodes[0]).not.toBe(canonical.nodes[0]);
    expect(second.nodes[0].config).not.toBe(canonical.nodes[0].config);
    expect(second.edges[0]).not.toBe(canonical.edges[0]);
  });

  it.each(['', '    ', 'invoice', '  email  '])(
    'rejects a short or empty prompt "%s"',
    (prompt) => {
      const result = generateMockWorkflow(prompt);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.error).toContain('at least 15 characters');
      expect('workflow' in result).toBe(false);
    },
  );

  it.each([
    'Book a restaurant table for my next holiday.',
    'Plan daily restaurant reservations for the team.',
  ])('explains the prototype limitation for unsupported prompt "%s"', (prompt) => {
    const result = generateMockWorkflow(prompt);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/prototype supports.*invoice.*CSV.*daily report/i);
    expect('workflow' in result).toBe(false);
  });

  it('creates independent blank drafts with a manual trigger ready to extend', () => {
    const first = createBlankWorkflow();
    const second = createBlankWorkflow();
    expect(first.id).not.toBe(second.id);
    expect(first.nodes[0].id).not.toBe(second.nodes[0].id);
    expect(first).toMatchObject({ status: 'draft', version: 1, totalRuns: 0, edges: [] });
    expect(first.nodes).toHaveLength(1);
    expect(first.nodes[0].type).toBe('manual');
    expect(validateWorkflow(first).map((issue) => issue.message)).toContain(
      'Add an End node to finish the workflow.',
    );
  });
});
