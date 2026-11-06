import type { Execution, Workflow } from '../types';
import { sleep } from '../lib/utils';
export interface DashboardSnapshot {
  totalWorkflows: number;
  activeWorkflows: number;
  totalExecutions: number;
  successRate: number;
  averageDuration: number;
  succeeded: number;
  failed: number;
  running: number;
  waiting: number;
}
export function calculateMetrics(
  workflows: Workflow[],
  executions: Execution[],
): DashboardSnapshot {
  const succeeded = executions.filter((e) => e.status === 'succeeded').length;
  const failed = executions.filter((e) => e.status === 'failed').length;
  const completed = executions.filter((e) => e.status === 'succeeded' || e.status === 'failed');
  return {
    totalWorkflows: workflows.filter((w) => w.status !== 'archived').length,
    activeWorkflows: workflows.filter((w) => w.status === 'active').length,
    totalExecutions: executions.length,
    successRate: completed.length ? (succeeded / completed.length) * 100 : 0,
    averageDuration: completed.length
      ? completed.reduce((sum, e) => sum + e.duration, 0) / completed.length
      : 0,
    succeeded,
    failed,
    running: executions.filter((e) => e.status === 'running' || e.status === 'queued').length,
    waiting: executions.filter((e) => e.status === 'waiting_approval').length,
  };
}
export interface AgentFlowApi {
  getDashboard: (workflows: Workflow[], executions: Execution[]) => Promise<DashboardSnapshot>;
}
// Legacy prototype adapter. The routed application uses src/api/client.ts instead.
export const mockApi: AgentFlowApi = {
  async getDashboard(workflows, executions) {
    await sleep(180);
    return calculateMetrics(workflows, executions);
  },
};
