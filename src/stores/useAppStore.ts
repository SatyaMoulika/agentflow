import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Approval, Execution, Integration, Settings, Workflow } from '../types';
import {
  fixtureWorkflows,
  fixtureExecutions,
  fixtureApprovals,
  fixtureIntegrations,
  defaultSettings,
} from '../data/fixtures';
import { simulateExecution, type SimulationAdapter } from '../services/execution-engine';
import { uid } from '../lib/utils';
import { validateWorkflow } from '../lib/graph';
interface Toast {
  id: string;
  message: string;
  type: 'success' | 'error' | 'info';
}
interface AppState {
  authenticated: boolean;
  workflows: Workflow[];
  executions: Execution[];
  approvals: Approval[];
  integrations: Integration[];
  settings: Settings;
  toasts: Toast[];
  signIn: (name?: string, email?: string) => void;
  signOut: () => void;
  saveWorkflow: (workflow: Workflow) => void;
  updateWorkflow: (id: string, update: Partial<Workflow>) => void;
  duplicateWorkflow: (id: string) => string;
  runWorkflow: (id: string) => string;
  cancelExecution: (id: string) => void;
  decideApproval: (id: string, decision: 'approved' | 'rejected', comment?: string) => void;
  updateIntegration: (id: string, update: Partial<Integration>) => void;
  updateSettings: (update: Partial<Settings>) => void;
  notify: (message: string, type?: Toast['type']) => void;
  dismissToast: (id: string) => void;
}
export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      authenticated: false,
      workflows: fixtureWorkflows,
      executions: fixtureExecutions,
      approvals: fixtureApprovals,
      integrations: fixtureIntegrations,
      settings: defaultSettings,
      toasts: [],
      signIn: (name, email) =>
        set((s) => ({
          authenticated: true,
          settings: { ...s.settings, ...(name ? { name } : {}), ...(email ? { email } : {}) },
        })),
      signOut: () => set({ authenticated: false }),
      saveWorkflow: (workflow) => {
        set((s) => ({
          workflows: s.workflows.some((w) => w.id === workflow.id)
            ? s.workflows.map((w) =>
                w.id === workflow.id ? { ...workflow, updatedAt: new Date().toISOString() } : w,
              )
            : [{ ...workflow, updatedAt: new Date().toISOString() }, ...s.workflows],
        }));
        get().notify('Workflow saved locally', 'success');
      },
      updateWorkflow: (id, update) =>
        set((s) => ({
          workflows: s.workflows.map((w) =>
            w.id === id ? { ...w, ...update, updatedAt: new Date().toISOString() } : w,
          ),
        })),
      duplicateWorkflow: (id) => {
        const w = get().workflows.find((w) => w.id === id);
        if (!w) return '';
        const nextId = uid('wf');
        get().saveWorkflow({
          ...structuredClone(w),
          id: nextId,
          name: `${w.name} (copy)`,
          status: 'draft',
          version: 1,
          totalRuns: 0,
          successRate: 0,
          lastRun: undefined,
        });
        return nextId;
      },
      runWorkflow: (workflowId) => {
        const workflow = get().workflows.find((w) => w.id === workflowId);
        if (!workflow) {
          get().notify('Workflow could not be found', 'error');
          return '';
        }
        if (workflow.status === 'archived') {
          get().notify('Restore this workflow before running it', 'error');
          return '';
        }
        const issues = validateWorkflow(workflow);
        if (issues.length) {
          get().notify(
            `Open the editor to resolve ${issues.length} validation issue${issues.length === 1 ? '' : 's'} before running.`,
            'error',
          );
          return '';
        }
        const id = uid('exec');
        const startedAt = new Date().toISOString();
        const execution: Execution = {
          id,
          workflowId,
          workflowName: workflow.name,
          version: workflow.version,
          status: 'running',
          startedAt,
          duration: 0,
          trigger: 'Manual',
          traceId: uid('trace') + uid('span').slice(5),
          graph: structuredClone(workflow),
          nodeRuns: workflow.nodes.map((n) => ({
            nodeId: n.id,
            status: 'pending',
            duration: 0,
            input: {},
            output: null,
          })),
          events: [
            {
              id: uid('event'),
              timestamp: startedAt,
              message: 'Demo workflow execution started. No external services will be called.',
              level: 'info',
            },
          ],
        };
        set((s) => ({ executions: [execution, ...s.executions] }));
        void simulateExecution(id, simulationAdapter);
        return id;
      },
      cancelExecution: (id) => {
        const e = get().executions.find((e) => e.id === id);
        if (!e || !['running', 'waiting_approval', 'queued'].includes(e.status)) return;
        set((s) => ({
          executions: s.executions.map((e) =>
            e.id === id
              ? {
                  ...e,
                  status: 'cancelled',
                  nodeRuns: e.nodeRuns.map((n) =>
                    ['running', 'pending', 'waiting_approval'].includes(n.status)
                      ? { ...n, status: 'skipped' }
                      : n,
                  ),
                  events: [
                    ...e.events,
                    {
                      id: uid('event'),
                      timestamp: new Date().toISOString(),
                      message: 'Demo execution cancelled by user',
                      level: 'warn',
                    },
                  ],
                }
              : e,
          ),
          approvals: s.approvals.map((a) =>
            a.executionId === id && a.status === 'pending' ? { ...a, status: 'expired' } : a,
          ),
        }));
        get().notify('Execution cancelled');
      },
      decideApproval: (id, decision, comment) => {
        const a = get().approvals.find((a) => a.id === id);
        if (!a || a.status !== 'pending') {
          get().notify('This approval has already been resolved', 'error');
          return;
        }
        const execution = get().executions.find((e) => e.id === a.executionId);
        if (!execution || execution.status !== 'waiting_approval') {
          get().notify('The linked execution is no longer waiting for approval', 'error');
          return;
        }
        const now = new Date().toISOString();
        set((s) => ({
          approvals: s.approvals.map((item) =>
            item.id === id ? { ...item, status: decision, decisionAt: now, comment } : item,
          ),
          executions: s.executions.map((e) =>
            e.id === a.executionId
              ? {
                  ...e,
                  status: 'running',
                  duration: e.duration + 120,
                  nodeRuns: e.nodeRuns.map((n) =>
                    n.nodeId === a.nodeId
                      ? {
                          ...n,
                          status: 'succeeded',
                          duration: 120,
                          endedAt: now,
                          output: {
                            ...n.input,
                            decision,
                            approvedBy: s.settings.name,
                            comment: comment || '',
                          },
                        }
                      : n,
                  ),
                  events: [
                    ...e.events,
                    {
                      id: uid('event'),
                      timestamp: now,
                      message: `Human decision: ${decision}. Demo execution resumed.`,
                      nodeId: a.nodeId,
                      level: 'info',
                    },
                  ],
                }
              : e,
          ),
        }));
        get().notify(`Request ${decision}`, 'success');
        void simulateExecution(a.executionId, simulationAdapter);
      },
      updateIntegration: (id, update) =>
        set((s) => ({
          integrations: s.integrations.map((i) => (i.id === id ? { ...i, ...update } : i)),
        })),
      updateSettings: (update) => set((s) => ({ settings: { ...s.settings, ...update } })),
      notify: (message, type = 'info') => {
        const id = uid('toast');
        set((s) => ({ toasts: [...s.toasts.slice(-3), { id, message, type }] }));
        setTimeout(() => get().dismissToast(id), 5000);
      },
      dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
    }),
    {
      name: 'agentflow-prototype-v1',
      partialize: ({
        authenticated,
        workflows,
        executions,
        approvals,
        integrations,
        settings,
      }) => ({
        authenticated,
        workflows,
        executions,
        approvals,
        integrations,
        settings,
      }),
    },
  ),
);
function refreshWorkflowMetrics(workflows: Workflow[], executions: Execution[]): Workflow[] {
  return workflows.map((w) => {
    const runs = executions.filter((e) => e.workflowId === w.id);
    return {
      ...w,
      totalRuns: runs.length,
      successRate: runs.length
        ? Math.round((runs.filter((e) => e.status === 'succeeded').length / runs.length) * 100)
        : 0,
      lastRun: runs[0]?.startedAt,
    };
  });
}
useAppStore.subscribe((state, previous) => {
  if (state.executions !== previous.executions) {
    useAppStore.setState({ workflows: refreshWorkflowMetrics(state.workflows, state.executions) });
  }
});
const simulationAdapter: SimulationAdapter = {
  getExecution: (id) => useAppStore.getState().executions.find((e) => e.id === id),
  updateExecution: (id, update) =>
    useAppStore.setState((s) => ({
      executions: s.executions.map((e) => (e.id === id ? { ...e, ...update } : e)),
    })),
  requestApproval: (approval) =>
    useAppStore.setState((s) => ({ approvals: [approval, ...s.approvals] })),
};
export function resumeSimulations() {
  for (const e of useAppStore.getState().executions) {
    if (e.status === 'running' || e.status === 'queued')
      void simulateExecution(e.id, simulationAdapter);
  }
}
