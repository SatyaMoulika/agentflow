import type { Workflow, WorkflowNode } from '../types';
import { nodeRegistry } from './node-registry';

export interface ValidationIssue {
  nodeId?: string;
  field?: string;
  message: string;
}

export function validateNode(node: WorkflowNode): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const requireField = (field: keyof WorkflowNode['config'], label: string) => {
    if (!String(node.config[field] ?? '').trim())
      issues.push({ nodeId: node.id, field, message: `${node.label}: ${label} is required.` });
  };
  if (!node.label.trim())
    issues.push({ nodeId: node.id, field: 'label', message: 'Give this node a name.' });
  if (['llm', 'classify', 'extract', 'agent'].includes(node.type)) {
    requireField('model', 'Model');
    requireField('prompt', 'Prompt');
  }
  if (node.type === 'condition') {
    requireField('variable', 'Input variable');
    requireField('operator', 'Operator');
    requireField('value', 'Comparison value');
  }
  if (node.type === 'http') {
    requireField('url', 'Request URL');
    if (node.config.url && !/^https?:\/\/[^\s]+$/i.test(node.config.url))
      issues.push({
        nodeId: node.id,
        field: 'url',
        message: `${node.label}: enter an http:// or https:// URL.`,
      });
    for (const field of ['headers', 'body'] as const) {
      const value = node.config[field]?.trim();
      if (value && !value.includes('{{')) {
        try {
          JSON.parse(value);
        } catch {
          issues.push({
            nodeId: node.id,
            field,
            message: `${node.label}: ${field} must be valid JSON.`,
          });
        }
      }
    }
  }
  if (node.type === 'approval') {
    requireField('title', 'Approval title');
    requireField('approver', 'Assigned approver');
  }
  if (node.type === 'transform' || node.type === 'calculator')
    requireField('expression', 'Expression');
  if (
    node.config.temperature !== undefined &&
    (node.config.temperature < 0 || node.config.temperature > 2)
  )
    issues.push({
      nodeId: node.id,
      field: 'temperature',
      message: `${node.label}: temperature must be between 0 and 2.`,
    });
  if (node.config.maxTokens !== undefined && node.config.maxTokens < 1)
    issues.push({
      nodeId: node.id,
      field: 'maxTokens',
      message: `${node.label}: maximum tokens must be positive.`,
    });
  if (node.config.timeout !== undefined && node.config.timeout < 1)
    issues.push({
      nodeId: node.id,
      field: 'timeout',
      message: `${node.label}: timeout must be positive.`,
    });
  if (node.config.retries !== undefined && (node.config.retries < 0 || node.config.retries > 10))
    issues.push({
      nodeId: node.id,
      field: 'retries',
      message: `${node.label}: retries must be between 0 and 10.`,
    });
  if (node.config.outputSchema?.trim()) {
    try {
      JSON.parse(node.config.outputSchema);
    } catch {
      issues.push({
        nodeId: node.id,
        field: 'outputSchema',
        message: `${node.label}: output schema must be valid JSON.`,
      });
    }
  }
  const parsed = nodeRegistry[node.type].configSchema.safeParse(node.config);
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const field = String(issue.path[0] || 'config');
      if (!issues.some((existing) => existing.field === field))
        issues.push({ nodeId: node.id, field, message: `${node.label}: ${issue.message}` });
    }
  }
  if (nodeRegistry[node.type].comingSoon)
    issues.push({
      nodeId: node.id,
      message: `${node.label}: this trigger is coming soon. Use a manual trigger for the demo.`,
    });
  return issues;
}

export function canConnect(
  workflow: Workflow,
  connection: { source: string; target: string; sourceHandle?: string | null },
): boolean {
  const { source, target } = connection;
  if (source === target) return false;
  const from = workflow.nodes.find((node) => node.id === source);
  const to = workflow.nodes.find((node) => node.id === target);
  if (!from || !to || from.type === 'end' || ['manual', 'webhook', 'schedule'].includes(to.type))
    return false;
  const handle = connection.sourceHandle || 'default';
  const allowed =
    from.type === 'condition'
      ? ['true', 'false']
      : from.type === 'approval'
        ? ['approved', 'rejected']
        : ['default'];
  if (!allowed.includes(handle)) return false;
  if (
    workflow.edges.some(
      (edge) => edge.source === source && (edge.sourceHandle || 'default') === handle,
    )
  )
    return false;
  const visited = new Set<string>();
  const reachesSource = (id: string): boolean => {
    if (id === source) return true;
    if (visited.has(id)) return false;
    visited.add(id);
    return workflow.edges
      .filter((edge) => edge.source === id)
      .some((edge) => reachesSource(edge.target));
  };
  return !reachesSource(target);
}

