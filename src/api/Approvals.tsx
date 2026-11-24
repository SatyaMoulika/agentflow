import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Button, EmptyState, JsonViewer, PageHeader } from '../components/ui';
import { api } from './client';
import { Failure, Pages, Pending } from './common';
import { date } from './format';
import { useScope } from './session';
import type { ApprovalStatus } from './types';

export function Approvals() {
  const scope = useScope();
  const [search] = useSearchParams();
  const runId = search.get('run_id') || undefined;
  const [status, setStatus] = useState<ApprovalStatus>('pending');
  const [page, setPage] = useState(1);
  const rows = useQuery({
    queryKey: [...scope, 'approvals', status, runId, page],
    queryFn: ({ signal }) => api.approvals({ status, run_id: runId, page }, signal),
    refetchInterval: status === 'pending' ? 5000 : false,
  });
  return (
    <div className="api-page">
      <PageHeader
        title="Approvals"
        description="Review requests assigned to you by your saved workflows."
      />
      <section className="card api-panel api-form">
        <p>
          Review the saved input before choosing a branch. Requests expire at the displayed
          deadline.
        </p>
        <label className="label" htmlFor="approval-status">
          Status
        </label>
        <select
          id="approval-status"
          className="input"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value as ApprovalStatus);
            setPage(1);
          }}
        >
          {(['pending', 'approved', 'rejected', 'expired', 'cancelled'] as const).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
        {runId && <Link to="/approvals">Show requests from all executions</Link>}
        {rows.isPending ? (
          <Pending />
        ) : rows.isError ? (
          <Failure error={rows.error} />
        ) : (
          <>
            {rows.data.items.length === 0 && (
              <EmptyState
                title="No matching approvals"
                description="Approval nodes create requests when a workflow reaches them."
              />
            )}
            {rows.data.items.map((row) => (
              <article className="card api-panel" key={row.id}>
                <h2>
                  <Link to={`/approvals/${row.id}`}>{row.title}</Link>
                </h2>
                <p>
                  Status: {row.status} · Expires {date(row.expires_at)}
                </p>
                <Link to={`/executions/${row.workflow_run_id}`}>View execution</Link>
              </article>
            ))}
            <Pages page={page} total={rows.data.total} size={20} onChange={setPage} />
          </>
        )}
      </section>
    </div>
  );
}

export function ApprovalView() {
  const { approvalId = '' } = useParams();
  return <ApprovalReview key={approvalId} approvalId={approvalId} />;
}

function ApprovalReview({ approvalId }: { approvalId: string }) {
  const scope = useScope();
  const cache = useQueryClient();
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const row = useQuery({
    queryKey: [...scope, 'approval', approvalId],
    queryFn: ({ signal }) => api.approval(approvalId, signal),
    refetchInterval: (query) => (query.state.data?.status === 'pending' ? 5000 : false),
  });
  async function decide(decision: 'approved' | 'rejected') {
    setBusy(true);
    setError(null);
    try {
      await api.decideApproval(approvalId, decision, note || null);
    } catch (failure) {
      setError(failure);
    } finally {
      await Promise.all([
        row.refetch(),
        cache.invalidateQueries({ queryKey: [...scope, 'approvals'] }),
        cache.invalidateQueries({ queryKey: [...scope, 'runs'] }),
        cache.invalidateQueries({ queryKey: [...scope, 'run', row.data?.workflow_run_id] }),
      ]);
      setBusy(false);
    }
  }
  if (row.isPending) return <Pending />;
  if (row.isError) return <Failure error={row.error} />;
  const data = row.data;
  return (
    <div className="api-page">
      <PageHeader title={data.title} description={`Approval ${data.status}`} />
      <section className="card api-panel api-form">
        <p>
          Expires {date(data.expires_at)}. A decision continues its selected branch on the saved
          workflow version.
        </p>
        <Link to={`/executions/${data.workflow_run_id}`}>View execution and saved workflow</Link>
        <h2>Input to review</h2>
        <JsonViewer data={data.input} />
        {error ? (
          <>
            <Failure error={error} />
            <p>Check the latest status before trying another decision.</p>
          </>
        ) : null}
        {data.status === 'pending' ? (
          <>
            <label className="label" htmlFor="approval-note">
              Decision note (optional)
            </label>
            <textarea
              id="approval-note"
              className="input"
              value={note}
              maxLength={2000}
              disabled={busy}
              onChange={(event) => setNote(event.target.value)}
            />
            <div className="api-actions">
              <Button variant="primary" disabled={busy} onClick={() => void decide('approved')}>
                Approve
              </Button>
              <Button disabled={busy} onClick={() => void decide('rejected')}>
                Reject
              </Button>
            </div>
          </>
        ) : (
          <>
            <p>
              Request {data.status}
              {data.resolved_at ? ` · ${date(data.resolved_at)}` : ''}.
            </p>
            {data.note && <p>{data.note}</p>}
          </>
        )}
        <Button disabled={busy} onClick={() => void row.refetch()}>
          Refresh status
        </Button>
        <Link to="/approvals">Back to approvals</Link>
      </section>
    </div>
  );
}
