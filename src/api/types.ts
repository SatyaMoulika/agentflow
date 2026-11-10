export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = Record<string, Json>;
export type ConnectionAuth = 'none' | 'bearer' | 'api_key';
export interface PlannerConnection {
  id: string;
  name: string;
  endpoint_url: string;
}
export interface ProviderMetadata {
  provider: 'groq';
  requested_model: string;
  model?: string | null;
  duration_ms: number;
  usage?: {
    prompt_tokens?: number | null;
    completion_tokens?: number | null;
    total_tokens?: number | null;
  } | null;
  finish_reason?: string | null;
  error_code?: string | null;
  retry_after_seconds?: number | null;
}
export interface HttpConnection {
  id: string;
  name: string;
  endpoint_url: string;
  auth_type: ConnectionAuth;
  created_at: string;
  revoked_at: string | null;
}
export interface User {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
}
export interface LoginResult {
  access_token: string;
  csrf_token: string;
  user: User;
  expires_in: number;
}
export interface GraphNode {
  id: string;
  type: string;
  config: JsonObject;
  label?: string;
  position?: { x: number; y: number };
  input_mapping?: Record<string, string>;
}
export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  source_handle?: string;
  label?: string;
}
export interface Definition {
  schema_version: '1.0';
  nodes: GraphNode[];
  edges: GraphEdge[];
  metadata?: JsonObject;
}
export interface WorkflowProposal {
  status: 'ready' | 'unsupported';
  message: string;
  name: string;
  description: string;
  definition: Definition | null;
  sample_input: JsonObject;
  model: string;
  repair_attempted: boolean;
  connections?: PlannerConnection[];
  provider_calls?: ProviderMetadata[];
}
export interface WorkflowEditProposal extends WorkflowProposal {
  base_version_id: string;
  base_version_number: number;
}
export interface WorkflowItem {
  id: string;
  owner_id: string;
  name: string;
  description: string;
  status: string;
  current_version_id: string | null;
  created_at: string;
  updated_at: string;
}
export interface Version {
  id: string;
  workflow_id: string;
  version_number: number;
  definition: Definition;
  created_at: string;
  created_by: string;
}
export interface WorkflowDetail extends WorkflowItem {
  current_version_number: number;
  version: Version | null;
}
export interface Page<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}
export interface CatalogItem {
  type: string;
  name: string;
  category: string;
  description: string;
  execution_ready: boolean;
  output_handles: string[];
  config_schema: JsonObject;
  capabilities: string[];
}
export interface Catalog {
  schema_version: string;
  items: CatalogItem[];
}
export interface Validation {
  valid: boolean;
  execution_ready: boolean;
  issues: { code: string; message: string; path: string }[];
  issues_truncated: boolean;
  workflow_version_id: string | null;
  plan: { topological_order: string[] } | null;
}
export interface History {
  id: string;
  revision: number;
  input: JsonObject;
  output: JsonObject | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  status: string;
}
export interface NodeAttempt extends History {
  node_id: string;
  attempt_number: number;
  duration_ms: number | null;
  provider?: ProviderMetadata | null;
  agent?: {
    tool_rounds: number;
    provider_calls: ProviderMetadata[];
    failure_reason?: string | null;
  } | null;
  retry?: {
    scheduled_at: string;
    due_at: string;
    resumed_at: string | null;
    cancelled_at: string | null;
  } | null;
}
export interface RunDetail extends History {
  next_retry_at?: string | null;
  retry_node_id?: string | null;
  next_retry_attempt?: number | null;
  execution_mode?: 'synchronous' | 'background';
  max_attempts: number;
  parent_run_id: string | null;
  workflow_id: string;
  workflow_version_id: string;
  event_sequence: number;
  version: Version;
  node_runs: NodeAttempt[];
}
export interface ExecutionEvent {
  sequence: number;
  node_run_id: string | null;
  event_type: string;
  payload: JsonObject;
  created_at: string;
}
export interface ExecutionEventPage {
  items: ExecutionEvent[];
  next_after_sequence: number;
}
export interface RunItem {
  execution_mode?: 'synchronous' | 'background';
  id: string;
  workflow_id: string;
  workflow_version_id: string;
  workflow_name: string;
  version_number: number;
  status: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
}
