import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { calculateMetrics } from '../src/services/api';
import { createBlankWorkflow, generateMockWorkflow } from '../src/services/generation';
import type { Workflow } from '../src/types';

class MemoryStorage implements Storage {
  private values = new Map<string, string>();
  get length() {
    return this.values.size;
  }
  clear() {
    this.values.clear();
  }
  getItem(key: string) {
    return this.values.get(key) ?? null;
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null;
  }
  removeItem(key: string) {
    this.values.delete(key);
  }
  setItem(key: string, value: string) {
    this.values.set(key, value);
  }
}

let useAppStore: (typeof import('../src/stores/useAppStore'))['useAppStore'];
let storage: MemoryStorage;

function invoiceWorkflow(): Workflow {
  const generated = generateMockWorkflow(
    'Process invoices, extract the amount, and request approval above ₹50,000.',
  );
  if (!generated.ok) throw new Error(generated.error);
  return generated.workflow;
}

function execution(id: string) {
  const result = useAppStore.getState().executions.find((item) => item.id === id);
  if (!result) throw new Error(`Execution ${id} is missing.`);
  return result;
}

async function startInvoice() {
  const workflow = invoiceWorkflow();
  useAppStore.getState().saveWorkflow(workflow);
  const id = useAppStore.getState().runWorkflow(workflow.id);
  expect(id).not.toBe('');
  await vi.runAllTimersAsync();
  expect(execution(id).status).toBe('waiting_approval');
  const approval = useAppStore
    .getState()
    .approvals.find((item) => item.executionId === id && item.status === 'pending');
  if (!approval) throw new Error('The simulated invoice did not create an approval.');
  return { id, workflow, approval };
}

