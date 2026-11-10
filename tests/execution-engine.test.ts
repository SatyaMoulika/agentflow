import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  evaluateCondition,
  simulateExecution,
  type SimulationAdapter,
} from '../src/services/execution-engine';
import {
  demoInput,
  fixtureApprovals,
  fixtureExecutions,
  fixtureWorkflows,
} from '../src/data/fixtures';
import type { Approval, Execution, Workflow } from '../src/types';

let nextId = 0;
function createHarness(workflow: Workflow = fixtureWorkflows[0]) {
  const graph = structuredClone(workflow);
  let execution: Execution = {
    id: `test_execution_${nextId++}`,
    workflowId: graph.id,
    workflowName: graph.name,
    version: graph.version,
    status: 'running',
    startedAt: new Date().toISOString(),
    duration: 0,
    trigger: 'Manual',
    traceId: 'test_trace',
    graph,
    events: [],
    nodeRuns: graph.nodes.map((node) => ({
      nodeId: node.id,
      status: 'pending',
      duration: 0,
      input: {},
      output: null,
    })),
  };
  const approvals: Approval[] = [];
  const adapter: SimulationAdapter = {
    getExecution: (id) => (id === execution.id ? execution : undefined),
    updateExecution: (id, update) => {
      if (id === execution.id) execution = { ...execution, ...update };
    },
    requestApproval: (approval) => approvals.push(approval),
  };
  return {
    adapter,
    approvals,
    get execution() {
      return execution;
    },
    node: (id: string) => execution.nodeRuns.find((run) => run.nodeId === id)!,
    decide(decision: 'approved' | 'rejected') {
      const approval = approvals.find((approval) => approval.status === 'pending');
      if (!approval) throw new Error('No pending approval to decide.');
      approval.status = decision;
      adapter.updateExecution(execution.id, {
        status: 'running',
        nodeRuns: execution.nodeRuns.map((run) =>
          run.nodeId === approval.nodeId
            ? {
                ...run,
                status: 'succeeded',
                endedAt: new Date().toISOString(),
                output: { ...run.input, decision },
              }
            : run,
        ),
      });
    },
    cancel() {
      adapter.updateExecution(execution.id, {
        status: 'cancelled',
        nodeRuns: execution.nodeRuns.map((run) =>
          ['pending', 'running', 'waiting_approval'].includes(run.status)
            ? { ...run, status: 'skipped' }
            : run,
        ),
      });
    },
  };
}

async function finishSimulation(harness: ReturnType<typeof createHarness>) {
  const pending = simulateExecution(harness.execution.id, harness.adapter);
  await vi.runAllTimersAsync();
  await pending;
}

