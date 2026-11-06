import {
  Play,
  Webhook,
  CalendarClock,
  Sparkles,
  Tags,
  ScanText,
  Bot,
  GitBranch,
  Braces,
  Merge,
  Flag,
  Globe,
  Calculator,
  FileText,
  UserCheck,
  type LucideIcon,
} from 'lucide-react';
import { z } from 'zod';
import type { NodeType, NodeCategory, NodeConfig, WorkflowNode } from '../types';
import { uid } from './utils';
export interface NodeDefinition {
  type: NodeType;
  name: string;
  category: NodeCategory;
  description: string;
  icon: LucideIcon;
  color: string;
  defaultConfig: NodeConfig;
  outputs: string[];
  comingSoon?: boolean;
  configSchema: z.ZodType<NodeConfig>;
  inputSchema: z.ZodType;
  outputSchema: z.ZodType;
}
const configSchema = z.object({
  description: z.string().optional(),
  model: z.string().optional(),
  systemPrompt: z.string().optional(),
  prompt: z.string().optional(),
  temperature: z.number().min(0).max(2).optional(),
  maxTokens: z.number().int().positive().optional(),
  timeout: z.number().positive().optional(),
  retries: z.number().min(0).optional(),
  input: z.string().optional(),
  outputSchema: z.string().optional(),
  variable: z.string().optional(),
  operator: z.string().optional(),
  value: z.string().optional(),
  url: z.string().optional(),
  method: z.string().optional(),
  headers: z.string().optional(),
  body: z.string().optional(),
  connection: z.string().optional(),
  approver: z.string().optional(),
  title: z.string().optional(),
  expiration: z.string().optional(),
  expression: z.string().optional(),
});
const requiredText = (name: string) =>
  z
    .string({ error: `${name} is required.` })
    .trim()
    .min(1, `${name} is required.`);
export const nodeConfigSchemas = {
  ai: configSchema.extend({ model: requiredText('Model'), prompt: requiredText('Prompt') }),
  condition: configSchema.extend({
    variable: requiredText('Input variable'),
    operator: z.enum(['greater_than', 'less_than', 'equals', 'not_equals', 'contains']),
    value: requiredText('Comparison value'),
  }),
  http: configSchema.extend({
    url: requiredText('Request URL').regex(
      /^https?:\/\/[^\s]+$/i,
      'Enter an http:// or https:// URL.',
    ),
  }),
  approval: configSchema.extend({
    title: requiredText('Approval title'),
    approver: requiredText('Assigned approver'),
  }),
  expression: configSchema.extend({ expression: requiredText('Expression') }),
};
const schemaFor = (type: NodeType): z.ZodType<NodeConfig> =>
  ['llm', 'extract', 'classify', 'agent'].includes(type)
    ? nodeConfigSchemas.ai
    : type === 'condition'
      ? nodeConfigSchemas.condition
      : type === 'http'
        ? nodeConfigSchemas.http
        : type === 'approval'
          ? nodeConfigSchemas.approval
          : ['transform', 'calculator'].includes(type)
            ? nodeConfigSchemas.expression
            : configSchema;
