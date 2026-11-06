import { date, elapsed } from './format';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { Activity, ArrowRight, GitBranch, Plus, RefreshCw, Workflow } from 'lucide-react';
import { Badge, Button, EmptyState, JsonViewer, PageHeader } from '../components/ui';
import { api } from './client';
import { Failure, Pages, Pending } from './common';
import { starterDefinition } from './graph';
import { useScope, useSession } from './session';
import Canvas from './Canvas';
import type { RunItem, WorkflowProposal } from './types';
export function Dashboard() {
  const scope = useScope();
  const workflows = useQuery({
    queryKey: [...scope, 'workflows', 'overview'],
    queryFn: ({ signal }) => api.workflows({ page_size: 5 }, signal),
  });
  const runs = useQuery({
    queryKey: [...scope, 'runs', 'overview'],
    queryFn: ({ signal }) => api.runs({ page_size: 5 }, signal),
  });
  return (
    <div className="api-page">
      <PageHeader
        title="Overview"
        description="Your saved workflows and actual execution history."
        actions={
          <Button asChild variant="primary">
            <Link to="/workflows/new">
              <Plus size={16} />
              Create workflow
            </Link>
          </Button>
        }
      />
      <div className="api-stats">
        <div className="card api-stat">
          <Workflow />
          <span>Unarchived workflows</span>
          <strong>{workflows.data?.total ?? '—'}</strong>
        </div>
        <div className="card api-stat">
          <Activity />
          <span>Stored executions</span>
          <strong>{runs.data?.total ?? '—'}</strong>
        </div>
      </div>
      {workflows.isError && (
        <Failure error={workflows.error} retry={() => void workflows.refetch()} />
      )}
      {runs.isError && <Failure error={runs.error} retry={() => void runs.refetch()} />}
      <section className="card api-panel">
        <div className="api-section">
          <h2>Recent executions</h2>
          <Link to="/executions">
            View history <ArrowRight size={14} />
          </Link>
        </div>
        {runs.isPending ? (
          <Pending />
        ) : runs.data?.items.length ? (
          <RunTable items={runs.data.items} />
        ) : (
          !runs.isError && (
            <EmptyState
              title="Your first run starts here"
              description="Create a workflow, save its definition and provide your own input."
              action={
                <Button asChild>
                  <Link to="/workflows">Open workflows</Link>
                </Button>
              }
            />
          )
        )}
      </section>
      <section className="card api-panel">
        <h2>Build with supported nodes</h2>
        <p className="muted">
          Generate a proposal with AI, or build with manual, transform, condition, calculator, Groq,
          merge and end nodes. Approvals are not available yet.
        </p>
      </section>
    </div>
  );
}
export function WorkflowList() {
  const scope = useScope();
  const cache = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const records = useQuery({
    queryKey: [...scope, 'workflows', page, q, status],
    queryFn: ({ signal }) => api.workflows({ page, page_size: 12, q, status }, signal),
  });
  async function archive(id: string) {
    if (!window.confirm('Archive this workflow? Its saved versions and runs will be kept.')) return;
    setBusy(id);
    setError(null);
    try {
      await api.archive(id);
      await cache.invalidateQueries({ queryKey: [...scope, 'workflows'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="api-page">
      <PageHeader
        title="Workflows"
        description="Definitions saved in your account."
        actions={
          <Button asChild variant="primary">
            <Link to="/workflows/new">
              <Plus size={16} />
              Create workflow
            </Link>
          </Button>
        }
      />
      <form
        className="api-actions"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
          setQ(search.trim());
        }}
      >
        <input
          className="input"
          aria-label="Search workflow names"
          placeholder="Search workflow names"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          maxLength={200}
        />
        <Button type="submit">Search</Button>
        <select
          className="input"
          aria-label="Workflow status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">Unarchived</option>
          <option value="draft">Draft</option>
          <option value="archived">Archived</option>
        </select>
        <Button type="button" onClick={() => void records.refetch()} aria-label="Refresh workflows">
          <RefreshCw size={16} />
        </Button>
      </form>
      {error !== null && <Failure error={error} />}
      {records.isPending ? (
        <Pending />
      ) : records.isError ? (
        <Failure error={records.error} retry={() => void records.refetch()} />
      ) : (
        <>
          <div className="api-grid">
            {records.data.items.map((item) => (
              <article className="card api-workflow-card" key={item.id}>
                <div className="api-section">
                  <span className="api-node-icon">
                    <GitBranch size={20} />
                  </span>
                  <Badge status={item.status} />
                </div>
                <h2>
                  <Link to={`/workflows/${item.id}/edit`}>{item.name}</Link>
                </h2>
                <p className="muted">{item.description || 'No description'}</p>
                <small>
                  {item.current_version_id ? 'Definition saved' : 'No saved definition'} · Updated{' '}
                  {date(item.updated_at)}
                </small>
                <div className="api-actions">
                  <Button asChild>
                    <Link to={`/workflows/${item.id}/edit`}>Open editor</Link>
                  </Button>
                  <Link to={`/executions?workflow_id=${item.id}`}>Runs</Link>
                  {item.status !== 'archived' && (
                    <Button
                      variant="ghost"
                      disabled={busy === item.id}
                      onClick={() => void archive(item.id)}
                    >
                      Archive
                    </Button>
                  )}
                </div>
              </article>
            ))}
          </div>
          {!records.data.items.length && (
            <EmptyState
              title="No matching workflows"
              description="Create your own workflow or change the search filters."
            />
          )}
          <Pages page={page} size={12} total={records.data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}
export function CreateWorkflow() {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [prompt, setPrompt] = useState('');
  const [proposal, setProposal] = useState<WorkflowProposal | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<unknown>(null);
  const navigate = useNavigate();
  const cache = useQueryClient();
  const scope = useScope();
  async function generateProposal(event: FormEvent) {
    event.preventDefault();
    setGenerating(true);
    setGenerationError(null);
    setProposal(null);
    try {
      setProposal(await api.generateWorkflow(prompt));
    } catch (error) {
      setGenerationError(error);
    } finally {
      setGenerating(false);
    }
  }
  async function saveProposal() {
    if (!proposal?.definition) return;
    setBusy(true);
    setGenerationError(null);
    try {
      const workflow = await api.create(proposal.name, proposal.description, proposal.definition);
      await cache.invalidateQueries({ queryKey: [...scope, 'workflows'] });
      navigate(`/workflows/${workflow.id}/edit`);
    } catch (error) {
      setGenerationError(error);
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const workflow = await api.create(name, description, starterDefinition());
      await cache.invalidateQueries({ queryKey: [...scope, 'workflows'] });
      navigate(`/workflows/${workflow.id}/edit`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="api-page">
      <PageHeader
        title="Create workflow"
        description="Describe what you need, or start with a manual workflow."
      />
      <form className="card api-panel api-form" onSubmit={generateProposal}>
        <h2>Generate with AI</h2>
        <p>
          Your request is sent to Groq and may be sent once more if the proposal fails validation.
          Review the proposal before saving.
        </p>
        <label className="label" htmlFor="workflow-prompt">
          What should the workflow do?
        </label>
        <textarea
          id="workflow-prompt"
          className="input"
          rows={4}
          maxLength={2000}
          required
          value={prompt}
          disabled={generating || busy}
          onChange={(event) => {
            setPrompt(event.target.value);
            setProposal(null);
          }}
          placeholder="Create a workflow that drafts a response to a customer support message."
        />
        <Button
          type="submit"
          variant="primary"
          loading={generating}
          disabled={generating || busy || !prompt.trim()}
        >
          Generate proposal
        </Button>
        {generationError !== null && <Failure error={generationError} />}
      </form>
      {proposal && (
        <section className="card api-panel api-form" aria-live="polite">
          <h2>
            {proposal.status === 'ready' ? 'Review proposal' : 'Cannot generate this workflow yet'}
          </h2>
          <p>{proposal.message}</p>
          {proposal.status === 'ready' && proposal.definition && (
            <>
              <h3>{proposal.name}</h3>
              <p>{proposal.description}</p>
              <p>
                Review the steps and check that they match your request. Validation checks graph
                structure; it does not guarantee the proposal meets your intent.
              </p>
              <ul>
                {proposal.definition.nodes.map((node) => (
                  <li key={node.id}>
                    {node.label || node.id} — {node.type}
                  </li>
                ))}
              </ul>
              <h3>Connections</h3>
              <ul>
                {proposal.definition.edges.map((edge) => (
                  <li key={edge.id}>
                    {edge.source} → {edge.target} ({edge.source_handle || 'default'})
                  </li>
                ))}
              </ul>
              <details>
                <summary>Proposed definition</summary>
                <JsonViewer data={proposal.definition} />
              </details>
              <details>
                <summary>Suggested test input</summary>
                <JsonViewer data={proposal.sample_input} />
              </details>
              <p className="muted">
                Suggested input is not run automatically. Save it if you want to use it later.
              </p>
              <Button
                type="button"
                variant="primary"
                loading={busy}
                disabled={busy || generating}
                onClick={() => void saveProposal()}
              >
                Create from proposal
              </Button>
            </>
          )}
          <small className="muted">
            Generated with {proposal.model}
            {proposal.repair_attempted ? ' after one regeneration' : ''}. No workflow has been saved
            yet.
          </small>
        </section>
      )}
      <form className="card api-panel api-form" onSubmit={submit}>
        <h2>Create manually</h2>
        <label className="label" htmlFor="workflow-name">
          Workflow name
        </label>
        <input
          id="workflow-name"
          className="input"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={busy}
        />
        <label className="label" htmlFor="workflow-description">
          Description
        </label>
        <textarea
          id="workflow-description"
          className="input"
          rows={3}
          maxLength={5000}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          disabled={busy}
        />
        <p className="muted">This creates a saved draft in your account.</p>
        {error !== null && <Failure error={error} />}
        <div className="api-actions">
          <Button asChild>
            <Link to="/workflows">Back</Link>
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={busy || !name.trim()}>
            Create workflow
          </Button>
        </div>
      </form>
    </div>
  );
}
function RunTable({ items }: { items: RunItem[] }) {
  return (
    <div className="api-table-scroll">
      <table className="api-table">
        <thead>
          <tr>
            <th>Workflow / run</th>
            <th>Status</th>
            <th>Version</th>
            <th>Created</th>
            <th>Elapsed</th>
          </tr>
        </thead>
        <tbody>
          {items.map((run) => (
            <tr key={run.id}>
              <td>
                <Link to={`/executions/${run.id}`}>
                  <strong>{run.workflow_name}</strong>
                  <code>{run.id}</code>
                </Link>
              </td>
              <td>
                <Badge status={run.status} />
              </td>
              <td>v{run.version_number}</td>
              <td>{date(run.created_at)}</td>
              <td>{elapsed(run.started_at || run.created_at, run.completed_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function RunList() {
  const scope = useScope();
  const [params, setParams] = useSearchParams();
  const workflow = params.get('workflow_id') || '';
  const [field, setField] = useState(workflow);
  useEffect(() => {
    setField(workflow);
  }, [workflow]);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const runs = useQuery({
    queryKey: [...scope, 'runs', workflow, status, page],
    queryFn: ({ signal }) =>
      api.runs({ workflow_id: workflow, status, page, page_size: 25 }, signal),
  });
  return (
    <div className="api-page">
      <PageHeader
        title="Executions"
        description="Actual stored runs, including their persisted failures and skipped branches."
        actions={
          <Button onClick={() => void runs.refetch()}>
            <RefreshCw size={16} />
            Refresh
          </Button>
        }
      />
      <form
        className="api-actions"
        onSubmit={(e) => {
          e.preventDefault();
          setPage(1);
          setParams(field.trim() ? { workflow_id: field.trim() } : {});
        }}
      >
        <input
          className="input"
          aria-label="Filter by workflow UUID"
          placeholder="Workflow UUID (optional)"
          value={field}
          onChange={(e) => setField(e.target.value)}
        />
        <Button type="submit">Filter</Button>
        <select
          className="input"
          aria-label="Run status"
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setPage(1);
          }}
        >
          <option value="">All statuses</option>
          {['queued', 'running', 'succeeded', 'failed', 'cancelled', 'waiting_approval'].map(
            (value) => (
              <option key={value} value={value}>
                {value.replaceAll('_', ' ')}
              </option>
            ),
          )}
        </select>
      </form>
      {runs.isPending ? (
        <Pending />
      ) : runs.isError ? (
        <Failure error={runs.error} retry={() => void runs.refetch()} />
      ) : (
        <section className="card api-panel">
          {runs.data.items.length ? (
            <RunTable items={runs.data.items} />
          ) : (
            <EmptyState
              title="No matching executions"
              description="Run a saved workflow or change the filters."
              action={
                <Button asChild>
                  <Link to="/workflows">Open workflows</Link>
                </Button>
              }
            />
          )}
          <Pages page={page} total={runs.data.total} size={25} onChange={setPage} />
        </section>
      )}
    </div>
  );
}
export function RunView() {
  const { executionId = '' } = useParams();
  const scope = useScope();
  const navigate = useNavigate();
  const cache = useQueryClient();
  const [commandError, setCommandError] = useState<unknown>(null);
  const [commandBusy, setCommandBusy] = useState('');
  const pendingRetry = useRef<{ id: string; key: string } | null>(null);
  const run = useQuery({
    queryKey: [...scope, 'run', executionId],
    queryFn: ({ signal }) => api.runDetail(executionId, signal),
    refetchInterval: (query) =>
      ['queued', 'running', 'waiting_approval'].includes(query.state.data?.status || '')
        ? 1500
        : false,
  });
  const currentStatus = run.data?.status;
  const scopeUser = scope[0];
  const scopeGeneration = scope[1];
  useEffect(() => {
    if (currentStatus && ['succeeded', 'failed', 'cancelled'].includes(currentStatus)) {
      void cache.invalidateQueries({ queryKey: [scopeUser, scopeGeneration, 'runs'] });
    }
  }, [currentStatus, cache, scopeUser, scopeGeneration]);
  if (run.isPending) return <Pending />;
  if (run.isError) return <Failure error={run.error} retry={() => void run.refetch()} />;
  const data = run.data;
  const hasGroq = data.version.definition.nodes.some((node) => node.type === 'groq');
  async function command(kind: 'retry' | 'cancel') {
    if (
      kind === 'cancel' &&
      !window.confirm('Cancel this execution? Completed node history will be retained.')
    )
      return;
    if (
      kind === 'retry' &&
      !window.confirm('Run the full workflow again using its original saved version and input?')
    )
      return;
    setCommandBusy(kind);
    setCommandError(null);
    try {
      if (kind === 'retry') {
        if (pendingRetry.current?.id !== executionId)
          pendingRetry.current = { id: executionId, key: crypto.randomUUID() };
        const result = await api.retryRun(executionId, pendingRetry.current.key);
        pendingRetry.current = null;
        navigate(`/executions/${result.id}`);
      } else {
        const result = await api.cancelRun(executionId);
        cache.setQueryData([...scope, 'run', executionId], result);
      }
      void cache.invalidateQueries({ queryKey: [...scope, 'runs'] });
    } catch (error) {
      setCommandError(error);
    } finally {
      setCommandBusy('');
    }
  }
  const statuses: Record<string, string> = {};
  const attempts: Record<string, number> = {};
  for (const row of data.node_runs)
    if ((attempts[row.node_id] || 0) < row.attempt_number) {
      statuses[row.node_id] = row.status;
      attempts[row.node_id] = row.attempt_number;
    }
  return (
    <div className="api-page">
      <PageHeader
        title="Execution details"
        description={data.id}
        actions={
          <>
            <Button asChild>
              <Link to={`/executions?workflow_id=${data.workflow_id}`}>Workflow history</Link>
            </Button>
            {['failed', 'cancelled'].includes(data.status) && !hasGroq && (
              <Button
                disabled={!!commandBusy}
                loading={commandBusy === 'retry'}
                onClick={() => void command('retry')}
              >
                Retry full workflow
              </Button>
            )}
            {['queued', 'running', 'waiting_approval'].includes(data.status) && (
              <Button
                variant="danger"
                disabled={!!commandBusy}
                loading={commandBusy === 'cancel'}
                onClick={() => void command('cancel')}
              >
                Cancel execution
              </Button>
            )}
            <Button disabled={!!commandBusy} onClick={() => void run.refetch()}>
              <RefreshCw size={16} />
              Refresh
            </Button>
          </>
        }
      />
      {commandError !== null && <Failure error={commandError} />}
      {['queued', 'running'].includes(data.status) && (
        <p className="api-notice" aria-live="polite">
          {data.next_retry_at
            ? `Waiting to retry ${data.retry_node_id} (attempt ${data.next_retry_attempt}) at ${date(data.next_retry_at)}.`
            : data.status === 'queued'
              ? 'Waiting for execution to start.'
              : 'Executing the saved workflow.'}{' '}
          This page updates automatically while the execution is active.
        </p>
      )}
      {hasGroq && ['failed', 'cancelled'].includes(data.status) && (
        <p className="api-notice">
          Full-workflow retry is unavailable for Groq runs. Start a new run explicitly if you want
          to send the prompt again.
        </p>
      )}
      <section className="card api-panel">
        <div className="api-section">
          <div className="api-actions">
            <Badge status={data.status} />
            <span>Version {data.version.version_number}</span>
            {data.execution_mode && (
              <span>
                {data.execution_mode === 'background'
                  ? 'Background execution'
                  : 'Synchronous execution'}
              </span>
            )}
            <span>Maximum attempts per node: {data.max_attempts}</span>
            {data.parent_run_id && (
              <Link to={`/executions/${data.parent_run_id}`}>Original execution</Link>
            )}
            <Link to={`/workflows/${data.workflow_id}/edit?version_id=${data.workflow_version_id}`}>
              View saved definition
            </Link>
          </div>
          <span className="muted">
            Elapsed {elapsed(data.started_at || data.created_at, data.completed_at)}
          </span>
        </div>
        {data.error_code && <p className="api-error">Failure: {data.error_code}</p>}
        <small className="muted">
          Created {date(data.created_at)} · Completed {date(data.completed_at)}
        </small>
      </section>
      <Canvas definition={data.version.definition} statuses={statuses} />
      <div className="api-two-columns">
        <section className="card api-panel">
          <h2>Run input</h2>
          <JsonViewer data={data.input} />
        </section>
        <section className="card api-panel">
          <h2>Run output</h2>
          {data.output === null ? (
            <p className="muted">No successful output stored.</p>
          ) : (
            <JsonViewer data={data.output} />
          )}
        </section>
      </div>
      <section className="card api-panel">
        <h2>Node attempts</h2>
        <p className="muted">
          Unvisited nodes after a failure have no attempt. Completed runs record the unchosen
          branches as skipped.
        </p>
        {data.node_runs.map((row) => (
          <details className="api-attempt" key={row.id}>
            <summary>
              <strong>{row.node_id}</strong>
              <Badge status={row.status} />
              <span>
                Attempt {row.attempt_number} ·{' '}
                {row.duration_ms === null ? 'No completed duration' : `${row.duration_ms} ms`}
              </span>
            </summary>
            <p>
              Started {date(row.started_at)} · Completed {date(row.completed_at)}
            </p>
            {row.error_code && <p className="api-error">{row.error_code}</p>}
            {row.retry && (
              <p>
                Retry scheduled for {date(row.retry.due_at)}
                {row.retry.resumed_at ? ` · Resumed ${date(row.retry.resumed_at)}` : ''}
                {row.retry.cancelled_at ? ` · Cancelled ${date(row.retry.cancelled_at)}` : ''}
              </p>
            )}
            <div className="api-two-columns">
              <div>
                <h3>Resolved input</h3>
                <JsonViewer data={row.input} />
              </div>
              <div>
                <h3>Output</h3>
                {row.output === null ? <p>No output stored.</p> : <JsonViewer data={row.output} />}
              </div>
            </div>
          </details>
        ))}
      </section>
      <p className="muted">
        Live events and traces are not available yet. Cancellation preserves completed history;
        retry starts the full original workflow for supported pure-node runs. No simulated telemetry
        is shown.
      </p>
    </div>
  );
}
export function Unavailable({ kind }: { kind: string }) {
  return (
    <div className="api-page">
      <PageHeader title={kind} />
      <EmptyState
        title={`${kind} are not available yet`}
        description="This feature’s backend module is still pending. Your workspace contains no simulated records or connections."
        action={
          <Button asChild>
            <Link to="/workflows">Open workflows</Link>
          </Button>
        }
      />
    </div>
  );
}
export function Integrations() {
  const [prompt, setPrompt] = useState(
    'Summarize the benefits of workflow automation in two sentences.',
  );
  const [result, setResult] = useState<{ model: string; content: string } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [pending, setPending] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.groqCompletion(prompt));
    } catch (err) {
      setError(err);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="api-page">
      <PageHeader title="Integrations" description="Test the backend connection to Groq." />
      <form className="card api-panel api-form" onSubmit={submit}>
        <h2>Groq</h2>
        <p>Your prompt is sent to Groq when you select Send. The API key stays on the server.</p>
        <label className="label" htmlFor="groq-prompt">
          Prompt
        </label>
        <textarea
          id="groq-prompt"
          className="input"
          rows={5}
          maxLength={4000}
          required
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
        <Button type="submit" variant="primary" disabled={pending || !prompt.trim()}>
          {pending ? 'Sending…' : 'Send to Groq'}
        </Button>
        {error ? <Failure error={error} /> : null}
        {result && (
          <section>
            <h3>Response from {result.model}</h3>
            <p style={{ whiteSpace: 'pre-wrap' }}>{result.content}</p>
          </section>
        )}
        <p className="muted">
          This test does not run a workflow. Add a Groq LLM node in the workflow editor to use Groq
          during a run.
        </p>
      </form>
    </div>
  );
}
export function Account() {
  const session = useSession();
  const scope = useScope();
  const profile = useQuery({ queryKey: [...scope, 'profile'], queryFn: api.me });
  const user = profile.data || session.user;
  const [theme, setTheme] = useState(() => {
    try {
      return localStorage.getItem('agentflow-ui-theme') || 'system';
    } catch {
      return 'system';
    }
  });
  function update(value: string) {
    setTheme(value);
    try {
      localStorage.setItem('agentflow-ui-theme', value);
    } catch {
      /* Appearance is optional local state. */
    }
    document.documentElement.dataset.theme =
      value === 'system'
        ? window.matchMedia('(prefers-color-scheme: dark)').matches
          ? 'dark'
          : 'light'
        : value;
  }
  return (
    <div className="api-page">
      <PageHeader title="Account" description="Your authenticated server profile." />
      <section className="card api-panel api-form">
        <h2>{user?.display_name}</h2>
        <p>{user?.email}</p>
        <small className="muted">Profile editing and password reset are not available yet.</small>
        <label className="label" htmlFor="theme">
          Appearance
        </label>
        <select id="theme" className="input" value={theme} onChange={(e) => update(e.target.value)}>
          <option value="system">System</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
        <small className="muted">Appearance is saved only on this browser.</small>
      </section>
    </div>
  );
}