describe('simulated workflow execution', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-29T09:00:00.000Z'));
  });
  afterEach(() => vi.useRealTimers());

  it('uses the configured condition threshold to follow only the false branch', async () => {
    const workflow = structuredClone(fixtureWorkflows[0]);
    workflow.nodes.find((node) => node.type === 'condition')!.config.value = '100000';
    const harness = createHarness(workflow);
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('succeeded');
    expect(harness.node('invoice_condition').output?.matched).toBe(false);
    expect(harness.node('invoice_store').status).toBe('succeeded');
    expect(harness.node('invoice_end').status).toBe('succeeded');
    expect(harness.node('invoice_approve').status).toBe('skipped');
    expect(harness.node('invoice_reject').status).toBe('skipped');
    expect(harness.approvals).toHaveLength(0);
    expect(harness.execution.duration).toBe(
      harness.execution.nodeRuns.reduce((total, run) => total + run.duration, 0),
    );
  });

  it('pauses the true branch at approval without executing downstream actions', async () => {
    const harness = createHarness();
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('waiting_approval');
    expect(harness.node('invoice_condition').output?.matched).toBe(true);
    expect(harness.node('invoice_approve').status).toBe('waiting_approval');
    expect(harness.node('invoice_store').status).toBe('pending');
    expect(harness.node('invoice_end').status).toBe('pending');
    expect(harness.approvals).toHaveLength(1);
    expect(harness.approvals[0]).toMatchObject({
      executionId: harness.execution.id,
      nodeId: 'invoice_approve',
      status: 'pending',
      data: { amount: demoInput.amount },
    });
    expect(
      harness.execution.events.some(
        (event) => event.level === 'warn' && event.nodeId === 'invoice_approve',
      ),
    ).toBe(true);
    await finishSimulation(harness);
    expect(harness.approvals).toHaveLength(1);
    expect(harness.node('invoice_store').status).toBe('pending');
  });

  it('resumes an approved request through the approved edge without repeating completed steps', async () => {
    const harness = createHarness();
    await finishSimulation(harness);
    const startedBefore = harness.execution.events.filter(
      (event) => event.nodeId === 'invoice_extract' && event.message.includes('started'),
    ).length;
    const extraction = structuredClone(harness.node('invoice_extract'));
    harness.decide('approved');
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('succeeded');
    expect(harness.node('invoice_store').status).toBe('succeeded');
    expect(harness.node('invoice_end').status).toBe('succeeded');
    expect(harness.node('invoice_reject').status).toBe('skipped');
    expect(harness.node('invoice_extract')).toEqual(extraction);
    expect(
      harness.execution.events.filter(
        (event) => event.nodeId === 'invoice_extract' && event.message.includes('started'),
      ),
    ).toHaveLength(startedBefore);
    expect(harness.approvals).toHaveLength(1);
  });

  it('resumes a rejected request through its terminal rejection edge without saving the invoice', async () => {
    const harness = createHarness();
    await finishSimulation(harness);
    harness.decide('rejected');
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('succeeded');
    expect(harness.node('invoice_approve').output?.decision).toBe('rejected');
    expect(harness.node('invoice_reject').status).toBe('succeeded');
    expect(harness.node('invoice_store').status).toBe('skipped');
    expect(harness.node('invoice_end').status).toBe('skipped');
    expect(harness.execution.events.some((event) => event.nodeId === 'invoice_store')).toBe(false);
  });

  it('honors cancellation during an in-flight step and does not revive the execution', async () => {
    const harness = createHarness();
    const pending = simulateExecution(harness.execution.id, harness.adapter);
    expect(harness.node('invoice_trigger').status).toBe('running');
    harness.cancel();
    await vi.runAllTimersAsync();
    await pending;

    expect(harness.execution.status).toBe('cancelled');
    expect(harness.execution.nodeRuns.every((run) => run.status === 'skipped')).toBe(true);
    expect(harness.execution.nodeRuns.every((run) => run.output === null)).toBe(true);
    expect(harness.approvals).toHaveLength(0);
    await finishSimulation(harness);
    expect(harness.execution.status).toBe('cancelled');
    expect(harness.approvals).toHaveLength(0);
  });

  it('allows only one worker for an execution started twice concurrently', async () => {
    const harness = createHarness(fixtureWorkflows[3]);
    const first = simulateExecution(harness.execution.id, harness.adapter);
    const second = simulateExecution(harness.execution.id, harness.adapter);
    await vi.runAllTimersAsync();
    await Promise.all([first, second]);
    expect(harness.execution.status).toBe('succeeded');
    expect(
      harness.execution.events.filter(
        (event) => event.nodeId === 'doc_trigger' && event.message.includes('started'),
      ),
    ).toHaveLength(1);
  });

  it('passes classifier output into the condition and the chosen downstream action', async () => {
    const workflow = structuredClone(fixtureWorkflows[1]);
    workflow.nodes.find((node) => node.type === 'condition')!.config.value = 'normal';
    const harness = createHarness(workflow);
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('succeeded');
    expect(harness.node('email_trigger').output).toHaveProperty('subject');
    expect(harness.node('email_classify').input).toEqual(harness.node('email_trigger').output);
    expect(harness.node('email_route').input).toEqual(harness.node('email_classify').output);
    expect(harness.node('email_route').output?.matched).toBe(true);
    expect(harness.node('email_send').status).toBe('succeeded');
    expect(harness.node('email_send').input).toMatchObject({
      category: 'billing',
      priority: 'normal',
      matched: true,
    });
  });

  it('reports an unsupported trigger instead of completing an empty execution', async () => {
    const workflow = structuredClone(fixtureWorkflows[3]);
    workflow.nodes[0].type = 'webhook';
    const harness = createHarness(workflow);
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('failed');
    expect(harness.execution.nodeRuns.every((run) => run.status === 'skipped')).toBe(true);
    expect(
      harness.execution.events.some(
        (event) => event.level === 'error' && event.message.includes('coming soon'),
      ),
    ).toBe(true);
  });

  it('records calculator errors and skips later steps', async () => {
    const workflow = structuredClone(fixtureWorkflows[3]);
    workflow.nodes[1].type = 'calculator';
    workflow.nodes[1].config.expression = '12 / 0';
    const harness = createHarness(workflow);
    await finishSimulation(harness);

    expect(harness.execution.status).toBe('failed');
    expect(harness.node('doc_parse')).toMatchObject({ status: 'failed', output: null });
    expect(harness.node('doc_parse').error).toContain('division by zero');
    expect(harness.node('doc_llm').status).toBe('skipped');
    expect(harness.node('doc_end').status).toBe('skipped');
    expect(harness.execution.duration).toBe(
      harness.execution.nodeRuns.reduce((sum, run) => sum + run.duration, 0),
    );
    expect(
      harness.execution.events.some(
        (event) => event.level === 'error' && event.nodeId === 'doc_parse',
      ),
    ).toBe(true);
  });

  it('evaluates numeric and text comparisons without treating a string threshold lexically', () => {
    const condition = structuredClone(
      fixtureWorkflows[0].nodes.find((node) => node.type === 'condition')!,
    );
    condition.config = { variable: 'amount', operator: 'greater_than', value: '50000' };
    expect(evaluateCondition(condition, { amount: 60000 })).toBe(true);
    expect(evaluateCondition(condition, { amount: 40000 })).toBe(false);
    condition.config = { variable: 'category', operator: 'equals', value: 'billing' };
    expect(evaluateCondition(condition, { category: 'billing' })).toBe(true);
    expect(evaluateCondition(condition, { category: 'support' })).toBe(false);
    condition.config = { variable: 'invoice.amount', operator: 'less_than', value: '50000' };
    expect(evaluateCondition(condition, { invoice: { amount: 40000 } })).toBe(true);
  });
});

