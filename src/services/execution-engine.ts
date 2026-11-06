import type { Approval, Execution, Workflow, WorkflowNode } from '../types';
import { demoInput } from '../data/fixtures';
import { sleep, uid } from '../lib/utils';

/** The UI can later consume an SSE adapter with the same typed event/state boundary. */
export interface SimulationAdapter {
  getExecution: (id: string) => Execution | undefined;
  updateExecution: (id: string, update: Partial<Execution>) => void;
  requestApproval: (approval: Approval) => void;
}

export function evaluateCondition(node: WorkflowNode, data: Record<string, unknown>): boolean {
  const left = (node.config.variable || 'amount')
    .split('.')
    .reduce<unknown>(
      (value, key) =>
        value && typeof value === 'object' ? (value as Record<string, unknown>)[key] : undefined,
      data,
    );
  const right = node.config.value || '';
  switch (node.config.operator) {
    case 'equals':
    case '==':
    case '===':
      return String(left) === right;
    case 'not_equals':
      return String(left) !== right;
    case 'less_than':
    case '<':
      return Number(left) < Number(right);
    case 'contains':
      return String(left ?? '').includes(right);
    case 'greater_than':
    case '>':
      return Number(left) > Number(right);
    default:
      return false;
  }
}

function triggerData(workflow: Workflow): Record<string, unknown> {
  if (/csv/i.test(workflow.name))
    return {
      file: 'performance_october.csv',
      records: 42,
      revenue: 168000,
      currency: 'INR',
      missing_values: 2,
    };
  switch (workflow.icon) {
    case 'email':
      return {
        from: 'customer@example.com',
        subject: 'Question about my October invoice',
        body: 'Could you help me understand the invoice charges?',
        received_at: new Date().toISOString(),
      };
    case 'support':
      return {
        ticket_id: 'SUP-2041',
        subject: 'Unable to access my workspace',
        message: 'Please help me restore access to my demo workspace.',
        customer: 'Jamie Chen',
        priority: 'normal',
      };
    case 'document':
      return {
        document: 'quarterly_review.pdf',
        pages: 12,
        text: 'The team completed 42 projects this quarter. Revenue grew by 18% and support response times improved.',
      };
    case 'lead':
      return {
        lead_id: 'LEAD-204',
        company: 'Acme Technologies',
        email: 'team@example.com',
        team_size: 35,
        interest: 'Workflow automation',
      };
    case 'report':
      return {
        period: 'Last 24 hours',
        completed: 42,
        failed: 2,
        revenue: 168000,
        currency: 'INR',
      };
    default:
      return { ...demoInput };
  }
}

function mockOutput(node: WorkflowNode, input: Record<string, unknown>): Record<string, unknown> {
  const output = { ...input, result: 'Processed successfully (simulation)' };
  switch (node.type) {
    case 'condition':
      return { ...output, matched: evaluateCondition(node, input) };
    case 'classify':
      return { ...output, category: 'billing', priority: 'normal', confidence: 0.94 };
    case 'extract':
      return { ...output, ...demoInput };
    case 'llm':
      return {
        ...output,
        summary:
          'Demo summary: the supplied information has been reviewed. Follow up on the requested action and keep the relevant team informed.',
      };
    case 'agent':
      return {
        ...output,
        recommendation: 'Route this item to the appropriate team for follow-up.',
        score: 84,
      };
    case 'http':
      return { ...output, status_code: 200, simulated: true, destination: node.config.url };
    case 'parser':
      return { ...output, parsed: true, format: 'structured-text' };
    case 'calculator': {
      // Deliberately bounded: no eval or arbitrary JavaScript execution.
      const match = node.config.expression?.match(
        /^\s*(-?\d+(?:\.\d+)?)\s*([+*/-])\s*(-?\d+(?:\.\d+)?)\s*$/,
      );
      if (!match)
        throw new Error(
          'The demo calculator supports two numbers and one operator (+, -, *, /). Edit the expression and retry.',
        );
      const a = Number(match[1]),
        b = Number(match[3]);
      const value =
        match[2] === '+' ? a + b : match[2] === '-' ? a - b : match[2] === '*' ? a * b : a / b;
      if (!Number.isFinite(value))
        throw new Error('The calculator result is not finite. Check for division by zero.');
      return { ...output, value };
    }
    default:
      return output;
  }
}

const workers = new Set<string>();
const terminal = (execution: Execution | undefined) =>
  !execution || ['cancelled', 'failed', 'succeeded'].includes(execution.status);

