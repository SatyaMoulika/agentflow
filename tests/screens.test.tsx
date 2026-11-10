// @vitest-environment node
import { afterAll, afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import Login from '../src/pages/Login';
import Dashboard from '../src/pages/Dashboard';
import Workflows from '../src/pages/Workflows';
import CreateWorkflow from '../src/pages/CreateWorkflow';
import WorkflowEditor from '../src/pages/WorkflowEditor';
import Executions from '../src/pages/Executions';
import ExecutionDetail from '../src/pages/ExecutionDetail';
import Integrations from '../src/pages/Integrations';
import Approvals from '../src/pages/Approvals';
import Settings from '../src/pages/Settings';
import { useAppStore } from '../src/stores/useAppStore';
import { fixtureApprovals, fixtureExecutions, fixtureWorkflows } from '../src/data/fixtures';

const { storage, originalStorage } = vi.hoisted(() => {
  const values = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage });
  return { storage, originalStorage };
});

const baseline = { ...useAppStore.getInitialState() };

function authenticate(authenticated: boolean) {
  // Zustand reads getInitialState during SSR. Keep that server snapshot aligned
  // with the test's client state without replacing or mocking the application hook.
  Object.assign(useAppStore.getInitialState(), { authenticated });
  useAppStore.setState({ authenticated });
}

function renderPage(path: string, element: ReactElement, route = path): string {
  const router = createMemoryRouter([{ path: route, element }], { initialEntries: [path] });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  try {
    return renderToString(
      <QueryClientProvider client={client}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
  } finally {
    router.dispose();
    client.clear();
  }
}

function headingText(markup: string): string[] {
  return Array.from(markup.matchAll(/<h[1-6]\b[^>]*>([\s\S]*?)<\/h[1-6]>/g), (match) =>
    match[1]
      .replace(/<[^>]*>/g, '')
      .replace(/&amp;/g, '&')
      .trim(),
  );
}

beforeEach(() => {
  storage.clear();
  Object.assign(useAppStore.getInitialState(), baseline);
  useAppStore.setState(baseline, true);
  authenticate(true);
});

afterEach(() => {
  Object.assign(useAppStore.getInitialState(), baseline);
  useAppStore.setState(baseline, true);
  storage.clear();
});

afterAll(() => {
  if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
  else Reflect.deleteProperty(globalThis, 'localStorage');
});

// These smoke checks exercise module imports, JSX, providers, route parameters,
// and graph hook contexts. Canvas geometry and browser interactions require UI QA.
describe('screen server-render smoke checks', () => {
  it('renders the signed-out demo login form', () => {
    authenticate(false);
    const markup = renderPage('/login', <Login />);
    expect(headingText(markup)).toContain('Welcome to your flow.');
    expect(markup).toContain('Email address');
    expect(markup).toContain('Demo password');
    expect(markup).toContain('Continue with demo workspace');
  });

  it('renders the authenticated dashboard overview', () => {
    expect(useAppStore.getState().authenticated).toBe(true);
    const markup = renderPage('/dashboard', <Dashboard />);
    expect(
      headingText(markup).some((heading) =>
        heading.includes(`Welcome back, ${baseline.settings.name.split(' ')[0]}`),
      ),
    ).toBe(true);
    expect(markup).toContain('Create workflow');
    expect(markup).toContain('Execution activity');
  });

  it.each([
    { path: '/workflows', element: <Workflows />, heading: 'Workflows' },
    { path: '/workflows/new', element: <CreateWorkflow />, heading: 'Create a workflow' },
    { path: '/executions', element: <Executions />, heading: 'Executions' },
    { path: '/integrations', element: <Integrations />, heading: 'Integrations' },
    { path: '/approvals', element: <Approvals />, heading: 'Approvals' },
    { path: '/settings', element: <Settings />, heading: 'Settings' },
  ])('renders $path with its primary heading', ({ path, element, heading }) => {
    const markup = renderPage(path, element);
    expect(headingText(markup)).toContain(heading);
    expect(markup).not.toContain('Unexpected Application Error!');
  });

  it('renders the workflow editor with data-router and React Flow contexts', () => {
    const workflow = fixtureWorkflows[0];
    const markup = renderPage(
      `/workflows/${workflow.id}/edit`,
      <WorkflowEditor />,
      '/workflows/:workflowId/edit',
    );
    expect(markup).toContain('aria-label="Workflow name"');
    expect(markup).toContain(`value="${workflow.name}"`);
    expect(markup).toContain('Node library');
    expect(markup).toContain('react-flow');
    expect(markup).toContain('Workflow copilot');
  });

  it('renders an execution graph and node inspector for the route execution', () => {
    const execution = fixtureExecutions[0];
    const markup = renderPage(
      `/executions/${execution.id}`,
      <ExecutionDetail />,
      '/executions/:executionId',
    );
    expect(headingText(markup)).toContain(execution.workflowName);
    expect(headingText(markup)).toContain('Step details');
    expect(markup).toContain('react-flow');
    expect(markup).toContain('Overview');
    expect(markup).toContain('Trace');
  });

  it('renders the approval detail selected by its route parameter', () => {
    const approval = fixtureApprovals.find((item) => item.status === 'pending')!;
    const markup = renderPage(`/approvals/${approval.id}`, <Approvals />, '/approvals/:approvalId');
    expect(headingText(markup)).toContain(approval.title);
    expect(headingText(markup)).toContain('Request context');
    expect(headingText(markup)).toContain('Input data');
    expect(markup).toContain(approval.workflowName);
  });

  it.each([
    {
      path: '/workflows/missing/edit',
      route: '/workflows/:workflowId/edit',
      element: <WorkflowEditor />,
      heading: 'Workflow not found',
    },
    {
      path: '/executions/missing',
      route: '/executions/:executionId',
      element: <ExecutionDetail />,
      heading: 'Execution not found',
    },
    {
      path: '/approvals/missing',
      route: '/approvals/:approvalId',
      element: <Approvals />,
      heading: 'Approval request not found',
    },
  ])('renders a useful missing-record state for $path', ({ path, route, element, heading }) => {
    const markup = renderPage(path, element, route);
    expect(headingText(markup)).toContain(heading);
    expect(markup).not.toContain('Unexpected Application Error!');
  });
});
