import { describe, expect, it } from 'vitest';
import { fixtureExecutions, fixtureWorkflows } from '../src/data/fixtures';
import { calculateMetrics } from '../src/services/api';
import type { Execution, ExecutionStatus, WorkflowStatus } from '../src/types';

function execution(status: ExecutionStatus, duration: number, index: number): Execution {
  return {
    ...structuredClone(fixtureExecutions[0]),
    id: `metrics-execution-${index}`,
    status,
    duration,
  };
}

describe('dashboard metric calculations', () => {
  it('returns finite zero values for an empty workspace', () => {
    const metrics = calculateMetrics([], []);
    expect(metrics).toEqual({
      totalWorkflows: 0,
      activeWorkflows: 0,
      totalExecutions: 0,
      successRate: 0,
      averageDuration: 0,
      succeeded: 0,
      failed: 0,
      running: 0,
      waiting: 0,
    });
    expect(Object.values(metrics).every(Number.isFinite)).toBe(true);
  });

  it('excludes archived workflows from the total while counting active workflows independently', () => {
    const statuses: WorkflowStatus[] = ['active', 'active', 'draft', 'paused', 'archived'];
    const workflows = statuses.map((status, index) => ({
      ...structuredClone(fixtureWorkflows[index]),
      status,
    }));
    const metrics = calculateMetrics(workflows, []);
    expect(metrics.totalWorkflows).toBe(4);
    expect(metrics.activeWorkflows).toBe(2);
    expect(metrics.totalExecutions).toBe(0);
  });

  it('calculates rate and average duration from completed successes and failures only', () => {
    const executions = [
      execution('succeeded', 1000, 0),
      execution('succeeded', 3000, 1),
      execution('failed', 2000, 2),
      execution('running', 90000, 3),
      execution('queued', 100000, 4),
      execution('waiting_approval', 110000, 5),
      execution('cancelled', 120000, 6),
    ];
    const metrics = calculateMetrics(fixtureWorkflows, executions);
    expect(metrics.totalExecutions).toBe(7);
    expect(metrics.succeeded).toBe(2);
    expect(metrics.failed).toBe(1);
    expect(metrics.running).toBe(2);
    expect(metrics.waiting).toBe(1);
    expect(metrics.successRate).toBeCloseTo(200 / 3);
    expect(metrics.averageDuration).toBe(2000);
    const cancelled = executions.filter((item) => item.status === 'cancelled').length;
    expect(metrics.succeeded + metrics.failed + metrics.running + metrics.waiting + cancelled).toBe(
      metrics.totalExecutions,
    );
  });

  it('avoids dividing by zero when executions exist but none have completed', () => {
    const statuses: ExecutionStatus[] = ['running', 'queued', 'waiting_approval', 'cancelled'];
    const metrics = calculateMetrics(
      [],
      statuses.map((status, index) => execution(status, 50000, index)),
    );
    expect(metrics.totalExecutions).toBe(4);
    expect(metrics.successRate).toBe(0);
    expect(metrics.averageDuration).toBe(0);
    expect(metrics.running).toBe(2);
    expect(metrics.waiting).toBe(1);
    expect(Object.values(metrics).every(Number.isFinite)).toBe(true);
  });

  it('uses fixture execution records consistently without mutating input data', () => {
    const workflows = structuredClone(fixtureWorkflows);
    const executions = structuredClone(fixtureExecutions);
    const before = {
      workflows: structuredClone(workflows),
      executions: structuredClone(executions),
    };
    const metrics = calculateMetrics(workflows, executions);
    const completed = executions.filter((item) => ['succeeded', 'failed'].includes(item.status));
    const succeeded = executions.filter((item) => item.status === 'succeeded');
    expect(metrics.totalWorkflows).toBe(
      workflows.filter((workflow) => workflow.status !== 'archived').length,
    );
    expect(metrics.activeWorkflows).toBe(
      workflows.filter((workflow) => workflow.status === 'active').length,
    );
    expect(metrics.totalExecutions).toBe(executions.length);
    expect(metrics.successRate).toBeCloseTo((succeeded.length / completed.length) * 100);
    expect(metrics.averageDuration).toBeCloseTo(
      completed.reduce((sum, item) => sum + item.duration, 0) / completed.length,
    );
    expect(workflows).toEqual(before.workflows);
    expect(executions).toEqual(before.executions);
  });
});
