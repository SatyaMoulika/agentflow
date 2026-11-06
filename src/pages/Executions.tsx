import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Activity,
  ArrowDownToLine,
  ArrowUpRight,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Layers3,
  RotateCcw,
  SlidersHorizontal,
} from 'lucide-react';
import { Badge, Button, EmptyState, PageHeader, SearchInput } from '../components/ui';
import { useAppStore } from '../stores/useAppStore';
import { formatDuration, relativeTime } from '../lib/utils';
import './observability.css';

export default function Executions() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const executions = useAppStore((s) => s.executions);
  const workflows = useAppStore((s) => s.workflows);
  const runWorkflow = useAppStore((s) => s.runWorkflow);
  const notify = useAppStore((s) => s.notify);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState(params.get('status') || 'all');
  const [workflow, setWorkflow] = useState('all');
  const [period, setPeriod] = useState('all');
  const [sort, setSort] = useState('newest');
  const [page, setPage] = useState(1);
  const perPage = 10;
  const [now] = useState(() => Date.now());

  const filtered = useMemo(
    () =>
      executions
        .filter((execution) => {
          const matchesSearch = `${execution.workflowName} ${execution.id} ${execution.traceId}`
            .toLowerCase()
            .includes(search.toLowerCase());
          const matchesPeriod =
            period === 'all' ||
            now - new Date(execution.startedAt).getTime() <= Number(period) * 86400000;
          return (
            matchesSearch &&
            matchesPeriod &&
            (status === 'all' || execution.status === status) &&
            (workflow === 'all' || execution.workflowId === workflow)
          );
        })
        .sort((a, b) =>
          sort === 'duration'
            ? b.duration - a.duration
            : sort === 'oldest'
              ? +new Date(a.startedAt) - +new Date(b.startedAt)
              : +new Date(b.startedAt) - +new Date(a.startedAt),
        ),
    [executions, search, status, workflow, period, sort, now],
  );
  const pages = Math.max(1, Math.ceil(filtered.length / perPage));
  const safePage = Math.min(page, pages);
  const visible = filtered.slice((safePage - 1) * perPage, safePage * perPage);
  const succeeded = executions.filter((e) => e.status === 'succeeded').length;
  const completed = executions.filter((e) => ['succeeded', 'failed'].includes(e.status));
  const average = completed.length
    ? completed.reduce((sum, e) => sum + e.duration, 0) / completed.length
    : 0;

  function exportExecutions() {
    const rows = [
      ['Execution ID', 'Workflow', 'Status', 'Started', 'Duration (ms)', 'Trigger'],
      ...filtered.map((e) => [
        e.id,
        e.workflowName,
        e.status,
        e.startedAt,
        String(e.duration),
        e.trigger,
      ]),
    ];
    const csv = rows
      .map((row) => row.map((value) => `"${value.replaceAll('"', '""')}"`).join(','))
      .join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = 'agentflow-executions.csv';
    link.click();
    URL.revokeObjectURL(url);
    notify('Execution history exported.', 'success');
  }

  function retry(workflowId: string) {
    if (!workflows.some((w) => w.id === workflowId)) {
      notify('The workflow for this execution is no longer available.', 'error');
      return;
    }
    const id = runWorkflow(workflowId);
    if (id) navigate(`/executions/${id}`);
  }

  return (
    <div className="obs-page">
      <PageHeader
        title="Executions"
        description="Every run. Every decision. The complete picture."
        actions={
          <Button variant="secondary" onClick={exportExecutions}>
            <ArrowDownToLine size={15} /> Export history
          </Button>
        }
      />
      <div className="obs-summary-grid">
        <div className="card obs-summary">
          <span>
            <Activity size={16} /> Total executions
          </span>
          <strong>{executions.length.toLocaleString()}</strong>
          <small>Across all workflows</small>
        </div>
        <div className="card obs-summary">
          <span>
            <span className="obs-status-dot success" /> Success rate
          </span>
          <strong>
            {completed.length ? `${Math.round((succeeded / completed.length) * 100)}%` : '—'}
          </strong>
          <small>{succeeded} successful executions</small>
        </div>
        <div className="card obs-summary">
          <span>
            <Clock3 size={16} /> Average duration
          </span>
          <strong>{completed.length ? formatDuration(Math.round(average)) : '—'}</strong>
          <small>Completed executions</small>
        </div>
        <div className="card obs-summary">
          <span>
            <span className="obs-status-dot running" /> In progress
          </span>
          <strong>
            {
              executions.filter((e) => ['queued', 'running', 'waiting_approval'].includes(e.status))
                .length
            }
          </strong>
          <small>Running or awaiting a decision</small>
        </div>
      </div>
      <div className="card obs-history">
        <div className="obs-table-heading">
          <div>
            <h2>Execution history</h2>
            <span className="muted">Follow the trail from trigger to outcome.</span>
          </div>
          <span className="obs-demo">
            <span /> Demo data
          </span>
        </div>
        <div className="obs-filters">
          <SearchInput
            value={search}
            onChange={(value) => {
              setSearch(value);
              setPage(1);
            }}
            placeholder="Search workflow or execution ID..."
          />
          <select
            aria-label="Filter by workflow"
            className="input"
            value={workflow}
            onChange={(e) => {
              setWorkflow(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">All workflows</option>
            {workflows.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Filter execution status"
            className="input"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">All statuses</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="running">Running</option>
            <option value="waiting_approval">Waiting for approval</option>
            <option value="queued">Queued</option>
            <option value="cancelled">Cancelled</option>
          </select>
          <select
            aria-label="Filter date range"
            className="input"
            value={period}
            onChange={(e) => {
              setPeriod(e.target.value);
              setPage(1);
            }}
          >
            <option value="all">All time</option>
            <option value="1">Last 24 hours</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
          </select>
          <select
            aria-label="Sort executions"
            className="input"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="duration">Longest duration</option>
          </select>
        </div>
        {filtered.length ? (
          <>
            <div className="obs-table-scroll">
              <table className="obs-table">
                <thead>
                  <tr>
                    <th>Workflow / execution</th>
                    <th>Status</th>
                    <th>Trigger</th>
                    <th>Started</th>
                    <th>Duration</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {visible.map((execution) => (
                    <tr key={execution.id}>
                      <td>
                        <button
                          className="obs-table-link"
                          onClick={() => navigate(`/executions/${execution.id}`)}
                        >
                          <span className="obs-workflow-icon">
                            <Layers3 size={17} />
                          </span>
                          <span>
                            <strong>{execution.workflowName}</strong>
                            <code>{execution.id}</code>
                          </span>
                        </button>
                      </td>
                      <td>
                        <Badge status={execution.status} />
                      </td>
                      <td>
                        <span className="obs-trigger">{execution.trigger}</span>
                      </td>
                      <td>
                        <span title={new Date(execution.startedAt).toLocaleString()}>
                          {relativeTime(execution.startedAt)}
                        </span>
                      </td>
                      <td className="obs-mono">{formatDuration(execution.duration)}</td>
                      <td>
                        <div className="obs-row-actions">
                          {['failed', 'cancelled'].includes(execution.status) && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => retry(execution.workflowId)}
                              title="Retry execution"
                            >
                              <RotateCcw size={14} />
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => navigate(`/executions/${execution.id}`)}
                            title="View execution"
                          >
                            <ArrowUpRight size={16} />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="obs-pagination">
              <span>
                Showing {(safePage - 1) * perPage + 1}–
                {Math.min(safePage * perPage, filtered.length)} of {filtered.length} executions
              </span>
              <div>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setPage(safePage - 1)}
                  disabled={safePage === 1}
                  aria-label="Previous page"
                >
                  <ChevronLeft size={15} />
                </Button>
                <span>
                  Page {safePage} of {pages}
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setPage(safePage + 1)}
                  disabled={safePage === pages}
                  aria-label="Next page"
                >
                  <ChevronRight size={15} />
                </Button>
              </div>
            </div>
          </>
        ) : (
          <EmptyState
            title={
              executions.length ? 'No executions match your filters' : 'Your first run starts here'
            }
            description={
              executions.length
                ? 'Try another search or clear the filters to see more executions.'
                : 'Run a workflow to see its progress, output, and execution trace.'
            }
            action={
              <Button
                variant="secondary"
                onClick={() => {
                  if (!executions.length) navigate('/workflows');
                  else {
                    setSearch('');
                    setStatus('all');
                    setWorkflow('all');
                    setPeriod('all');
                  }
                }}
              >
                {executions.length ? 'Clear filters' : 'Explore workflows'}
              </Button>
            }
          />
        )}
      </div>
      <p className="obs-footnote">
        <SlidersHorizontal size={13} /> This workspace uses simulated executions. No external
        services are called.
      </p>
    </div>
  );
}
