import { fixtureWorkflows } from '../data/fixtures';
import { createNode } from '../lib/node-registry';
import { uid } from '../lib/utils';
import type { NodeType, Workflow } from '../types';

export type GenerationFixture =
  'invoice' | 'email' | 'support' | 'csv' | 'document' | 'lead' | 'report';
export interface GeneratedWorkflow {
  workflow: Workflow;
  fixture: GenerationFixture;
  requiredIntegrations: string[];
  configurationNotes: string[];
}
export type GenerationResult = ({ ok: true } & GeneratedWorkflow) | { ok: false; error: string };
export const generationStages = [
  'Understanding your request',
  'Planning the workflow',
  'Connecting nodes and configuring steps',
  'Preparing your preview',
];

const fixtureIds: Record<GenerationFixture, string> = {
  invoice: 'wf_invoice',
  email: 'wf_email',
  support: 'wf_support',
  csv: 'wf_document',
  document: 'wf_document',
  lead: 'wf_lead',
  report: 'wf_report',
};

function freshWorkflow(fixture: Workflow): Workflow {
  const now = new Date().toISOString();
  return {
    ...structuredClone(fixture),
    id: uid('wf'),
    status: 'draft',
    version: 1,
    createdAt: now,
    updatedAt: now,
    lastRun: undefined,
    totalRuns: 0,
    successRate: 0,
  };
}

function replaceWithChain(workflow: Workflow, types: NodeType[]): void {
  workflow.nodes = types.map((type, index) => createNode(type, { x: index * 300, y: 150 }));
  workflow.edges = workflow.nodes.slice(1).map((node, index) => ({
    id: `generated-edge-${index}`,
    source: workflow.nodes[index].id,
    target: node.id,
  }));
}

/** A deterministic local adapter. Replace it with a typed FastAPI call when a backend is available. */
export function generateMockWorkflow(prompt: string): GenerationResult {
  const text = prompt.trim();
  if (text.length < 15)
    return {
      ok: false,
      error: 'Describe your workflow in at least 15 characters so we can choose a useful demo.',
    };
  const fixture: GenerationFixture | undefined = /\binvoices?\b/i.test(text)
    ? 'invoice'
    : /\b(?:e-?mails?|inbox)\b/i.test(text)
      ? 'email'
      : /\b(?:support|tickets?)\b/i.test(text)
        ? 'support'
        : /\bcsv\b/i.test(text)
          ? 'csv'
          : /\bdocuments?\b/i.test(text)
            ? 'document'
            : /\bleads?\b/i.test(text)
              ? 'lead'
              : /\b(?:reports?|performance)\b/i.test(text)
                ? 'report'
                : undefined;
  if (!fixture)
    return {
      ok: false,
      error:
        'This prototype supports invoice, email, support ticket, document, lead, CSV, and daily report workflows. Try a suggested prompt to explore a complete example.',
    };
  const canonical = fixtureWorkflows.find((workflow) => workflow.id === fixtureIds[fixture]);
  if (!canonical)
    return {
      ok: false,
      error: 'The demo workflow template is unavailable. Try another supported example.',
    };
  const workflow = freshWorkflow(canonical);
  if (fixture === 'csv') {
    workflow.name = 'CSV Analysis Pipeline';
    workflow.description =
      'Parse an uploaded CSV, analyze its records, and produce a structured summary.';
    replaceWithChain(workflow, ['manual', 'parser', 'llm', 'end']);
    workflow.nodes[0].label = 'CSV file received';
    workflow.nodes[1].label = 'Parse CSV file';
    workflow.nodes[1].config.input = '{{trigger.csv}}';
    workflow.nodes[1].config.description = 'Parse the demo CSV file into structured records.';
    workflow.nodes[2].label = 'Analyze and summarize';
    workflow.nodes[2].config.prompt =
      'Analyze the supplied CSV records. Summarize key trends, record counts, and any missing values.';
    workflow.nodes[3].label = 'Analysis complete';
  }
  if (fixture === 'email' && /summari[sz]|summar(?:y|ies)/i.test(text)) {
    workflow.name = 'Email Summary & Classification';
    workflow.description =
      'Summarize incoming messages, classify their priority, and send the result to your team inbox.';
    replaceWithChain(workflow, ['manual', 'llm', 'classify', 'http', 'end']);
    workflow.nodes[0].label = 'Email received';
    workflow.nodes[1].label = 'Summarize email';
    workflow.nodes[1].config.prompt =
      'Summarize the incoming email in three concise bullet points, including requested actions and deadlines.';
    workflow.nodes[2].label = 'Classify email priority';
    workflow.nodes[2].config.prompt =
      'Classify this email as low, normal, or high priority. Return the priority and department.';
    workflow.nodes[3].label = 'Send summary to inbox';
    workflow.nodes[4].label = 'Email processed';
  }
  const requiredIntegrations = [
    ...(workflow.nodes.some((node) => ['llm', 'classify', 'extract', 'agent'].includes(node.type))
      ? ['AI provider (demo)']
      : []),
    ...(workflow.nodes.some((node) => node.type === 'http') ? ['HTTP API (demo)'] : []),
  ];
  return {
    ok: true,
    workflow,
    fixture,
    requiredIntegrations,
    configurationNotes: [
      'Your prompt selects a supported demo template. Customize any additional requirements in the editor.',
      'A manual trigger lets you start this example without an external service.',
      ...(workflow.nodes.some((node) => node.type === 'approval')
        ? ['Review the ₹50,000 threshold and assigned approver in the editor.']
        : []),
      'All AI and tool steps use simulated data. Review the included prompts and configuration before running.',
    ],
  };
}

export function createBlankWorkflow(): Workflow {
  const now = new Date().toISOString();
  return {
    id: uid('wf'),
    name: 'Untitled workflow',
    description: 'A new workflow, ready for your next idea.',
    status: 'draft',
    version: 1,
    nodes: [createNode('manual', { x: 280, y: 100 })],
    edges: [],
    createdAt: now,
    updatedAt: now,
    totalRuns: 0,
    successRate: 0,
    icon: 'workflow',
  };
}
