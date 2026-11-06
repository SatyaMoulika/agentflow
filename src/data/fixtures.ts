import type {
  Approval,
  Execution,
  ExecutionEvent,
  Integration,
  NodeRun,
  NodeType,
  Settings,
  Workflow,
  WorkflowEdge,
  WorkflowNode,
} from '../types';
import { nodeRegistry } from '../lib/node-registry';
const ago = (minutes: number) => new Date(Date.now() - minutes * 60000).toISOString();
const node = (
  id: string,
  type: NodeType,
  label: string,
  x: number,
  y = 150,
  config: WorkflowNode['config'] = {},
): WorkflowNode => ({
  id,
  type,
  label,
  position: { x, y },
  config: { ...nodeRegistry[type].defaultConfig, ...config },
});
const edge = (source: string, target: string, sourceHandle?: string): WorkflowEdge => ({
  id: `${source}-${target}`,
  source,
  target,
  sourceHandle,
});
const base = (
  id: string,
  name: string,
  description: string,
  status: Workflow['status'],
  icon: string,
  nodes: WorkflowNode[],
  edges: WorkflowEdge[],
): Workflow => ({
  id,
  name,
  description,
  status,
  icon,
  nodes,
  edges,
  version: 1,
  createdAt: ago(64800),
  updatedAt: ago(36),
  totalRuns: 0,
  successRate: 0,
});
export const fixtureWorkflows: Workflow[] = [
  base(
    'wf_invoice',
    'Invoice Approval Automation',
    'From inbox to approval. Extract invoice data and keep your payments moving.',
    'active',
    'invoice',
    [
      node('invoice_trigger', 'manual', 'Invoice received', 0),
      node('invoice_extract', 'extract', 'Extract invoice details', 300),
      node('invoice_validate', 'transform', 'Validate invoice', 600),
      node('invoice_condition', 'condition', 'Amount exceeds ₹50,000?', 900),
      node('invoice_approve', 'approval', 'Finance approval', 1200, 30),
      node('invoice_store', 'http', 'Save invoice', 1500),
      node('invoice_end', 'end', 'Workflow complete', 1800),
      node('invoice_reject', 'end', 'Payment declined', 1500, 380),
    ],
    [
      edge('invoice_trigger', 'invoice_extract'),
      edge('invoice_extract', 'invoice_validate'),
      edge('invoice_validate', 'invoice_condition'),
      edge('invoice_condition', 'invoice_approve', 'true'),
      edge('invoice_condition', 'invoice_store', 'false'),
      edge('invoice_approve', 'invoice_store', 'approved'),
      edge('invoice_approve', 'invoice_reject', 'rejected'),
      edge('invoice_store', 'invoice_end'),
    ],
  ),
  base(
    'wf_email',
    'AI Email Classification',
    'Give every message a home. Automatically categorize and route incoming emails.',
    'active',
    'email',
    [
      node('email_trigger', 'manual', 'New email', 0),
      node('email_classify', 'classify', 'Classify email', 300),
      node('email_route', 'condition', 'Urgent message?', 600, 150, {
        variable: 'priority',
        operator: 'equals',
        value: 'high',
      }),
      node('email_send', 'http', 'Send to team inbox', 900),
      node('email_end', 'end', 'Done', 1200),
    ],
    [
      edge('email_trigger', 'email_classify'),
      edge('email_classify', 'email_route'),
      edge('email_route', 'email_send', 'true'),
      edge('email_route', 'email_end', 'false'),
      edge('email_send', 'email_end'),
    ],
  ),
  base(
    'wf_support',
    'Customer Support Ticket Routing',
    'Get customers to the right people with intelligent ticket triage.',
    'active',
    'support',
    [
      node('support_trigger', 'manual', 'Ticket received', 0),
      node('support_agent', 'agent', 'Analyze support ticket', 300),
      node('support_classify', 'classify', 'Assign department', 600),
      node('support_send', 'http', 'Route to support', 900),
      node('support_end', 'end', 'Done', 1200),
    ],
    [
      edge('support_trigger', 'support_agent'),
      edge('support_agent', 'support_classify'),
      edge('support_classify', 'support_send'),
      edge('support_send', 'support_end'),
    ],
  ),
  base(
    'wf_document',
    'Document Summarization Pipeline',
    'Turn lengthy documents into clear, actionable summaries in seconds.',
    'draft',
    'document',
    [
      node('doc_trigger', 'manual', 'Document uploaded', 0),
      node('doc_parse', 'parser', 'Parse document', 300),
      node('doc_llm', 'llm', 'Generate summary', 600),
      node('doc_end', 'end', 'Summary ready', 900),
    ],
    [edge('doc_trigger', 'doc_parse'), edge('doc_parse', 'doc_llm'), edge('doc_llm', 'doc_end')],
  ),
  base(
    'wf_lead',
    'Lead Qualification Agent',
    'Research, score, and qualify leads so your team can focus on the right ones.',
    'active',
    'lead',
    [
      node('lead_trigger', 'manual', 'New lead', 0),
      node('lead_agent', 'agent', 'Qualify lead', 300),
      node('lead_score', 'transform', 'Normalize lead score', 600),
      node('lead_send', 'http', 'Update CRM', 900),
      node('lead_end', 'end', 'Done', 1200),
    ],
    [
      edge('lead_trigger', 'lead_agent'),
      edge('lead_agent', 'lead_score'),
      edge('lead_score', 'lead_send'),
      edge('lead_send', 'lead_end'),
    ],
  ),
  base(
    'wf_report',
    'Daily Report Generator',
    'Your daily performance pulse, collected and summarized automatically.',
    'paused',
    'report',
    [
      node('report_trigger', 'manual', 'Start daily report', 0),
      node('report_http', 'http', 'Fetch performance data', 300),
      node('report_llm', 'llm', 'Write daily report', 600),
      node('report_end', 'end', 'Report ready', 900),
    ],
    [
      edge('report_trigger', 'report_http'),
      edge('report_http', 'report_llm'),
      edge('report_llm', 'report_end'),
    ],
  ),
];
export const demoInput = {
  invoice_number: 'INV-2026-1042',
  vendor: 'Acme Technologies',
  amount: 60000,
  currency: 'INR',
  document: 'invoice_october.pdf',
};
const fixtureInput = (index: number): Record<string, unknown> => ({
  ...demoInput,
  ...(index === 6
    ? { invoice_number: 'INV-2026-1038', amount: 54000 }
    : index === 12
      ? { invoice_number: 'INV-2026-1029', amount: 92000 }
      : index === 18
        ? { invoice_number: 'INV-2026-1021', amount: 40000 }
        : index === 24
          ? { invoice_number: 'INV-2026-1015', amount: 65000 }
          : {}),
});
const fixtureCondition = (node: WorkflowNode, input: Record<string, unknown>) => {
  const left = input[node.config.variable || 'amount'];
  const right = node.config.value || '50000';
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
      return String(left).includes(right);
    default:
      return Number(left) > Number(right);
  }
};
export function makeFixtureExecutions(): Execution[] {
  return Array.from({ length: 36 }, (_, i) => {
    const workflow = fixtureWorkflows[i % 6];
    const status: Execution['status'] =
      i === 0
        ? 'waiting_approval'
        : [8, 20, 29].includes(i)
          ? 'failed'
          : [16, 24].includes(i)
            ? 'cancelled'
            : 'succeeded';
    // The most recent five runs are today; the remainder cover the previous month.
    const startedAt = ago(i < 5 ? [2, 5, 19, 47, 105][i] : (i - 4) * 1440 + 53);
    const nodeRuns: NodeRun[] = workflow.nodes.map((n) => ({
      nodeId: n.id,
      status: 'pending',
      duration: 0,
      input: {},
      output: null,
    }));
    let clock = new Date(startedAt).getTime();
    let duration = 0;
    let steps = 0;
    let data = fixtureInput(i);
    const events: ExecutionEvent[] = [
      {
        id: `ev_${i}_0`,
        timestamp: startedAt,
        message: 'Demo workflow execution started. No external services were called.',
        level: 'info',
      },
    ];
    const event = (message: string, nodeId?: string, level: ExecutionEvent['level'] = 'info') =>
      events.push({
        id: `ev_${i}_${events.length}`,
        timestamp: new Date(clock).toISOString(),
        message,
        nodeId,
        level,
      });
    const queue = workflow.nodes
      .filter((n) => ['manual', 'webhook', 'schedule'].includes(n.type))
      .map((n) => n.id);
    const visited = new Set<string>();
    while (queue.length) {
      const id = queue.shift()!;
      if (visited.has(id)) continue;
      visited.add(id);
      const node = workflow.nodes.find((n) => n.id === id)!;
      const run = nodeRuns.find((n) => n.nodeId === id)!;
      if (status === 'cancelled' && i !== 24 && steps === 1) break;
      run.startedAt = new Date(clock).toISOString();
      run.attempt = 1;
      run.retryCount = 0;
      run.input = { ...data };
      event(`${node.label} started`, id);
      if (node.type === 'approval' && status === 'waiting_approval') {
        run.status = 'waiting_approval';
        event('Approval requested. Demo execution paused for your decision.', id, 'warn');
        break;
      }
      if (node.type === 'approval' && i === 24) {
        event('Approval requested. Demo execution paused for your decision.', id, 'warn');
        clock += 60000;
        run.status = 'skipped';
        run.endedAt = new Date(clock).toISOString();
        event('Approval expired after the simulated execution was cancelled.', id, 'warn');
        break;
      }
      const ai = ['extract', 'llm', 'classify', 'agent'].includes(node.type);
      if (i === 10 && ai) {
        run.attempt = 2;
        run.retryCount = 1;
        event('Demo transient provider limit; retry 1 started successfully.', id, 'warn');
      }
      run.duration = ai
        ? 650 + ((i * 47 + steps * 113) % 1200)
        : node.type === 'http'
          ? 220 + ((i * 31) % 400)
          : 60 + ((i * 11 + steps * 17) % 140);
      if (status === 'failed' && steps === 2) {
        run.status = 'failed';
        run.duration = 30000;
        run.error = 'Demo provider timeout: the request exceeded the configured 30 second limit.';
        clock += run.duration;
        duration += run.duration;
        run.endedAt = new Date(clock).toISOString();
        event(run.error, id, 'error');
        break;
      }
      run.status = 'succeeded';
      clock += run.duration;
      duration += run.duration;
      run.endedAt = new Date(clock).toISOString();
      const output: Record<string, unknown> = {
        ...data,
        result: 'Processed successfully (simulation)',
      };
      if (node.type === 'condition') output.matched = fixtureCondition(node, data);
      if (node.type === 'classify') {
        output.category = 'billing';
        output.priority = 'normal';
      }
      if (node.type === 'llm')
        output.summary =
          'Demo summary: workflow performance is healthy. Review outstanding approvals and retry failed provider requests.';
      if (node.type === 'approval') {
        output.decision = i === 12 ? 'rejected' : 'approved';
        output.approvedBy = 'Moulika';
        if (i === 12) output.comment = 'Duplicate invoice; payment not authorized.';
      }
      run.output = output;
      if (ai) run.tokens = { input: 840 + steps * 92, output: 196 + steps * 18 };
      event(`${node.label} completed in ${run.duration}ms`, id);
      if (node.type === 'approval')
        event(`Human decision: ${output.decision}. Demo execution resumed.`, id);
      const branch =
        node.type === 'condition'
          ? output.matched
            ? 'true'
            : 'false'
          : node.type === 'approval'
            ? String(output.decision)
            : undefined;
      queue.push(
        ...workflow.edges
          .filter((edge) => edge.source === id && (!branch || edge.sourceHandle === branch))
          .map((edge) => edge.target),
      );
      data = output;
      steps++;
    }
    if (status !== 'waiting_approval')
      nodeRuns.forEach((run) => {
        if (run.status === 'pending') run.status = 'skipped';
      });
    if (status === 'succeeded') event('Demo execution completed successfully');
    if (status === 'cancelled') event('Demo execution cancelled by user', undefined, 'warn');
    if (status === 'failed')
      event('Demo execution stopped after a step failed', undefined, 'error');
    return {
      id: `exec_${(1048 - i).toString(16)}a${i.toString().padStart(3, '0')}`,
      workflowId: workflow.id,
      workflowName: workflow.name,
      version: 1,
      status,
      startedAt,
      duration,
      trigger: i % 3 === 0 ? 'Manual' : 'Demo event',
      traceId: `trace_${(1048 - i).toString(16)}b42e96a38c714e9`,
      graph: structuredClone(workflow),
      nodeRuns,
      events,
    };
  });
}
export const fixtureExecutions = makeFixtureExecutions();
for (const w of fixtureWorkflows) {
  const runs = fixtureExecutions.filter((e) => e.workflowId === w.id);
  w.totalRuns = runs.length;
  w.successRate = Math.round(
    (runs.filter((e) => e.status === 'succeeded').length / runs.length) * 100,
  );
  w.lastRun = runs[0]?.startedAt;
}
export const fixtureApprovals: Approval[] = fixtureExecutions.flatMap((execution) => {
  const run = execution.nodeRuns.find(
    (run) =>
      execution.graph.nodes.find((node) => node.id === run.nodeId)?.type === 'approval' &&
      run.startedAt,
  );
  if (!run) return [];
  const status: Approval['status'] =
    run.status === 'waiting_approval'
      ? 'pending'
      : execution.status === 'cancelled'
        ? 'expired'
        : run.output?.decision === 'rejected'
          ? 'rejected'
          : 'approved';
  return [
    {
      id:
        status === 'pending'
          ? 'approval_invoice'
          : status === 'rejected'
            ? 'approval_rejected'
            : status === 'expired'
              ? 'approval_expired'
              : execution.id === fixtureExecutions[6].id
                ? 'approval_previous'
                : `approval_${execution.id}`,
      executionId: execution.id,
      workflowId: execution.workflowId,
      workflowName: execution.workflowName,
      nodeId: run.nodeId,
      title: status === 'rejected' ? 'Duplicate invoice review' : 'Invoice payment approval',
      description:
        status === 'rejected'
          ? 'Duplicate invoice flagged during finance review.'
          : `Review a payment of ₹${Number(run.input.amount).toLocaleString('en-IN')} to ${run.input.vendor} before the invoice is saved.`,
      requestedAt: run.startedAt!,
      status,
      risk: status === 'rejected' ? 'high' : status === 'approved' ? 'low' : 'medium',
      data: { ...run.input },
      decisionAt: status === 'pending' ? undefined : run.endedAt,
      comment:
        status === 'rejected'
          ? 'Duplicate invoice; payment not authorized.'
          : status === 'expired'
            ? 'The linked simulated execution was cancelled.'
            : undefined,
    },
  ];
});
export const fixtureIntegrations: Integration[] = [
  {
    id: 'gmail',
    name: 'Gmail',
    description: 'Read, classify, and send emails from your workflows.',
    category: 'Communication',
    icon: 'mail',
    color: '#ea4335',
    connected: true,
    connectionName: 'Team inbox (demo)',
  },
  {
    id: 'sheets',
    name: 'Google Sheets',
    description: 'Turn your spreadsheets into connected, automated data.',
    category: 'Productivity',
    icon: 'sheet',
    color: '#16a34a',
    connected: true,
    connectionName: 'Operations (demo)',
  },
  {
    id: 'drive',
    name: 'Google Drive',
    description: 'Find, read, and organize documents in one place.',
    category: 'Storage',
    icon: 'drive',
    color: '#eab308',
    connected: false,
  },
  {
    id: 'slack',
    name: 'Slack',
    description: 'Keep your team in the loop with timely notifications.',
    category: 'Communication',
    icon: 'slack',
    color: '#8b5cf6',
    connected: true,
    connectionName: 'AgentFlow workspace (demo)',
  },
  {
    id: 'webhooks',
    name: 'Webhooks',
    description: 'Trigger workflows from events in your favorite tools.',
    category: 'Developer Tools',
    icon: 'webhook',
    color: '#ec4899',
    connected: false,
  },
  {
    id: 'http',
    name: 'HTTP API',
    description: 'Connect any REST endpoint to your workflow.',
    category: 'Developer Tools',
    icon: 'globe',
    color: '#3b82f6',
    connected: true,
    connectionName: 'Demo API',
  },
  {
    id: 'postgres',
    name: 'PostgreSQL',
    description: 'Query and write structured data with confidence.',
    category: 'Storage',
    icon: 'database',
    color: '#0284c7',
    connected: false,
  },
  {
    id: 'openai',
    name: 'OpenAI-compatible LLM',
    description: 'Add intelligence with your preferred language model.',
    category: 'AI Providers',
    icon: 'sparkles',
    color: '#0d9488',
    connected: true,
    connectionName: 'Demo AI provider',
  },
];
export const defaultSettings: Settings = {
  name: 'Moulika',
  email: 'moulika@example.com',
  theme: 'light',
  model: 'gpt-4.1-mini',
  temperature: 0.3,
  maxSteps: 25,
  timeout: 60,
  retries: 2,
  concurrency: 5,
  tracing: true,
  retention: '30 days',
  logLevel: 'info',
  redaction: true,
  notifyFailure: true,
  notifyApproval: true,
  notifyCompletion: false,
};
