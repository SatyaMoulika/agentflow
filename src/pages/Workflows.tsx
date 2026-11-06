import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import {
  ArrowUpRight,
  Archive,
  Copy,
  FileText,
  GitBranch,
  LayoutGrid,
  List,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Search,
  Sparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react';
import { useAppStore } from '../stores/useAppStore';
import { Badge, Button, EmptyState, PageHeader, SearchInput } from '../components/ui';
import type { Workflow } from '../types';
import './management.css';

function relativeTime(date?: string) {
  return date ? formatDistanceToNow(new Date(date), { addSuffix: true }) : 'Never run';
}

export default function Workflows() {
  const navigate = useNavigate();
  const { workflows, duplicateWorkflow, updateWorkflow, runWorkflow, notify } = useAppStore();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [sort, setSort] = useState('updated');
  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [menu, setMenu] = useState<string | null>(null);
  const filtered = useMemo(
    () =>
      workflows
        .filter(
          (w) =>
            (status === 'all' || w.status === status) &&
            `${w.name} ${w.description}`.toLowerCase().includes(search.toLowerCase()),
        )
        .sort((a, b) =>
          sort === 'name'
            ? a.name.localeCompare(b.name)
            : sort === 'runs'
              ? b.totalRuns - a.totalRuns
              : new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
        ),
    [workflows, status, search, sort],
  );
  const run = (workflow: Workflow) => {
    setMenu(null);
    const executionId = runWorkflow(workflow.id);
    if (executionId) navigate(`/executions/${executionId}`);
  };
  const duplicate = (workflow: Workflow) => {
    duplicateWorkflow(workflow.id);
    setMenu(null);
    notify('Workflow duplicated. Your copy is ready to edit.');
  };
  function actions(workflow: Workflow) {
    return (
      <div className="workflow-actions">
        <button
          className="icon-button"
          aria-label={`Actions for ${workflow.name}`}
          aria-expanded={menu === workflow.id}
          onClick={() => setMenu(menu === workflow.id ? null : workflow.id)}
        >
          <MoreHorizontal size={18} />
        </button>
        {menu === workflow.id && (
          <>
            <button
              aria-label="Close actions"
              className="menu-dismiss"
              onClick={() => setMenu(null)}
            />
            <div className="workflow-menu">
              <button onClick={() => navigate(`/workflows/${workflow.id}/edit`)}>
                <ArrowUpRight size={15} /> Open editor
              </button>
              <button onClick={() => run(workflow)}>
                <Play size={15} /> Run workflow
              </button>
              <button onClick={() => duplicate(workflow)}>
                <Copy size={15} /> Duplicate
              </button>
              <button
                onClick={() => {
                  updateWorkflow(workflow.id, {
                    status: workflow.status === 'active' ? 'paused' : 'active',
                  });
                  setMenu(null);
                }}
              >
                <Pause size={15} />{' '}
                {workflow.status === 'active' ? 'Pause workflow' : 'Activate workflow'}
              </button>
              <button
                className="danger-text"
                onClick={() => {
                  updateWorkflow(workflow.id, { status: 'archived' });
                  setMenu(null);
                  notify('Workflow archived. Find it in the Archived filter.');
                }}
              >
                <Archive size={15} /> Archive
              </button>
            </div>
          </>
        )}
      </div>
    );
  }
  return (
    <div className="management-page">
      <PageHeader
        title="Workflows"
        description="Your ideas, set in motion. Build and manage your automations."
        actions={
          <>
            <Button variant="secondary" onClick={() => navigate('/workflows/new')}>
              <Sparkles size={16} /> Generate with AI
            </Button>
            <Button variant="primary" onClick={() => navigate('/workflows/new')}>
              <Plus size={17} /> Create workflow
            </Button>
          </>
        }
      />
      <div className="workflow-summary">
        <span>
          <span className="summary-dot" /> {workflows.filter((w) => w.status === 'active').length}{' '}
          active workflows
        </span>
        <span>{workflows.length} workflows in your workspace</span>
      </div>
      <div className="management-toolbar">
        <SearchInput value={search} onChange={setSearch} placeholder="Search workflows..." />
        <div className="toolbar-controls">
          <select
            aria-label="Filter by status"
            className="input compact-select"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {['all', 'active', 'draft', 'paused', 'archived'].map((s) => (
              <option key={s} value={s}>
                {s === 'all' ? 'All statuses' : s.charAt(0).toUpperCase() + s.slice(1)}
              </option>
            ))}
          </select>
          <select
            aria-label="Sort workflows"
            className="input compact-select"
            value={sort}
            onChange={(e) => setSort(e.target.value)}
          >
            <option value="updated">Last updated</option>
            <option value="name">Name A–Z</option>
            <option value="runs">Most executions</option>
          </select>
          <div className="view-toggle">
            <button
              className={view === 'grid' ? 'selected' : ''}
              aria-label="Grid view"
              aria-pressed={view === 'grid'}
              onClick={() => setView('grid')}
            >
              <LayoutGrid size={17} />
            </button>
            <button
              className={view === 'list' ? 'selected' : ''}
              aria-label="List view"
              aria-pressed={view === 'list'}
              onClick={() => setView('list')}
            >
              <List size={17} />
            </button>
          </div>
        </div>
      </div>
      {filtered.length === 0 ? (
        <EmptyState
          icon={<Search size={26} />}
          title={workflows.length ? 'No workflows found' : 'Your automation journey starts here'}
          description={
            workflows.length
              ? 'Try another search or change the status filter.'
              : 'Turn your first idea into an intelligent workflow.'
          }
          action={
            <Button
              variant="primary"
              onClick={() =>
                workflows.length ? (setSearch(''), setStatus('all')) : navigate('/workflows/new')
              }
            >
              {workflows.length ? 'Clear filters' : 'Create your first workflow'}
            </Button>
          }
        />
      ) : view === 'grid' ? (
        <div className="workflow-grid">
          {filtered.map((workflow, index) => (
            <article className="workflow-card card" key={workflow.id}>
              <div className="workflow-card-top">
                <span className={`workflow-symbol symbol-${index % 4}`}>
                  {/invoice|document/i.test(workflow.name) ? (
                    <FileText size={21} />
                  ) : (
                    <WorkflowIcon size={21} />
                  )}
                </span>
                <div className="workflow-card-status">
                  <Badge status={workflow.status} />
                  {actions(workflow)}
                </div>
              </div>
              <Link className="workflow-card-title" to={`/workflows/${workflow.id}/edit`}>
                {workflow.name}
              </Link>
              <p className="workflow-description">{workflow.description}</p>
              <div className="workflow-stat-row">
                <span>
                  <GitBranch size={14} /> {workflow.nodes.length} nodes
                </span>
                <span>{workflow.totalRuns.toLocaleString()} executions</span>
              </div>
              <div className="workflow-last-run">Last run {relativeTime(workflow.lastRun)}</div>
              <div className="workflow-card-footer">
                <span className="workflow-success">
                  {workflow.totalRuns ? (
                    <>
                      <span className="summary-dot" /> {workflow.successRate}% success
                    </>
                  ) : (
                    'No executions yet'
                  )}
                </span>
                <span>Updated {relativeTime(workflow.updatedAt)}</span>
              </div>
              <div className="workflow-card-hover">
                <button onClick={() => navigate(`/workflows/${workflow.id}/edit`)}>
                  Open workflow <ArrowUpRight size={14} />
                </button>
                <button aria-label={`Run ${workflow.name}`} onClick={() => run(workflow)}>
                  <Play size={14} />
                </button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="card management-table-wrap">
          <table className="management-table">
            <thead>
              <tr>
                <th>Workflow</th>
                <th>Status</th>
                <th>Nodes</th>
                <th>Executions</th>
                <th>Last run</th>
                <th>Updated</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((workflow) => (
                <tr key={workflow.id}>
                  <td>
                    <Link className="table-workflow-name" to={`/workflows/${workflow.id}/edit`}>
                      <span className="workflow-symbol">
                        <WorkflowIcon size={17} />
                      </span>
                      {workflow.name}
                    </Link>
                  </td>
                  <td>
                    <Badge status={workflow.status} />
                  </td>
                  <td>{workflow.nodes.length}</td>
                  <td>{workflow.totalRuns.toLocaleString()}</td>
                  <td>{relativeTime(workflow.lastRun)}</td>
                  <td>{relativeTime(workflow.updatedAt)}</td>
                  <td>{actions(workflow)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {filtered.length > 0 && (
        <div className="results-count">
          Showing {filtered.length} of {workflows.length} workflows
        </div>
      )}
    </div>
  );
}
