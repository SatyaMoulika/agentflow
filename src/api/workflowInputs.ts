import type { Definition, JsonObject } from './types';

export type InputField = {
  name: string;
  label: string;
  type: 'text' | 'number' | 'boolean';
  required: boolean;
  default?: string | number | boolean;
};

export function readInputFields(definition: Definition): InputField[] | null {
  const raw = definition.metadata?.agentflow_input_fields;
  if (!Array.isArray(raw) || raw.length > 30) return null;
  const fields: InputField[] = [];
  for (const item of raw) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return null;
    if (
      Object.keys(item).some(
        (key) => !['name', 'label', 'type', 'required', 'default'].includes(key),
      )
    )
      return null;
    const { name, label, type, required } = item;
    if (
      typeof name !== 'string' ||
      !name.trim() ||
      name.length > 200 ||
      typeof label !== 'string' ||
      !label.trim() ||
      label.length > 200 ||
      (type !== 'text' && type !== 'number' && type !== 'boolean') ||
      typeof required !== 'boolean' ||
      fields.some((field) => field.name === name)
    )
      return null;
    const fallback = item.default;
    if (
      fallback !== undefined &&
      !(
        (type === 'text' && typeof fallback === 'string') ||
        (type === 'number' && typeof fallback === 'number' && Number.isFinite(fallback)) ||
        (type === 'boolean' && typeof fallback === 'boolean')
      )
    )
      return null;
    fields.push({
      name,
      label,
      type,
      required,
      ...(fallback !== undefined ? { default: fallback as string | number | boolean } : {}),
    });
  }
  return fields;
}

export function suggestedInputs(definition: Definition): InputField[] {
  const start = definition.nodes.find((node) => node.type === 'manual');
  if (!start) return [];
  const names = new Set<string>();
  for (const edge of definition.edges.filter((item) => item.source === start.id)) {
    const node = definition.nodes.find((item) => item.id === edge.target);
    if (
      node &&
      !Object.keys(node.input_mapping || {}).length &&
      ['agent', 'groq', 'classify', 'extract', 'json_parser'].includes(node.type) &&
      typeof node.config.input_field === 'string' &&
      node.config.input_field.trim()
    )
      names.add(node.config.input_field);
    if (
      node?.type === 'gmail_read' &&
      !Object.keys(node.input_mapping || {}).length &&
      typeof node.config.message_id_field === 'string' &&
      node.config.message_id_field.trim()
    )
      names.add(node.config.message_id_field);
  }
  return [...names].map((name) => ({ name, label: name, type: 'text', required: true }));
}

export function buildInput(fields: InputField[], values: Record<string, string>): JsonObject {
  const output: JsonObject = Object.create(null) as JsonObject;
  for (const field of fields) {
    const value = values[field.name] ?? '';
    if (!value.trim()) {
      if (field.required) throw new Error(`Enter ${field.label}.`);
      continue;
    }
    if (field.type === 'number') {
      const parsed = Number(value);
      if (!Number.isFinite(parsed)) throw new Error(`${field.label} must be a valid number.`);
      output[field.name] = parsed;
    } else if (field.type === 'boolean') {
      if (value !== 'true' && value !== 'false')
        throw new Error(`Choose a value for ${field.label}.`);
      output[field.name] = value === 'true';
    } else output[field.name] = value;
  }
  return output;
}

export function formValues(fields: InputField[], input: JsonObject): Record<string, string> {
  if (Object.keys(input).some((name) => !fields.some((field) => field.name === name)))
    throw new Error(
      'The JSON contains additional fields. Remove them before switching to the form.',
    );
  const values: Record<string, string> = Object.create(null) as Record<string, string>;
  for (const field of fields) {
    const value = input[field.name];
    if (!Object.hasOwn(input, field.name)) values[field.name] = '';
    else if (
      (field.type === 'text' && typeof value === 'string') ||
      (field.type === 'number' && typeof value === 'number') ||
      (field.type === 'boolean' && typeof value === 'boolean')
    )
      values[field.name] = String(value);
    else throw new Error(`${field.label} has a different type in JSON.`);
  }
  return values;
}
