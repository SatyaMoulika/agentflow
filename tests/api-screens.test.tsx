import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactElement } from 'react';
import { client } from '../src/api/client';
import AuthPage from '../src/api/AuthPage';
import Editor from '../src/api/Editor';
import { CreateWorkflow, Dashboard, WorkflowList, RunView, Unavailable } from '../src/api/pages';
import { starterDefinition } from '../src/api/graph';
import HttpConnections, {
  AgentConnectionPicker,
  PlannerConnectionPicker,
} from '../src/api/Connections';
import { ProviderDetails } from '../src/api/ProviderDetails';
import GmailConnections, { GmailConnectionSelector } from '../src/api/GmailConnections';
import GitHubConnections from '../src/api/GitHubConnections';
import { RunForm } from '../src/api/RunWorkflow';
import { IntegrationHeading } from '../src/api/IntegrationHeading';
const user = {
  id: '12345678-1234-1234-1234-123456789abc',
  email: 'actual@example.com',
  display_name: 'Actual user',
  is_active: true,
};
const id = '12345678-1234-1234-1234-123456789def';
const empty = { items: [], total: 0, page: 1, page_size: 25 };
function render(
  path: string,
  element: ReactElement,
  setup?: (cache: QueryClient) => void,
  route = path,
) {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  setup?.(cache);
  const router = createMemoryRouter([{ path: route, element }], { initialEntries: [path] });
  return renderToString(
    <QueryClientProvider client={cache}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}
function authenticated() {
  vi.spyOn(client, 'snapshot').mockReturnValue({ status: 'authenticated', user, generation: 1 });
}
afterEach(() => vi.restoreAllMocks());
describe('routed real API views', () => {
  it.each(['gmail', 'github', 'groq', 'http'] as const)(
    'shows a decorative service icon with a readable heading for %s',
    (service) => {
      const markup = render('/integrations', <IntegrationHeading service={service} />);
      expect(markup).toContain('aria-hidden="true"');
      expect(markup).toContain('<svg');
      expect(markup).toContain(
        `<h2>${{ gmail: 'Gmail', github: 'GitHub', groq: 'Groq', http: 'HTTP connections' }[service]}</h2>`,
      );
    },
  );
  it('shows saved workflow input fields on the run page', () => {
    authenticated();
    const definition = starterDefinition();
    definition.metadata = {
      agentflow_input_fields: [
        { name: 'message', label: 'Review request', type: 'text', required: true },
      ],
    };
    const markup = render(
      `/workflows/${id}/run`,
      <RunForm
        workflow={{
          id,
          owner_id: user.id,
          name: 'Review PRs',
          description: '',
          status: 'draft',
          current_version_id: id,
          current_version_number: 1,
          created_at: '',
          updated_at: '',
          version: {
            id,
            workflow_id: id,
            version_number: 1,
            definition,
            created_at: '',
            created_by: user.id,
          },
        }}
      />,
    );
    expect(markup).toContain('Run Review PRs');
    expect(markup).toContain('Review request');
    expect(markup).toContain('Run saved version');
  });
  it('offers GitHub repository reads and clearly describes the scope', () => {
    authenticated();
    const markup = render('/integrations', <GitHubConnections />);
    expect(markup).toContain('Repository owner');
    expect(markup).toContain('Repository name');
    expect(markup).toContain('Create GitHub connection');
    expect(markup).toContain('No automatic triggers or GitHub writes');
  });
  it('shows connected Gmail state without claiming mailbox automation is available', () => {
    authenticated();
    const markup = render('/integrations', <GmailConnections />, (cache) =>
      cache.setQueryData(
        [user.id, 1, 'gmail-connections'],
        [{ id, created_at: '2026-11-13T00:00:00Z', revoked_at: null }],
      ),
    );
    expect(markup).toContain('Connect Gmail');
    expect(markup).toContain('Connected');
    expect(markup).toContain('Disconnect');
    expect(markup).toContain('still being built');
  });
  it('discloses that Gmail text is stored and can be sent to Groq', () => {
    authenticated();
    const markup = render(
      '/workflows/new',
      <GmailConnectionSelector value="" disabled={false} onChange={() => {}} />,
      (cache) => cache.setQueryData([user.id, 1, 'gmail-connections'], []),
    );
    expect(markup).toContain('stored in run history');
    expect(markup).toContain('sent to Groq');
  });
  it.each(['paused', 'running', 'completed', 'cancelled'])(
    'shows saved agent state and offers continuation only for a paused invocation (%s)',
    (checkpointStatus) => {
      authenticated();
      const definition = starterDefinition();
      definition.nodes.splice(1, 0, {
        id: 'agent',
        type: 'agent',
        config: { instruction: 'Calculate.', input_field: 'message' },
      });
      const markup = render(
        `/executions/${id}`,
        <RunView />,
        (cache) =>
          cache.setQueryData([user.id, 1, 'run', id], {
            id,
            workflow_id: id,
            workflow_version_id: id,
            status: ['paused', 'running'].includes(checkpointStatus)
              ? 'running'
              : checkpointStatus === 'completed'
                ? 'succeeded'
                : 'cancelled',
            max_attempts: 1,
            parent_run_id: null,
            input: {},
            output: null,
            error_code: null,
            created_at: '2026-11-11T00:00:00Z',
            started_at: '2026-11-11T00:00:00Z',
            completed_at: null,
            event_sequence: 0,
            version: { id, version_number: 1, definition },
            node_runs: [
              {
                id: 'attempt',
                node_id: 'agent',
                attempt_number: 1,
                status: 'running',
                input: {},
                output: null,
                error_code: null,
                checkpoint: {
                  thread_id: 'saved-thread',
                  status: checkpointStatus,
                  checkpoint_id: id,
                  resume_count: 1,
                },
              },
            ],
          }),
        '/executions/:executionId',
      );
      expect(markup).toContain('saved-thread');
      expect(markup).not.toContain('Retry full workflow');
      if (checkpointStatus === 'paused') {
        expect(markup).toContain('Continue agent');
        expect(markup).toContain('Paused after a saved tool result');
      } else expect(markup).not.toContain('Continue agent');
    },
  );
  it('starts agent HTTP access empty and discloses fetched response sharing', () => {
    authenticated();
    const markup = render(
      '/workflows/new',
      <AgentConnectionPicker value={[]} disabled={false} onChange={() => {}} />,
      (cache) =>
        cache.setQueryData([user.id, 1, 'connections', 1], {
          ...empty,
          total: 1,
          items: [
            {
              id,
              name: 'Selected status',
              endpoint_url: 'https://api.example.com/status',
              revoked_at: null,
            },
          ],
        }),
    );
    expect(markup.replaceAll('<!-- -->', '')).toContain('0 selected');
    expect(markup).toContain('fetched JSON responses are sent to Groq');
    expect(markup).toContain('Credentials stay on the server');
    expect(markup).not.toContain('checked=""');
  });
  it('allows a missing or revoked agent connection selection to be removed', () => {
    authenticated();
    const markup = render(
      '/workflows/new',
      <AgentConnectionPicker value={[id]} disabled={false} onChange={() => {}} />,
      (cache) => cache.setQueryData([user.id, 1, 'connections', 1], empty),
    );
    expect(markup).toContain(id);
    expect(markup).toContain('Remove selection');
    expect(markup).toContain('Missing or revoked selections must be removed');
  });
  it('shows agent stop details and usage without offering full-workflow retry', () => {
    authenticated();
    const definition = starterDefinition();
    definition.nodes.splice(1, 0, {
      id: 'agent',
      type: 'agent',
      config: { instruction: 'Calculate.', input_field: 'message', max_tool_rounds: 1 },
    });
    const markup = render(
      `/executions/${id}`,
      <RunView />,
      (cache) =>
        cache.setQueryData([user.id, 1, 'run', id], {
          id,
          workflow_id: id,
          workflow_version_id: id,
          status: 'failed',
          max_attempts: 3,
          parent_run_id: null,
          input: {},
          output: null,
          error_code: 'EXECUTION_FAILED',
          created_at: '2026-11-10T00:00:00Z',
          started_at: '2026-11-10T00:00:00Z',
          completed_at: '2026-11-10T00:00:01Z',
          event_sequence: 0,
          version: { id, version_number: 1, definition },
          node_runs: [
            {
              id: 'attempt',
              node_id: 'agent',
              attempt_number: 1,
              status: 'failed',
              input: {},
              output: null,
              duration_ms: 12,
              error_code: 'EXECUTION_FAILED',
              agent: {
                tool_rounds: 1,
                failure_reason: 'iteration_limit',
                provider_calls: [
                  {
                    provider: 'groq',
                    requested_model: 'requested',
                    model: 'reported',
                    duration_ms: 12,
                    usage: { total_tokens: 6 },
                  },
                ],
              },
            },
          ],
        }),
      '/executions/:executionId',
    );
    expect(markup.replaceAll('<!-- -->', '')).toContain('Agent stopped: iteration_limit');
    expect(markup.replaceAll('<!-- -->', '')).toContain('Completed tool calls: 1');
    expect(markup.replaceAll('<!-- -->', '')).toContain('total 6');
    expect(markup).not.toContain('Retry full workflow');
  });
  it('requires explicit planner selection and makes metadata sharing visible', () => {
    authenticated();
    const markup = render(
      '/workflows/new',
      <form>
        <PlannerConnectionPicker value={[]} disabled={false} onChange={() => {}} />
      </form>,
      (cache) =>
        cache.setQueryData([user.id, 1, 'connections', 1], {
          ...empty,
          total: 1,
          items: [
            {
              id,
              name: 'Status endpoint',
              endpoint_url: 'https://api.example.com/status',
              revoked_at: null,
            },
          ],
        }),
    );
    expect(markup.replaceAll('<!-- -->', '')).toContain('0 selected');
    expect(markup).toContain('Their names and endpoint URLs are sent to Groq');
    expect(markup).not.toContain('checked=""');
    expect(markup).toContain('type="button"');
  });
  it('distinguishes missing usage from reported zero tokens', () => {
    const metadata = {
      provider: 'groq' as const,
      requested_model: 'requested',
      model: 'reported',
      duration_ms: 12,
    };
    expect(render('/integrations', <ProviderDetails metadata={metadata} />)).toContain(
      'Token usage was not reported',
    );
    const markup = render(
      '/integrations',
      <ProviderDetails metadata={{ ...metadata, usage: { total_tokens: 0 } }} />,
    );
    expect(markup.replaceAll('<!-- -->', '')).toContain('total 0');
    expect(markup.replaceAll('<!-- -->', '')).toContain('input unknown');
  });
  it('renders real HTTP connection metadata and never fabricates credentials or calls endpoints', () => {
    authenticated();
    const request = vi.spyOn(client, 'request');
    const markup = render('/integrations', <HttpConnections />, (cache) =>
      cache.setQueryData([user.id, 1, 'connections', 1], {
        ...empty,
        total: 1,
        items: [
          {
            id,
            name: 'Public status',
            endpoint_url: 'https://api.example.com/status',
            auth_type: 'bearer',
            revoked_at: null,
            created_at: '2026-11-06T00:00:00Z',
          },
        ],
      }),
    );
    expect(markup).toContain('Public status');
    expect(markup).toContain('Revoke connection');
    expect(markup).toContain('Create connection');
    expect(markup).toContain('Workflow input is not sent');
    expect(markup).not.toContain('private-credential');
    expect(request).not.toHaveBeenCalled();
  });
  it('offers real sign in and registration without demo credentials', () => {
    vi.spyOn(client, 'snapshot').mockReturnValue({
      status: 'anonymous',
      user: null,
      generation: 0,
    });
    const login = render('/login', <AuthPage />);
    expect(login).toContain('Welcome back');
    expect(login).toContain('Create an account');
    expect(login).not.toContain('demo password');
    const signup = render('/register', <AuthPage registration />);
    expect(signup).toContain('Display name');
    expect(signup).toContain('Create account');
  });
  it('renders a true empty workflow state from the server page', () => {
    authenticated();
    const markup = render('/workflows', <WorkflowList />, (cache) =>
      cache.setQueryData([user.id, 1, 'workflows', 1, '', ''], empty),
    );
    expect(markup).toContain('No matching workflows');
    expect(markup).toContain('Create workflow');
    expect(markup).not.toContain('Invoice Processing');
  });
  it('offers prompt generation and manual creation without submitting automatically', () => {
    authenticated();
    const request = vi.spyOn(client, 'request');
    const markup = render('/workflows/new', <CreateWorkflow />);
    expect(markup).toContain('Generate with AI');
    expect(markup).toContain('Generate proposal');
    expect(markup).toContain('Create manually');
    expect(request).not.toHaveBeenCalled();
  });
  it('uses server totals and avoids invented success rates on the overview', () => {
    authenticated();
    const markup = render('/dashboard', <Dashboard />, (cache) => {
      cache.setQueryData([user.id, 1, 'workflows', 'overview'], { ...empty, total: 2 });
      cache.setQueryData([user.id, 1, 'runs', 'overview'], empty);
    });
    expect(markup).toContain('Unarchived workflows');
    expect(markup).toContain('>2</strong>');
    expect(markup).toContain('Your first run starts here');
    expect(markup).not.toContain('Success rate');
  });
  it('shows explicit unavailable states instead of simulated approvals or connections', () => {
    expect(render('/approvals', <Unavailable kind="Approvals" />)).toContain(
      'Approvals are not available yet',
    );
    expect(render('/integrations', <Unavailable kind="Integrations" />)).not.toContain(
      'Connect Slack',
    );
  });
  it('renders the real editor with server node contracts and snake_case definition', () => {
    authenticated();
    const definition = starterDefinition();
    const markup = render(
      `/workflows/${id}/edit`,
      <Editor />,
      (cache) => {
        cache.setQueryData([user.id, 1, 'workflow', id, undefined], {
          id,
          name: 'Stored workflow',
          description: '',
          status: 'draft',
          current_version_id: id,
          current_version_number: 1,
          version: { id, version_number: 1, definition },
        });
        cache.setQueryData([user.id, 1, 'catalog'], {
          schema_version: '1.0',
          items: ['manual', 'transform', 'condition', 'calculator', 'merge', 'end'].map((type) => ({
            type,
            name: type,
            description: '',
            execution_ready: true,
            config_schema: {},
            output_handles:
              type === 'end' ? [] : type === 'condition' ? ['true', 'false'] : ['default'],
          })),
        });
      },
      '/workflows/:workflowId/edit',
    );
    expect(markup).toContain('Node library');
    expect(markup).toContain('react-flow');
    expect(markup).toContain('Run saved version');
    expect(markup).toContain('Propose changes with AI');
    expect(markup).toContain('Generate edit proposal');
    expect(markup).toContain('value="Stored workflow"');
    expect(markup).not.toContain('Workflow copilot');
  });
  it('displays persisted run values without fabricated traces, logs or token usage', () => {
    authenticated();
    const markup = render(
      `/executions/${id}`,
      <RunView />,
      (cache) =>
        cache.setQueryData([user.id, 1, 'run', id], {
          id,
          workflow_id: id,
          workflow_version_id: id,
          max_attempts: 1,
          parent_run_id: null,
          status: 'succeeded',
          created_at: '2026-11-03T00:00:00Z',
          completed_at: '2026-11-03T00:00:01Z',
          started_at: '2026-11-03T00:00:00Z',
          input: { BusinessKey: 12 },
          output: { BusinessKey: 12 },
          error_code: null,
          node_runs: [],
          version: { id, version_number: 1, definition: starterDefinition() },
        }),
      '/executions/:executionId',
    );
    expect(markup).toContain('BusinessKey');
    expect(markup).toContain('No simulated telemetry');
    expect(markup).not.toContain('Tokens used');
    expect(markup).toContain('View saved definition');
  });
  it('renders persisted execution events in sequence order', () => {
    authenticated();
    const markup = render(
      `/executions/${id}`,
      <RunView />,
      (cache) => {
        cache.setQueryData([user.id, 1, 'run', id], {
          id,
          workflow_id: id,
          workflow_version_id: id,
          max_attempts: 1,
          parent_run_id: null,
          status: 'succeeded',
          event_sequence: 2,
          created_at: '2026-11-03T00:00:00Z',
          completed_at: '2026-11-03T00:00:01Z',
          started_at: '2026-11-03T00:00:00Z',
          input: {},
          output: {},
          error_code: null,
          node_runs: [],
          version: { id, version_number: 1, definition: starterDefinition() },
        });
        cache.setQueryData([user.id, 1, 'run-events', id, 0], {
          items: [
            {
              sequence: 1,
              node_run_id: null,
              event_type: 'run.created',
              payload: { status: 'queued' },
              created_at: '2026-11-03T00:00:00Z',
            },
            {
              sequence: 2,
              node_run_id: null,
              event_type: 'run.status_changed',
              payload: { from_status: 'queued', to_status: 'running' },
              created_at: '2026-11-03T00:00:01Z',
            },
          ],
          next_after_sequence: 2,
        });
      },
      '/executions/:executionId',
    );
    expect(markup).toContain('Execution events');
    expect(markup).toContain('Execution created');
    expect(markup).toContain('Execution running');
    expect(markup.indexOf('Execution created')).toBeLessThan(markup.indexOf('Execution running'));
  });
});

it('keeps an explicitly selected snapshot read-only even when it is the current version', () => {
  authenticated();
  const markup = render(
    `/workflows/${id}/edit?version_id=${id}`,
    <Editor />,
    (cache) => {
      cache.setQueryData([user.id, 1, 'workflow', id, id], {
        id,
        name: 'Saved snapshot',
        description: '',
        status: 'draft',
        current_version_id: id,
        current_version_number: 1,
        version: { id, version_number: 1, definition: starterDefinition() },
      });
      cache.setQueryData([user.id, 1, 'catalog'], { schema_version: '1.0', items: [] });
    },
    '/workflows/:workflowId/edit',
  );
  expect(markup).toContain('Saved version snapshots are read-only');
  expect(markup).toContain('Open current definition');
});

it.each(['queued', 'running', 'waiting_approval', 'failed', 'cancelled', 'succeeded'])(
  'shows only appropriate commands for a %s execution',
  (status) => {
    authenticated();
    const markup = render(
      `/executions/${id}`,
      <RunView />,
      (cache) =>
        cache.setQueryData([user.id, 1, 'run', id], {
          id,
          workflow_id: id,
          workflow_version_id: id,
          max_attempts: 3,
          parent_run_id: id,
          status,
          execution_mode: 'background',
          created_at: '2026-11-04T00:00:00Z',
          completed_at: null,
          started_at: null,
          input: {},
          output: null,
          error_code: null,
          node_runs: [],
          version: { id, version_number: 1, definition: starterDefinition() },
        }),
      '/executions/:executionId',
    );
    expect(markup.includes('Cancel execution')).toBe(
      ['queued', 'running', 'waiting_approval'].includes(status),
    );
    expect(markup.includes('Retry full workflow')).toBe(['failed', 'cancelled'].includes(status));
    expect(markup.replace(/<!--.*?-->/g, '')).toContain('Maximum attempts per node: 3');
    expect(markup).toContain('Original execution');
    expect(markup).toContain('Background execution');
    expect(markup.includes('This page updates automatically')).toBe(
      ['queued', 'running'].includes(status),
    );
  },
);

it('explains a scheduled retry and preserves the failed attempt history', () => {
  authenticated();
  const markup = render(
    `/executions/${id}`,
    <RunView />,
    (cache) =>
      cache.setQueryData([user.id, 1, 'run', id], {
        id,
        workflow_id: id,
        workflow_version_id: id,
        status: 'running',
        execution_mode: 'background',
        max_attempts: 3,
        parent_run_id: null,
        created_at: '2026-11-06T00:00:00Z',
        started_at: '2026-11-06T00:00:00Z',
        completed_at: null,
        input: {},
        output: null,
        error_code: null,
        next_retry_at: '2026-11-06T00:00:05Z',
        retry_node_id: 'select',
        next_retry_attempt: 2,
        version: { id, version_number: 1, definition: starterDefinition() },
        node_runs: [
          {
            id,
            node_id: 'select',
            attempt_number: 1,
            status: 'failed',
            error_code: 'INTERNAL_FAILURE',
            duration_ms: 1,
            input: {},
            output: null,
            started_at: '2026-11-06T00:00:00Z',
            completed_at: '2026-11-06T00:00:01Z',
            retry: {
              scheduled_at: '2026-11-06T00:00:01Z',
              due_at: '2026-11-06T00:00:05Z',
              resumed_at: null,
              cancelled_at: null,
            },
          },
        ],
      }),
    '/executions/:executionId',
  ).replace(/<!--.*?-->/g, '');
  expect(markup).toContain('Waiting to retry select (attempt 2)');
  expect(markup).toContain('Retry scheduled for');
  expect(markup).toContain('INTERNAL_FAILURE');
  expect(markup).toContain('Cancel execution');
  expect(markup).not.toContain('Executing the saved workflow.');
});

it.each(['gmail_read', 'http', 'agent'])(
  'does not offer full-workflow retry for a failed %s workflow',
  (type) => {
    authenticated();
    const definition = starterDefinition();
    definition.nodes.splice(1, 0, { id: 'external', type, config: {} });
    definition.edges = [
      { id: 'first', source: 'start', target: 'external', source_handle: 'default' },
      { id: 'last', source: 'external', target: 'finish', source_handle: 'default' },
    ];
    const markup = render(
      `/executions/${id}`,
      <RunView />,
      (cache) =>
        cache.setQueryData([user.id, 1, 'run', id], {
          id,
          workflow_id: id,
          workflow_version_id: id,
          status: 'failed',
          max_attempts: 1,
          parent_run_id: null,
          created_at: '2026-11-19T00:00:00Z',
          completed_at: null,
          started_at: null,
          input: {},
          output: null,
          error_code: 'CONNECTION_UNAVAILABLE',
          node_runs: [],
          version: { id, version_number: 1, definition },
        }),
      '/executions/:executionId',
    );
    expect(markup).not.toContain('Retry full workflow');
    expect(markup).toContain('Full-workflow retry is unavailable');
  },
);