describe('demo fixture consistency', () => {
  it('keeps workflow metrics aligned with the final execution records', () => {
    for (const workflow of fixtureWorkflows) {
      const executions = fixtureExecutions.filter(
        (execution) => execution.workflowId === workflow.id,
      );
      expect(workflow.totalRuns).toBe(executions.length);
      expect(workflow.successRate).toBe(
        Math.round(
          (executions.filter((execution) => execution.status === 'succeeded').length /
            executions.length) *
            100,
        ),
      );
      expect(workflow.lastRun).toBe(executions[0].startedAt);
    }
  });

  it('links all approval states to the corresponding execution and branch outcome', () => {
    expect(new Set(fixtureApprovals.map((approval) => approval.status))).toEqual(
      new Set(['pending', 'approved', 'rejected', 'expired']),
    );
    for (const approval of fixtureApprovals) {
      const execution = fixtureExecutions.find(
        (execution) => execution.id === approval.executionId,
      )!;
      const node = execution.graph.nodes.find((node) => node.id === approval.nodeId)!;
      const run = execution.nodeRuns.find((run) => run.nodeId === approval.nodeId)!;
      expect(node.type).toBe('approval');
      expect(approval.workflowId).toBe(execution.workflowId);
      expect(approval.data).toEqual(run.input);
      expect(approval.requestedAt).toBe(run.startedAt);
      if (approval.status === 'pending') {
        expect(execution.status).toBe('waiting_approval');
        expect(run.status).toBe('waiting_approval');
      } else if (approval.status === 'expired') {
        expect(execution.status).toBe('cancelled');
        expect(run.status).toBe('skipped');
      } else {
        expect(run.status).toBe('succeeded');
        expect(run.output?.decision).toBe(approval.status);
        const takenEdge = execution.graph.edges.find(
          (edge) => edge.source === run.nodeId && edge.sourceHandle === approval.status,
        )!;
        expect(execution.nodeRuns.find((run) => run.nodeId === takenEdge.target)?.status).toBe(
          'succeeded',
        );
        if (approval.status === 'rejected')
          expect(execution.nodeRuns.find((run) => run.nodeId === 'invoice_store')?.status).toBe(
            'skipped',
          );
      }
    }
    const waiting = fixtureExecutions.filter(
      (execution) => execution.status === 'waiting_approval',
    );
    expect(waiting).toHaveLength(1);
    expect(
      waiting.every((execution) =>
        fixtureApprovals.some(
          (approval) => approval.executionId === execution.id && approval.status === 'pending',
        ),
      ),
    ).toBe(true);
  });

  it('uses coherent node outputs, duration totals, timestamps, and log references', () => {
    for (const execution of fixtureExecutions) {
      expect(execution.duration).toBe(
        execution.nodeRuns.reduce((sum, run) => sum + run.duration, 0),
      );
      for (const run of execution.nodeRuns) {
        if (run.status === 'succeeded') {
          expect(run.output).not.toBeNull();
          expect(run.startedAt).toBeDefined();
          expect(run.endedAt).toBeDefined();
        }
        if (run.status !== 'succeeded') expect(run.tokens).toBeUndefined();
        if (run.endedAt)
          expect(+new Date(run.endedAt)).toBeGreaterThanOrEqual(+new Date(run.startedAt!));
      }
      for (const event of execution.events) {
        expect(+new Date(event.timestamp)).toBeGreaterThanOrEqual(+new Date(execution.startedAt));
        if (event.nodeId)
          expect(execution.graph.nodes.some((node) => node.id === event.nodeId)).toBe(true);
      }
      if (execution.status === 'succeeded')
        expect(
          execution.nodeRuns.some((run) =>
            ['pending', 'running', 'waiting_approval', 'failed'].includes(run.status),
          ),
        ).toBe(false);
      if (execution.status === 'failed')
        expect(execution.nodeRuns.filter((run) => run.status === 'failed')).toHaveLength(1);
    }
  });
});