export function validateWorkflow(workflow: Workflow): ValidationIssue[] {
  const issues = workflow.nodes.flatMap(validateNode);
  if (!workflow.name.trim()) issues.push({ field: 'name', message: 'Give your workflow a name.' });
  const starts = workflow.nodes.filter((node) =>
    ['manual', 'webhook', 'schedule'].includes(node.type),
  );
  if (starts.length !== 1) issues.push({ message: 'A workflow needs exactly one trigger.' });
  if (!workflow.nodes.some((node) => node.type === 'end'))
    issues.push({ message: 'Add an End node to finish the workflow.' });
  const ids = new Set(workflow.nodes.map((node) => node.id));
  if (ids.size !== workflow.nodes.length)
    issues.push({ message: 'Each node must have a unique ID.' });
  if (new Set(workflow.edges.map((edge) => edge.id)).size !== workflow.edges.length)
    issues.push({ message: 'Each connection must have a unique ID.' });
  const visited = new Set<string>();
  const visiting = new Set<string>();
  let cyclic = false;
  const visit = (id: string) => {
    if (visiting.has(id)) {
      cyclic = true;
      return;
    }
    if (visited.has(id)) return;
    visiting.add(id);
    workflow.edges.filter((edge) => edge.source === id).forEach((edge) => visit(edge.target));
    visiting.delete(id);
    visited.add(id);
  };
  workflow.nodes.forEach((node) => visit(node.id));
  if (cyclic)
    issues.push({
      message: 'This graph contains a cycle. Remove a connection to create a one-way flow.',
    });
  workflow.edges.forEach((edge) => {
    if (!ids.has(edge.source) || !ids.has(edge.target))
      issues.push({ message: 'A connection points to a missing node. Remove that connection.' });
    const source = workflow.nodes.find((node) => node.id === edge.source);
    const target = workflow.nodes.find((node) => node.id === edge.target);
    if (source?.type === 'end')
      issues.push({
        nodeId: source.id,
        message: `${source.label}: End nodes cannot have outgoing connections.`,
      });
    if (target && ['manual', 'webhook', 'schedule'].includes(target.type))
      issues.push({
        nodeId: target.id,
        message: `${target.label}: triggers cannot have incoming connections.`,
      });
    const handle = edge.sourceHandle || 'default';
    const allowed =
      source?.type === 'condition'
        ? ['true', 'false']
        : source?.type === 'approval'
          ? ['approved', 'rejected']
          : ['default'];
    if (source && !allowed.includes(handle))
      issues.push({
        nodeId: source.id,
        message: `${source.label}: this connection uses an invalid output branch.`,
      });
    if (
      workflow.edges.find(
        (item) => item.source === edge.source && (item.sourceHandle || 'default') === handle,
      )?.id !== edge.id
    )
      issues.push({
        nodeId: source?.id,
        message: `${source?.label || 'Node'}: each output can connect to one next step. Use a condition to branch.`,
      });
  });
  const reachable = new Set<string>();
  const reach = (id: string) => {
    if (reachable.has(id)) return;
    reachable.add(id);
    workflow.edges.filter((edge) => edge.source === id).forEach((edge) => reach(edge.target));
  };
  starts.forEach((node) => reach(node.id));
  workflow.nodes.forEach((node) => {
    if (!reachable.has(node.id))
      issues.push({ nodeId: node.id, message: `${node.label}: connect this node to the trigger.` });
    if (node.type !== 'end' && !workflow.edges.some((edge) => edge.source === node.id))
      issues.push({
        nodeId: node.id,
        message: `${node.label}: connect its output to the next step.`,
      });
    if (node.type === 'condition') {
      ['true', 'false'].forEach((branch) => {
        if (!workflow.edges.some((edge) => edge.source === node.id && edge.sourceHandle === branch))
          issues.push({ nodeId: node.id, message: `${node.label}: connect the ${branch} branch.` });
      });
    }
    if (node.type === 'approval') {
      ['approved', 'rejected'].forEach((branch) => {
        if (!workflow.edges.some((edge) => edge.source === node.id && edge.sourceHandle === branch))
          issues.push({ nodeId: node.id, message: `${node.label}: connect the ${branch} branch.` });
      });
    }
  });
  return issues;
}

export function autoLayout(workflow: Workflow): Workflow {
  const levels = new Map<string, number>();
  const degrees = new Map(
    workflow.nodes.map((node) => [
      node.id,
      workflow.edges.filter((edge) => edge.target === node.id).length,
    ]),
  );
  const queue = workflow.nodes.filter((node) => degrees.get(node.id) === 0).map((node) => node.id);
  queue.forEach((id) => levels.set(id, 0));
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    workflow.edges
      .filter((edge) => edge.source === id)
      .forEach((edge) => {
        levels.set(edge.target, Math.max(levels.get(edge.target) || 0, (levels.get(id) || 0) + 1));
        degrees.set(edge.target, (degrees.get(edge.target) || 1) - 1);
        if (degrees.get(edge.target) === 0) queue.push(edge.target);
      });
  }
  const rows = new Map<number, number>();
  return {
    ...workflow,
    nodes: workflow.nodes.map((node) => {
      const level = levels.get(node.id) || 0;
      const row = rows.get(level) || 0;
      rows.set(level, row + 1);
      return { ...node, position: { x: 70 + level * 290, y: 110 + row * 165 } };
    }),
  };
}
