import type { Definition } from './types';
import { starterDefinition } from './graph';
export type StarterKind = 'calculator' | 'github';
export function starterWorkflow(kind: StarterKind, connectionId = '') {
  if (kind === 'github' && !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(connectionId))
    throw new Error('Choose an active GitHub connection first.');
  const definition = starterDefinition();
  definition.nodes[1].position = { x: 580, y: 130 };
  definition.nodes.splice(
    1,
    0,
    kind === 'github'
      ? {
          id: 'brief',
          type: 'agent',
          label: 'Read and brief',
          position: { x: 300, y: 130 },
          config: {
            instruction:
              'Fetch the selected GitHub connection and produce a concise briefing based only on the returned data. Include issue or PR numbers and links where available. Explain that collection results may cover only the first page; do not claim completeness. Do not post comments, change labels or write to GitHub.',
            input_field: 'request',
            max_tool_rounds: 3,
            connection_ids: [connectionId],
            pause_after_tools: false,
          },
        }
      : {
          id: 'double',
          type: 'calculator',
          label: 'Double the amount',
          position: { x: 300, y: 130 },
          config: {
            operation: 'multiply',
            operands: [
              { kind: 'output', path: '$.start.output.amount' },
              { kind: 'literal', value: 2 },
            ],
          },
        },
  );
  const middle = kind === 'github' ? 'brief' : 'double';
  definition.edges = [
    { id: 'start_step', source: 'start', target: middle, source_handle: 'default' },
    { id: 'step_finish', source: middle, target: 'finish', source_handle: 'default' },
  ];
  definition.metadata = {
    agentflow_input_fields:
      kind === 'github'
        ? [{ name: 'request', label: 'What would you like to know?', type: 'text', required: true }]
        : [{ name: 'amount', label: 'Amount to double', type: 'number', required: true }],
  };
  return {
    name: kind === 'github' ? 'GitHub briefing' : 'My first calculation',
    description:
      kind === 'github'
        ? 'Read a selected repository connection and prepare a briefing for review. No GitHub changes.'
        : 'Enter an amount and multiply it by two. No AI provider or external connection required.',
    definition,
  };
}
export function setupIssues(definition: Definition): string[] {
  const issues: string[] = [];
  if (!definition.nodes.some((n) => n.type === 'manual')) issues.push('Add a manual start.');
  if (!definition.nodes.some((n) => n.type === 'end')) issues.push('Add an end step.');
  for (const node of definition.nodes) {
    const title = node.label || node.id;
    if (['http', 'gmail_read'].includes(node.type) && !node.config.connection_id)
      issues.push(`${title}: select a connection.`);
    if (
      ['groq', 'agent'].includes(node.type) &&
      (typeof node.config.instruction !== 'string' || !node.config.instruction.trim())
    )
      issues.push(`${title}: write instructions.`);
    if (
      ['groq', 'agent', 'json_parser', 'classify', 'extract'].includes(node.type) &&
      (typeof node.config.input_field !== 'string' || !node.config.input_field.trim())
    )
      issues.push(`${title}: choose the input field.`);
  }
  return issues;
}
export function isGitHubReadEndpoint(endpoint: string) {
  return /^https:\/\/api\.github\.com\/repos\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/(issues|pulls)$/.test(
    endpoint,
  );
}
