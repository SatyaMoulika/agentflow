export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived';
export type NodeType =
  | 'manual'
  | 'webhook'
  | 'schedule'
  | 'llm'
  | 'classify'
  | 'extract'
  | 'agent'
  | 'condition'
  | 'transform'
  | 'merge'
  | 'end'
  | 'http'
  | 'calculator'
  | 'parser'
  | 'approval';
export type NodeCategory = 'Trigger' | 'AI' | 'Logic' | 'Tool' | 'Human';
export interface NodeConfig {
  description?: string;
  model?: string;
  systemPrompt?: string;
  prompt?: string;
  temperature?: number;
  maxTokens?: number;
  timeout?: number;
  retries?: number;
  input?: string;
  outputSchema?: string;
  variable?: string;
  operator?: string;
  value?: string;
  url?: string;
  method?: string;
  headers?: string;
  body?: string;
  connection?: string;
  approver?: string;
  title?: string;
  expiration?: string;
  expression?: string;
}
export interface WorkflowNode {
  id: string;
  type: NodeType;
  label: string;
  position: { x: number; y: number };
  config: NodeConfig;
}
export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  label?: string;
}
export interface Workflow {
  id: string;
  name: string;
  description: string;
  status: WorkflowStatus;
  version: number;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  createdAt: string;
  updatedAt: string;
  totalRuns: number;
  successRate: number;
  lastRun?: string;
  icon: string;
}
export type ExecutionStatus =
  'queued' | 'running' | 'waiting_approval' | 'succeeded' | 'failed' | 'cancelled';
export type NodeRunStatus =
  'pending' | 'running' | 'succeeded' | 'failed' | 'waiting_approval' | 'skipped';
export interface NodeRun {
  attempt?: number;
  retryCount?: number;
  nodeId: string;
  status: NodeRunStatus;
  duration: number;
  startedAt?: string;
  endedAt?: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  error?: string;
  tokens?: { input: number; output: number };
}
export interface ExecutionEvent {
  id: string;
  timestamp: string;
  message: string;
  level: 'info' | 'warn' | 'error';
  nodeId?: string;
}
export interface Execution {
  id: string;
  workflowId: string;
  workflowName: string;
  version: number;
  status: ExecutionStatus;
  startedAt: string;
  duration: number;
  trigger: string;
  traceId: string;
  nodeRuns: NodeRun[];
  events: ExecutionEvent[];
  graph: Workflow;
}
export interface Approval {
  id: string;
  executionId: string;
  workflowId: string;
  workflowName: string;
  nodeId: string;
  title: string;
  description: string;
  requestedAt: string;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  risk: 'low' | 'medium' | 'high';
  data: Record<string, unknown>;
  decisionAt?: string;
  comment?: string;
}
export interface Integration {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  color: string;
  connected: boolean;
  connectionName?: string;
}
export interface Settings {
  name: string;
  email: string;
  theme: 'light' | 'dark' | 'system';
  model: string;
  temperature: number;
  maxSteps: number;
  timeout: number;
  retries: number;
  concurrency: number;
  tracing: boolean;
  retention: string;
  logLevel: string;
  redaction: boolean;
  notifyFailure: boolean;
  notifyApproval: boolean;
  notifyCompletion: boolean;
}