/** Traverses a validated DAG and simulates only the selected branches. Never calls a provider. */
export async function simulateExecution(id: string, adapter: SimulationAdapter): Promise<void> {
  if (workers.has(id)) return;
  workers.add(id);
  const event = (message: string, nodeId?: string, level: 'info' | 'warn' | 'error' = 'info') => {
    const execution = adapter.getExecution(id);
    if (execution)
      adapter.updateExecution(id, {
        events: [
          ...execution.events,
          { id: uid('event'), timestamp: new Date().toISOString(), message, nodeId, level },
        ],
      });
  };
  try {
    const initial = adapter.getExecution(id);
    if (terminal(initial) || !initial || initial.status === 'waiting_approval') return;
    const roots = initial.graph.nodes.filter((node) => node.type === 'manual');
    if (
      roots.length !== 1 ||
      initial.graph.nodes.some((node) => ['webhook', 'schedule'].includes(node.type))
    ) {
      adapter.updateExecution(id, {
        status: 'failed',
        nodeRuns: initial.nodeRuns.map((run) => ({ ...run, status: 'skipped' })),
      });
      event(
        'This demo requires exactly one manual trigger. Webhook and schedule triggers are coming soon.',
        undefined,
        'error',
      );
      return;
    }
    const queue = roots.map((node) => node.id);
    const visited = new Set<string>();
    while (queue.length) {
      const nodeId = queue.shift()!;
      if (visited.has(nodeId)) continue;
      visited.add(nodeId);
      let execution = adapter.getExecution(id);
      if (terminal(execution) || !execution) return;
      const node = execution.graph.nodes.find((node) => node.id === nodeId);
      const run = execution.nodeRuns.find((item) => item.nodeId === nodeId);
      if (!node || !run) continue;
      const enqueueOutputs = () => {
        const fresh = adapter.getExecution(id)!;
        const result = fresh.nodeRuns.find((item) => item.nodeId === nodeId)!;
        let edges = fresh.graph.edges.filter((edge) => edge.source === nodeId);
        if (node.type === 'condition')
          edges = edges.filter(
            (edge) =>
              edge.sourceHandle === (evaluateCondition(node, result.input) ? 'true' : 'false'),
          );
        if (node.type === 'approval')
          edges = edges.filter(
            (edge) => edge.sourceHandle === (result.output?.decision || 'approved'),
          );
        queue.push(...edges.map((edge) => edge.target));
      };
      if (run.status === 'succeeded') {
        enqueueOutputs();
        continue;
      }
      const predecessors = execution.graph.edges
        .filter((edge) => edge.target === nodeId)
        .map((edge) => execution!.nodeRuns.find((item) => item.nodeId === edge.source))
        .filter((item) => item?.status === 'succeeded');
      const input = predecessors.length
        ? (Object.assign({}, ...predecessors.map((item) => item?.output || {})) as Record<
            string,
            unknown
          >)
        : triggerData(execution.graph);
      const startedAt = new Date().toISOString();
      adapter.updateExecution(id, {
        status: 'running',
        nodeRuns: execution.nodeRuns.map((item) =>
          item.nodeId === nodeId
            ? { ...item, status: 'running', attempt: 1, retryCount: 0, startedAt, input }
            : item,
        ),
      });
      event(`${node.label} started`, nodeId);
      await sleep(
        node.type === 'manual'
          ? 350
          : ['extract', 'llm', 'classify', 'agent'].includes(node.type)
            ? 1100
            : 650,
      );
      execution = adapter.getExecution(id);
      if (terminal(execution) || !execution) return;
      if (node.type === 'approval') {
        adapter.updateExecution(id, {
          status: 'waiting_approval',
          nodeRuns: execution.nodeRuns.map((item) =>
            item.nodeId === nodeId ? { ...item, status: 'waiting_approval' } : item,
          ),
        });
        event('Approval requested. Demo execution paused for your decision.', nodeId, 'warn');
        adapter.requestApproval({
          id: uid('approval'),
          executionId: id,
          workflowId: execution.workflowId,
          workflowName: execution.workflowName,
          nodeId,
          title: node.config.title || 'Review workflow action',
          description:
            node.config.description || 'Review this demo action before the workflow continues.',
          requestedAt: startedAt,
          status: 'pending',
          risk: 'medium',
          data: input,
        });
        return;
      }
      const duration =
        node.type === 'manual'
          ? 120
          : ['extract', 'llm', 'classify', 'agent'].includes(node.type)
            ? 890
            : node.type === 'http'
              ? 420
              : 42;
      let output: Record<string, unknown>;
      try {
        output = mockOutput(node, input);
      } catch (error) {
        const message =
          error instanceof Error ? error.message : 'This simulated step could not be completed.';
        adapter.updateExecution(id, {
          status: 'failed',
          duration: execution.duration + duration,
          nodeRuns: execution.nodeRuns.map((item) =>
            item.nodeId === nodeId
              ? {
                  ...item,
                  status: 'failed',
                  error: message,
                  duration,
                  endedAt: new Date().toISOString(),
                }
              : item.status === 'pending'
                ? { ...item, status: 'skipped' }
                : item,
          ),
        });
        event(message, nodeId, 'error');
        return;
      }
      adapter.updateExecution(id, {
        duration: execution.duration + duration,
        nodeRuns: execution.nodeRuns.map((item) =>
          item.nodeId === nodeId
            ? {
                ...item,
                status: 'succeeded',
                duration,
                endedAt: new Date().toISOString(),
                output,
                tokens: ['extract', 'llm', 'classify', 'agent'].includes(node.type)
                  ? { input: 1128, output: 286 }
                  : undefined,
              }
            : item,
        ),
      });
      event(`${node.label} completed in ${duration}ms`, nodeId);
      enqueueOutputs();
    }
    const execution = adapter.getExecution(id);
    if (execution?.status === 'running') {
      adapter.updateExecution(id, {
        status: 'succeeded',
        nodeRuns: execution.nodeRuns.map((item) =>
          item.status === 'pending' ? { ...item, status: 'skipped' } : item,
        ),
      });
      event('Demo execution completed successfully');
    }
  } finally {
    workers.delete(id);
  }
}