describe('local application store journeys', () => {
  beforeEach(async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-29T09:00:00.000Z'));
    storage = new MemoryStorage();
    vi.stubGlobal('localStorage', storage);
    vi.stubGlobal('window', { localStorage: storage });
    vi.resetModules();
    ({ useAppStore } = await import('../src/stores/useAppStore'));
    // Each journey starts from an empty workspace while retaining real store actions.
    useAppStore.setState({
      authenticated: true,
      workflows: [],
      executions: [],
      approvals: [],
      toasts: [],
    });
  });

  afterEach(async () => {
    await vi.runAllTimersAsync();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('saves a generated invoice, pauses for review, then completes with coherent metrics and data', async () => {
    const { id, workflow, approval } = await startInvoice();
    expect(useAppStore.getState().workflows.find((item) => item.id === workflow.id)).toMatchObject({
      totalRuns: 1,
      successRate: 0,
    });
    expect(approval).toMatchObject({
      workflowId: workflow.id,
      executionId: id,
      data: { amount: 60000 },
    });
    expect(execution(id).nodeRuns.find((run) => run.nodeId === 'invoice_store')?.status).toBe(
      'pending',
    );

    useAppStore.getState().decideApproval(approval.id, 'approved', 'Reviewed the demo invoice.');
    await vi.runAllTimersAsync();

    const complete = execution(id);
    expect(complete.status).toBe('succeeded');
    expect(complete.duration).toBe(complete.nodeRuns.reduce((sum, run) => sum + run.duration, 0));
    expect(complete.nodeRuns.find((run) => run.nodeId === approval.nodeId)).toMatchObject({
      duration: 120,
      status: 'succeeded',
      output: { amount: 60000, decision: 'approved' },
    });
    expect(complete.nodeRuns.find((run) => run.nodeId === 'invoice_store')).toMatchObject({
      status: 'succeeded',
      input: { amount: 60000, decision: 'approved' },
      output: { status_code: 200, simulated: true },
    });
    expect(complete.nodeRuns.find((run) => run.nodeId === 'invoice_reject')?.status).toBe(
      'skipped',
    );
    expect(useAppStore.getState().approvals.find((item) => item.id === approval.id)).toMatchObject({
      status: 'approved',
      comment: 'Reviewed the demo invoice.',
    });
    expect(useAppStore.getState().workflows.find((item) => item.id === workflow.id)).toMatchObject({
      totalRuns: 1,
      successRate: 100,
      lastRun: complete.startedAt,
    });
    expect(
      calculateMetrics(useAppStore.getState().workflows, useAppStore.getState().executions),
    ).toMatchObject({
      totalExecutions: 1,
      succeeded: 1,
      waiting: 0,
      running: 0,
      averageDuration: complete.duration,
      successRate: 100,
    });
    expect(
      complete.events.filter(
        (event) => event.nodeId === 'invoice_extract' && event.message.includes('started'),
      ),
    ).toHaveLength(1);
  });

  it('ignores repeated approval decisions without duplicate resume events or duration', async () => {
    const { id, approval } = await startInvoice();
    const before = execution(id).duration;
    useAppStore.getState().decideApproval(approval.id, 'approved', 'First decision');
    useAppStore.getState().decideApproval(approval.id, 'rejected', 'Duplicate decision');
    await vi.runAllTimersAsync();

    const complete = execution(id);
    expect(complete.status).toBe('succeeded');
    expect(useAppStore.getState().approvals.find((item) => item.id === approval.id)).toMatchObject({
      status: 'approved',
      comment: 'First decision',
    });
    expect(
      complete.events.filter((event) => event.message.startsWith('Human decision:')),
    ).toHaveLength(1);
    expect(complete.duration).toBe(before + 120 + 420 + 42);
    expect(complete.duration).toBe(complete.nodeRuns.reduce((sum, run) => sum + run.duration, 0));
    expect(complete.nodeRuns.find((run) => run.nodeId === 'invoice_reject')?.status).toBe(
      'skipped',
    );
  });

  it('expires pending requests when a waiting execution is cancelled and refuses late decisions', async () => {
    const { id, approval } = await startInvoice();
    const before = execution(id).duration;
    useAppStore.getState().cancelExecution(id);
    useAppStore.getState().decideApproval(approval.id, 'approved');
    await vi.runAllTimersAsync();

    expect(execution(id)).toMatchObject({ status: 'cancelled', duration: before });
    expect(useAppStore.getState().approvals.find((item) => item.id === approval.id)?.status).toBe(
      'expired',
    );
    expect(execution(id).nodeRuns.find((run) => run.nodeId === approval.nodeId)?.status).toBe(
      'skipped',
    );
    expect(execution(id).nodeRuns.find((run) => run.nodeId === 'invoice_store')?.status).toBe(
      'skipped',
    );
    expect(execution(id).events.some((event) => event.message.startsWith('Human decision:'))).toBe(
      false,
    );
    expect(
      calculateMetrics(useAppStore.getState().workflows, useAppStore.getState().executions),
    ).toMatchObject({ totalExecutions: 1, succeeded: 0, waiting: 0, running: 0 });
  });

  it('rejects invalid, archived, and missing workflows at the store entry point', () => {
    const invalid = createBlankWorkflow();
    useAppStore.getState().saveWorkflow(invalid);
    expect(useAppStore.getState().runWorkflow(invalid.id)).toBe('');
    expect(useAppStore.getState().toasts.at(-1)).toMatchObject({
      type: 'error',
      message: expect.stringContaining('validation issue'),
    });

    const archived = { ...invoiceWorkflow(), status: 'archived' as const };
    useAppStore.getState().saveWorkflow(archived);
    expect(useAppStore.getState().runWorkflow(archived.id)).toBe('');
    expect(useAppStore.getState().runWorkflow('missing-workflow')).toBe('');
    expect(useAppStore.getState().executions).toHaveLength(0);
    expect(useAppStore.getState().approvals).toHaveLength(0);
  });

  it('persists mock settings and workflow edits across a fresh store instance without persisting toasts', async () => {
    const workflow = invoiceWorkflow();
    useAppStore.getState().saveWorkflow(workflow);
    useAppStore.getState().updateWorkflow(workflow.id, { name: 'Finance invoice review' });
    useAppStore.getState().signIn('Jamie', 'jamie@example.com');
    useAppStore
      .getState()
      .updateSettings({ theme: 'dark', temperature: 0.4, notifyCompletion: false });
    useAppStore.getState().notify('Ephemeral notification');
    const persisted = JSON.parse(storage.getItem('agentflow-prototype-v1')!);
    expect(persisted.state.toasts).toBeUndefined();

    vi.resetModules();
    const fresh = (await import('../src/stores/useAppStore')).useAppStore;
    expect(fresh.persist.hasHydrated()).toBe(true);
    expect(fresh.getState().authenticated).toBe(true);
    expect(fresh.getState().settings).toMatchObject({
      name: 'Jamie',
      email: 'jamie@example.com',
      theme: 'dark',
      temperature: 0.4,
      notifyCompletion: false,
    });
    const persistedGraph = JSON.parse(
      JSON.stringify({ nodes: workflow.nodes, edges: workflow.edges }),
    );
    expect(fresh.getState().workflows.find((item) => item.id === workflow.id)).toMatchObject({
      name: 'Finance invoice review',
      ...persistedGraph,
    });
    expect(fresh.getState().toasts).toHaveLength(0);
    useAppStore = fresh;
  });

  it('rehydrates a waiting approval and completes it after a simulated refresh', async () => {
    const { id, approval } = await startInvoice();
    vi.resetModules();
    const refreshed = await import('../src/stores/useAppStore');
    useAppStore = refreshed.useAppStore;
    refreshed.resumeSimulations();
    await vi.runAllTimersAsync();
    expect(execution(id).status).toBe('waiting_approval');
    expect(useAppStore.getState().approvals.filter((item) => item.executionId === id)).toHaveLength(
      1,
    );

    useAppStore.getState().decideApproval(approval.id, 'approved');
    await vi.runAllTimersAsync();
    expect(execution(id).status).toBe('succeeded');
    expect(execution(id).duration).toBe(
      execution(id).nodeRuns.reduce((sum, run) => sum + run.duration, 0),
    );
    expect(useAppStore.getState().approvals.filter((item) => item.executionId === id)).toHaveLength(
      1,
    );
  });
});
