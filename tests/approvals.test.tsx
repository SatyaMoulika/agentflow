import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Approvals, ApprovalView } from '../src/api/Approvals';
import { client } from '../src/api/client';
import type { ApprovalDetail } from '../src/api/types';

const user = { id: 'owner', email: 'owner@example.com', display_name: 'Owner', is_active: true };
const approval: ApprovalDetail = {
  id: 'review',
  workflow_run_id: 'run',
  node_run_id: 'attempt',
  node_id: 'review',
  assigned_to: user.id,
  title: 'Review calculation',
  status: 'pending',
  note: null,
  created_at: '2026-11-23T00:00:00Z',
  expires_at: '2026-11-24T00:00:00Z',
  resolved_at: null,
  input: { CaseKey: { ID: 7 } },
};

function view(status: ApprovalDetail['status']) {
  const cache = new QueryClient();
  vi.spyOn(client, 'snapshot').mockReturnValue({ status: 'authenticated', user, generation: 1 });
  cache.setQueryData([user.id, 1, 'approval', approval.id], { ...approval, status });
  const router = createMemoryRouter(
    [{ path: '/approvals/:approvalId', element: <ApprovalView /> }],
    {
      initialEntries: ['/approvals/review'],
    },
  );
  return renderToString(
    <QueryClientProvider client={cache}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());
describe('real approval review', () => {
  it('shows saved input, deadline, and explicit approve/reject controls', () => {
    const markup = view('pending');
    expect(markup).toContain('Review calculation');
    expect(markup).toContain('CaseKey');
    expect(markup).toContain('Approve</button>');
    expect(markup).toContain('Reject</button>');
    expect(markup).toContain('/executions/run');
    expect(markup).toContain('Decision note (optional)');
  });
  it.each(['approved', 'rejected', 'expired', 'cancelled'] as const)(
    'removes decisions after %s',
    (status) => {
      const markup = view(status);
      expect(markup.replace(/<!--.*?-->/g, '')).toContain(`Request ${status}`);
      expect(markup).not.toContain('Approve</button>');
      expect(markup).not.toContain('Reject</button>');
    },
  );
  it('shows an actual empty queue without simulated requests', () => {
    const cache = new QueryClient();
    vi.spyOn(client, 'snapshot').mockReturnValue({ status: 'authenticated', user, generation: 1 });
    cache.setQueryData([user.id, 1, 'approvals', 'pending', undefined, 1], {
      items: [],
      total: 0,
      page: 1,
      page_size: 20,
    });
    const router = createMemoryRouter([{ path: '/approvals', element: <Approvals /> }], {
      initialEntries: ['/approvals'],
    });
    const markup = renderToString(
      <QueryClientProvider client={cache}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(markup).toContain('No matching approvals');
    expect(markup).not.toContain('Review calculation');
  });
});
