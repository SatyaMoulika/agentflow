import type { Definition, GraphNode, Json, JsonObject } from './types';
export function parseObject(text: string): JsonObject {
  let value: Json;
  try {
    value = JSON.parse(text) as Json;
  } catch {
    throw new Error('Enter valid JSON.');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Use a JSON object, not a list or scalar.');
  const walk = (item: Json, depth: number) => {
    if (depth > 32) throw new Error('JSON nesting exceeds 32 levels.');
    if (typeof item === 'number' && !Number.isFinite(item))
      throw new Error('Use finite JSON numbers.');
    if (item && typeof item === 'object')
      Object.values(item).forEach((child) => walk(child, depth + 1));
  };
  walk(value, 0);
  if (new TextEncoder().encode(JSON.stringify(value)).length > 262144)
    throw new Error('JSON exceeds the 256 KiB limit.');
  return value;
}
export function parseDefinition(text: string): Definition {
  const value = parseObject(text);
  if (value.schema_version !== '1.0' || !Array.isArray(value.nodes) || !Array.isArray(value.edges))
    throw new Error('A definition needs schema_version "1.0" and nodes/edges arrays.');
  if (
    value.nodes.some(
      (node) =>
        !node ||
        typeof node !== 'object' ||
        Array.isArray(node) ||
        typeof node.id !== 'string' ||
        typeof node.type !== 'string' ||
        !node.config ||
        typeof node.config !== 'object' ||
        Array.isArray(node.config),
    )
  )
    throw new Error('Each node needs an id, type and configuration object.');
  if (
    value.edges.some(
      (edge) =>
        !edge ||
        typeof edge !== 'object' ||
        Array.isArray(edge) ||
        typeof edge.id !== 'string' ||
        typeof edge.source !== 'string' ||
        typeof edge.target !== 'string',
    )
  )
    throw new Error('Each edge needs id, source and target strings.');
  return value as unknown as Definition;
}
export function starterDefinition(): Definition {
  return {
    schema_version: '1.0',
    nodes: [
      {
        id: 'start',
        type: 'manual',
        label: 'Manual start',
        position: { x: 40, y: 130 },
        config: {},
      },
      { id: 'finish', type: 'end', label: 'Finish', position: { x: 460, y: 130 }, config: {} },
    ],
    edges: [{ id: 'start_finish', source: 'start', target: 'finish', source_handle: 'default' }],
  };
}
export function defaultNode(type: string, start = 'start', index = 0): GraphNode {
  let config: JsonObject = {};
  if (type === 'http') config = { connection_id: '' };
  if (type === 'transform') config = { operation: 'identity' };
  if (type === 'groq')
    config = { instruction: 'Draft a helpful response to the message.', input_field: 'message' };
  if (type === 'agent')
    config = {
      instruction: 'Use the calculator for arithmetic and explain the result.',
      input_field: 'message',
      max_tool_rounds: 3,
    };
  if (type === 'json_parser') config = { input_field: 'text' };
  if (type === 'classify') config = { input_field: 'text', labels: ['positive', 'negative'] };
  if (type === 'extract') config = { input_field: 'text', fields: ['name', 'email'] };
  if (type === 'condition')
    config = { field: `$.${start}.output.amount`, operator: 'greater_than', value: 10 };
  if (type === 'calculator')
    config = {
      operation: 'add',
      operands: [
        { kind: 'literal', value: 1 },
        { kind: 'literal', value: 2 },
      ],
    };
  return {
    id: `${type}_${crypto.randomUUID().replaceAll('-', '').slice(0, 8)}`,
    type,
    config,
    label: type[0].toUpperCase() + type.slice(1),
    position: { x: 210 + (index % 3) * 90, y: 60 + (index % 5) * 95 },
  };
}
export function downloadDraft(name: string, definition: Definition) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(definition, null, 2)], { type: 'application/json' }),
  );
  const link = document.createElement('a');
  link.href = url;
  link.download = `${name.replace(/[^a-zA-Z0-9_-]/g, '_') || 'workflow'}-draft.json`;
  link.click();
  URL.revokeObjectURL(url);
}