const definition = (
  type: NodeType,
  name: string,
  category: NodeCategory,
  description: string,
  icon: LucideIcon,
  color: string,
  defaultConfig: NodeConfig = {},
  outputs = ['default'],
  comingSoon = false,
): NodeDefinition => ({
  type,
  name,
  category,
  description,
  icon,
  color:
    {
      indigo: '#6366f1',
      violet: '#8b5cf6',
      amber: '#d99a23',
      blue: '#3b82f6',
      teal: '#0d9488',
      slate: '#8591a5',
    }[color] || color,
  defaultConfig,
  outputs,
  comingSoon,
  configSchema: schemaFor(type),
  inputSchema: z.record(z.string(), z.unknown()),
  outputSchema: z.record(z.string(), z.unknown()),
});
export const nodeRegistry: Record<NodeType, NodeDefinition> = {
  manual: definition(
    'manual',
    'Manual Trigger',
    'Trigger',
    'Start a workflow on demand',
    Play,
    'indigo',
  ),
  webhook: definition(
    'webhook',
    'Webhook Trigger',
    'Trigger',
    'Receive an incoming request',
    Webhook,
    'indigo',
    {},
    ['default'],
    true,
  ),
  schedule: definition(
    'schedule',
    'Schedule Trigger',
    'Trigger',
    'Run on a recurring schedule',
    CalendarClock,
    'indigo',
    {},
    ['default'],
    true,
  ),
  llm: definition(
    'llm',
    'LLM Generation',
    'AI',
    'Generate text with a language model',
    Sparkles,
    'violet',
    {
      model: 'gpt-4.1-mini',
      systemPrompt: 'You are a helpful automation assistant.',
      prompt: 'Summarize the supplied input.',
      temperature: 0.3,
      maxTokens: 2048,
      timeout: 30,
      retries: 2,
    },
  ),
  classify: definition(
    'classify',
    'Text Classification',
    'AI',
    'Classify text into useful categories',
    Tags,
    'violet',
    {
      model: 'gpt-4.1-mini',
      prompt: 'Classify the input as billing, technical, or general.',
      temperature: 0.1,
      maxTokens: 512,
    },
  ),
  extract: definition(
    'extract',
    'Information Extraction',
    'AI',
    'Turn unstructured content into data',
    ScanText,
    'violet',
    {
      model: 'gpt-4.1-mini',
      prompt: 'Extract invoice number, vendor, amount, and currency.',
      temperature: 0,
      maxTokens: 2048,
      outputSchema: '{"invoice_number":"string","amount":"number","vendor":"string"}',
    },
  ),
  agent: definition('agent', 'AI Agent', 'AI', 'Reason through a defined task', Bot, 'violet', {
    model: 'gpt-4.1-mini',
    prompt: 'Analyze the supplied data and produce a structured recommendation.',
    temperature: 0.3,
    maxTokens: 2048,
  }),
  condition: definition(
    'condition',
    'Condition',
    'Logic',
    'Branch based on a comparison',
    GitBranch,
    'amber',
    { variable: 'amount', operator: 'greater_than', value: '50000' },
    ['true', 'false'],
  ),
  transform: definition(
    'transform',
    'Transform Data',
    'Logic',
    'Map and reshape your data',
    Braces,
    'amber',
    { expression: 'input', description: 'Validate required fields and normalize the result.' },
  ),
  merge: definition('merge', 'Merge', 'Logic', 'Bring workflow branches together', Merge, 'amber'),
  end: definition('end', 'End', 'Logic', 'Complete the workflow', Flag, 'slate', {}, []),
  http: definition('http', 'HTTP Request', 'Tool', 'Send data to an HTTP endpoint', Globe, 'blue', {
    url: 'https://example.com/api/results',
    method: 'POST',
    headers: '{"Content-Type":"application/json"}',
    body: '{{ input }}',
    timeout: 30,
    retries: 2,
  }),
  calculator: definition(
    'calculator',
    'Calculator',
    'Tool',
    'Evaluate a numeric expression',
    Calculator,
    'blue',
    { expression: '60000 * 1.18' },
  ),
  parser: definition(
    'parser',
    'Document Parser',
    'Tool',
    'Parse documents and structured files',
    FileText,
    'blue',
    { description: 'Parse the demo document into structured text.' },
  ),
  approval: definition(
    'approval',
    'Approval Request',
    'Human',
    'Pause and ask a person to review',
    UserCheck,
    'teal',
    {
      title: 'Review invoice payment',
      approver: 'Moulika',
      description: 'Review the extracted invoice before saving.',
      expiration: '24 hours',
    },
    ['approved', 'rejected'],
  ),
};
export const createNode = (type: NodeType, position = { x: 100, y: 100 }): WorkflowNode => ({
  id: uid('node'),
  type,
  label: nodeRegistry[type].name,
  position,
  config: { ...nodeRegistry[type].defaultConfig },
});
