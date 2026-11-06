import { memo, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Bot,
  Braces,
  CheckCircle2,
  ChevronRight,
  Circle,
  Copy,
  Hash,
  Layers3,
  LoaderCircle,
  PauseCircle,
  RotateCcw,
  ShieldCheck,
  Square,
  Terminal,
  Timer,
  TriangleAlert,
} from 'lucide-react';
import { Badge, Button, ConfirmDialog, EmptyState, JsonViewer } from '../components/ui';
import { useAppStore } from '../stores/useAppStore';
import { formatDuration, relativeTime } from '../lib/utils';
import { nodeRegistry } from '../lib/node-registry';
import type { Execution, ExecutionEvent, NodeRunStatus, NodeType } from '../types';
import '@xyflow/react/dist/style.css';
import './observability.css';

type RunCanvasNode = Node<
  { label: string; kind: NodeType; status: NodeRunStatus; duration: number },
  'execution'
>;
const RunNode = memo(function RunNode({ data, selected }: NodeProps<RunCanvasNode>) {
  const definition = nodeRegistry[data.kind];
  const Icon = definition.icon;
  const branches = definition.outputs.length > 1;
  const StateIcon =
    data.status === 'succeeded'
      ? CheckCircle2
      : data.status === 'failed'
        ? TriangleAlert
        : data.status === 'running'
          ? LoaderCircle
          : data.status === 'waiting_approval'
            ? PauseCircle
            : Circle;
  return (
    <div
      className={`obs-canvas-node ${selected ? 'selected' : ''} ${branches ? 'has-branches' : ''} status-${data.status}`}
    >
      {definition.category !== 'Trigger' && (
        <Handle type="target" position={Position.Left} isConnectable={false} />
      )}
      <span className={`obs-node-icon kind-${data.kind}`}>
        <Icon size={19} />
      </span>
      <div className="obs-node-body">
        <small>{data.kind === 'llm' ? 'AI MODEL' : data.kind.toUpperCase()}</small>
        <strong>{data.label}</strong>
        <span className="obs-node-duration">
          {data.duration > 0
            ? formatDuration(data.duration)
            : data.status === 'running'
              ? 'In progress'
              : data.status === 'waiting_approval'
                ? 'Awaiting review'
                : data.status === 'skipped'
                  ? 'Skipped'
                  : 'Not started'}
        </span>
      </div>
      <StateIcon
        size={15}
        className={`obs-node-state ${data.status === 'running' ? 'spin' : ''}`}
      />
      {definition.outputs.map((output, index) => (
        <Handle
          key={output}
          type="source"
          id={output}
          position={Position.Right}
          style={{ top: branches ? `${35 + index * 38}%` : '50%' }}
          isConnectable={false}
        />
      ))}
      {branches &&
        definition.outputs.map((output, index) => (
          <span
            key={output}
            className="obs-node-branch-label"
            style={{ top: `${35 + index * 38}%` }}
          >
            {output}
          </span>
        ))}
    </div>
  );
});
const nodeTypes = { execution: RunNode };
const inspectorTabs = ['Overview', 'Input', 'Output', 'LLM', 'Trace', 'Logs'] as const;

function Logs({ execution, nodeId }: { execution: Execution; nodeId?: string }) {
  const notify = useAppStore((s) => s.notify);
  const [query, setQuery] = useState('');
  const [level, setLevel] = useState('all');
  const logs = execution.events.filter(
    (log) =>
      (!nodeId || log.nodeId === nodeId) &&
      (level === 'all' || level === log.level) &&
      log.message.toLowerCase().includes(query.toLowerCase()),
  );
  async function copyLogs() {
    try {
      await navigator.clipboard.writeText(
        logs
          .map((log) => `[${log.timestamp}] ${log.level.toUpperCase()} ${log.message}`)
          .join('\n'),
      );
      notify('Logs copied to clipboard.', 'success');
    } catch {
      notify('Clipboard access is unavailable in this browser.', 'error');
    }
  }
  return (
    <div className="obs-logs">
      <div className="obs-log-toolbar">
        <input
          className="input"
          aria-label="Search logs"
          placeholder="Search logs..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="input"
          value={level}
          aria-label="Log severity"
          onChange={(e) => setLevel(e.target.value)}
        >
          <option value="all">All levels</option>
          <option value="info">Info</option>
          <option value="warn">Warning</option>
          <option value="error">Error</option>
        </select>
        <Button size="sm" variant="ghost" onClick={copyLogs} title="Copy filtered logs">
          <Copy size={14} />
        </Button>
      </div>
      <div className="obs-log-entries">
        {logs.length ? (
          logs.map((log) => (
            <div key={log.id} className={`obs-log-entry ${log.level}`}>
              <time>{new Date(log.timestamp).toLocaleTimeString('en-GB')}</time>
              <span>{log.level.toUpperCase()}</span>
              <p>{log.message}</p>
            </div>
          ))
        ) : (
          <div className="obs-small-empty">
            <Terminal size={22} />
            <p>No logs match this view.</p>
          </div>
        )}
      </div>
    </div>
  );
}

function Timeline({ execution }: { execution: Execution }) {
  const [filter, setFilter] = useState('all');
  const events = execution.events.filter((e) => filter === 'all' || e.level === filter);
  const icons = { info: CheckCircle2, warn: PauseCircle, error: TriangleAlert };
  return (
    <div className="obs-timeline">
      <div className="obs-section-heading">
        <div>
          <h3>Execution timeline</h3>
          <p>A chronological record of this run.</p>
        </div>
        <select
          className="input"
          aria-label="Filter timeline"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All events</option>
          <option value="info">Info</option>
          <option value="warn">Warnings</option>
          <option value="error">Errors</option>
        </select>
      </div>
      <div className="obs-timeline-events">
        {events.map((event: ExecutionEvent) => {
          const Icon = icons[event.level];
          return (
            <div className={`obs-timeline-event ${event.level}`} key={event.id}>
              <span className="obs-timeline-icon">
                <Icon size={15} />
              </span>
              <div>
                <strong>{event.message}</strong>
                {event.nodeId && (
                  <small>
                    {execution.graph.nodes.find((n) => n.id === event.nodeId)?.label ||
                      event.nodeId}
                  </small>
                )}
              </div>
              <time>{new Date(event.timestamp).toLocaleTimeString('en-GB')}</time>
            </div>
          );
        })}
        {!events.length && <p className="muted">No events match this filter.</p>}
      </div>
    </div>
  );
}

export default function ExecutionDetail() {
  const params = useParams();
  const id = params.executionId || params.id;
  const navigate = useNavigate();
  const execution = useAppStore((s) => s.executions.find((e) => e.id === id));
  const approval = useAppStore((s) =>
    s.approvals.find((a) => a.executionId === id && a.status === 'pending'),
  );
  const cancelExecution = useAppStore((s) => s.cancelExecution);
  const runWorkflow = useAppStore((s) => s.runWorkflow);
  const workflows = useAppStore((s) => s.workflows);
  const notify = useAppStore((s) => s.notify);
  const [selectedId, setSelectedId] = useState<string>();
  const [tab, setTab] = useState<(typeof inspectorTabs)[number]>('Overview');
  const [view, setView] = useState('canvas');
  const [confirmCancel, setConfirmCancel] = useState(false);
  const selectedNode =
    execution?.graph.nodes.find((n) => n.id === selectedId) ||
    execution?.graph.nodes.find((n) => ['llm', 'extract', 'agent'].includes(n.type)) ||
    execution?.graph.nodes[0];
  const graphNodes = useMemo<RunCanvasNode[]>(
    () =>
      execution?.graph.nodes.map((n) => {
        const run = execution.nodeRuns.find((r) => r.nodeId === n.id);
        return {
          id: n.id,
          position: n.position,
          type: 'execution',
          selected: n.id === selectedNode?.id,
          data: {
            label: n.label,
            kind: n.type,
            status: run?.status || 'pending',
            duration: run?.duration || 0,
          },
        };
      }) || [],
    [execution, selectedNode?.id],
  );
  const graphEdges = useMemo(
    () =>
      execution?.graph.edges.map((edge) => {
        const source = execution.graph.nodes.find((node) => node.id === edge.source);
        const sourceRun = execution.nodeRuns.find((run) => run.nodeId === edge.source);
        const targetRun = execution.nodeRuns.find((run) => run.nodeId === edge.target);
        const branch =
          source?.type === 'condition'
            ? sourceRun?.output?.matched
              ? 'true'
              : 'false'
            : source?.type === 'approval'
              ? sourceRun?.output?.decision
              : undefined;
        const taken =
          sourceRun?.status === 'succeeded' &&
          (!branch || edge.sourceHandle === branch) &&
          !!targetRun &&
          targetRun.status !== 'skipped' &&
          targetRun.status !== 'pending';
        return {
          ...edge,
          sourceHandle:
            edge.sourceHandle || (source ? nodeRegistry[source.type].outputs[0] : undefined),
          type: 'smoothstep',
          animated: sourceRun?.status === 'running',
          style: { stroke: taken ? 'var(--success)' : 'var(--border)', strokeWidth: 2 },
        };
      }) || [],
    [execution],
  );
  if (!execution)
    return (
      <EmptyState
        title="Execution not found"
        description="This execution may have been removed, or the link is no longer valid."
        action={<Button onClick={() => navigate('/executions')}>Back to executions</Button>}
      />
    );
  const selectedRun = execution.nodeRuns.find((n) => n.nodeId === selectedNode?.id);
  const isAI = selectedNode && ['llm', 'classify', 'extract', 'agent'].includes(selectedNode.type);
  const totalTokens = execution.nodeRuns.reduce(
    (sum, run) => sum + (run.tokens?.input || 0) + (run.tokens?.output || 0),
    0,
  );
  const completed = execution.nodeRuns.filter((r) => r.status === 'succeeded').length;
  const active = ['queued', 'running', 'waiting_approval'].includes(execution.status);
  const failedRun = execution.nodeRuns.find((r) => r.status === 'failed');
  const allLogs = view === 'logs';

  function retry() {
    if (!execution) return;
    if (!workflows.some((w) => w.id === execution.workflowId)) {
      notify('The original workflow is no longer available.', 'error');
      return;
    }
    const runId = runWorkflow(execution.workflowId);
    if (runId) navigate(`/executions/${runId}`);
  }

  return (
    <div className="obs-page obs-detail">
      <div className="obs-detail-breadcrumb">
        <Link to="/executions">
          <ArrowLeft size={15} /> Executions
        </Link>
        <ChevronRight size={13} />
        <span>{execution.workflowName}</span>
      </div>
      <div className="obs-detail-header">
        <div>
          <div className="obs-title-line">
            <h1>{execution.workflowName}</h1>
            <Badge status={execution.status} />
          </div>
          <div className="obs-run-meta">
            <code>{execution.id}</code>
            <span>·</span>
            <span>Version {execution.version}</span>
            <span>·</span>
            <span>{relativeTime(execution.startedAt)}</span>
            <span className="obs-demo">
              <span /> Simulated run
            </span>
          </div>
        </div>
        <div className="obs-row-actions">
          <Button
            variant="secondary"
            onClick={() => navigate(`/workflows/${execution.workflowId}/edit`)}
          >
            <Layers3 size={15} /> Open workflow
          </Button>
          {active ? (
            <Button variant="danger" onClick={() => setConfirmCancel(true)}>
              <Square size={13} /> Cancel run
            </Button>
          ) : (
            <Button variant="primary" onClick={retry}>
              <RotateCcw size={15} /> Run again
            </Button>
          )}
        </div>
      </div>
      {execution.status === 'waiting_approval' && (
        <div className="obs-alert warning">
          <ShieldCheck size={20} />
          <div>
            <strong>A decision is needed to continue</strong>
            <p>This simulated execution is paused at a human approval step.</p>
          </div>
          {approval && (
            <Button variant="primary" onClick={() => navigate(`/approvals/${approval.id}`)}>
              Review request <ArrowRight size={15} />
            </Button>
          )}
        </div>
      )}
      {execution.status === 'failed' && (
        <div className="obs-alert error">
          <TriangleAlert size={20} />
          <div>
            <strong>This execution stopped with an error</strong>
            <p>{failedRun?.error || 'Inspect the failed node and execution logs for details.'}</p>
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              setSelectedId(failedRun?.nodeId);
              setTab('Logs');
            }}
          >
            Inspect error
          </Button>
        </div>
      )}
      <div className="obs-run-stats">
        <div>
          <span>
            <Timer size={14} /> Total duration
          </span>
          <strong>{formatDuration(execution.duration)}</strong>
        </div>
        <div>
          <span>
            <CheckCircle2 size={14} /> Completed steps
          </span>
          <strong>
            {completed}
            <small> / {execution.graph.nodes.length}</small>
          </strong>
        </div>
        <div>
          <span>
            <Bot size={14} /> Total tokens
          </span>
          <strong>{totalTokens.toLocaleString()}</strong>
        </div>
        <div>
          <span>
            <Activity size={14} /> Trigger
          </span>
          <strong className="obs-capitalize">{execution.trigger}</strong>
        </div>
        <div>
          <span>
            <Hash size={14} /> Trace ID
          </span>
          <strong className="obs-mono obs-trace-id" title={execution.traceId}>
            {execution.traceId}
          </strong>
        </div>
      </div>
      <div className="obs-monitor card">
        <div className="obs-monitor-main">
          <div className="obs-canvas-toolbar">
            <div className="obs-segmented" aria-label="Execution view">
              {[
                ['canvas', 'Workflow'],
                ['timeline', 'Timeline'],
                ['logs', 'Logs'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setView(value)}
                  className={view === value ? 'active' : ''}
                >
                  {label}
                </button>
              ))}
            </div>
            <span className="obs-canvas-hint">
              {execution.status === 'running' ? (
                <>
                  <span className="obs-status-dot running" /> Live simulation
                </>
              ) : (
                <>
                  <span className="obs-status-dot success" /> Execution snapshot
                </>
              )}
            </span>
          </div>
          {view === 'canvas' ? (
            <>
              <div className="obs-execution-canvas">
                <ReactFlow
                  nodes={graphNodes}
                  edges={graphEdges}
                  nodeTypes={nodeTypes}
                  onNodeClick={(_, node) => {
                    setSelectedId(node.id);
                    setTab('Overview');
                  }}
                  fitView
                  fitViewOptions={{ padding: 0.3 }}
                  minZoom={0.25}
                  maxZoom={1.5}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable
                  proOptions={{ hideAttribution: true }}
                >
                  <Background
                    variant={BackgroundVariant.Dots}
                    gap={20}
                    size={1}
                    color="var(--border)"
                  />
                  <Controls showInteractive={false} />
                </ReactFlow>
              </div>
              <div className="obs-canvas-legend">
                <span>
                  <i className="success" /> Succeeded
                </span>
                <span>
                  <i className="running" /> Running
                </span>
                <span>
                  <i className="waiting" /> Waiting
                </span>
                <span>
                  <i className="failed" /> Failed
                </span>
                <span>
                  <i className="pending" /> Pending
                </span>
              </div>
            </>
          ) : allLogs ? (
            <div className="obs-main-log">
              <Logs execution={execution} />
            </div>
          ) : (
            <Timeline execution={execution} />
          )}
        </div>
        <aside className="obs-inspector">
          <div className="obs-inspector-heading">
            <span className="obs-workflow-icon">
              {selectedNode &&
                (() => {
                  const Icon = nodeRegistry[selectedNode.type].icon;
                  return <Icon size={18} />;
                })()}
            </span>
            <div>
              <h3>{selectedNode?.label || 'No node selected'}</h3>
              <p>
                {selectedNode?.type} · {selectedNode?.id}
              </p>
            </div>
            {selectedRun && <Badge status={selectedRun.status} />}
          </div>
          <div className="obs-inspector-tabs" role="tablist" aria-label="Node inspector">
            {inspectorTabs.map((t) => (
              <button
                role="tab"
                aria-selected={tab === t}
                key={t}
                onClick={() => setTab(t)}
                className={tab === t ? 'active' : ''}
              >
                {t}
              </button>
            ))}
          </div>
          <div className="obs-inspector-body" role="tabpanel" aria-label={`${tab} inspector`}>
            {tab === 'Overview' && (
              <>
                <div className="obs-inspector-section">
                  <h4>Step details</h4>
                  <p className="muted">
                    {selectedNode?.config.description ||
                      'Inspect this step’s inputs, outputs, and trace to understand how the workflow reached its result.'}
                  </p>
                  <dl className="obs-definition">
                    <div>
                      <dt>Status</dt>
                      <dd>{selectedRun ? <Badge status={selectedRun.status} /> : 'Pending'}</dd>
                    </div>
                    <div>
                      <dt>Duration</dt>
                      <dd>{selectedRun ? formatDuration(selectedRun.duration) : '—'}</dd>
                    </div>
                    <div>
                      <dt>Started</dt>
                      <dd>
                        {selectedRun?.startedAt
                          ? new Date(selectedRun.startedAt).toLocaleTimeString()
                          : 'Not started'}
                      </dd>
                    </div>
                    <div>
                      <dt>Finished</dt>
                      <dd>
                        {selectedRun?.endedAt
                          ? new Date(selectedRun.endedAt).toLocaleTimeString()
                          : 'Not finished'}
                      </dd>
                    </div>
                    <div>
                      <dt>Attempt / retries</dt>
                      <dd>
                        {selectedRun?.attempt ?? '—'} / {selectedRun?.retryCount ?? '—'}
                      </dd>
                    </div>
                    <div>
                      <dt>Node type</dt>
                      <dd className="obs-capitalize">{selectedNode?.type}</dd>
                    </div>
                  </dl>
                </div>
                {selectedRun?.error && (
                  <div className="obs-inline-error">
                    <TriangleAlert size={16} />
                    <p>{selectedRun.error}</p>
                  </div>
                )}
                <div className="obs-inspector-section">
                  <h4>Output preview</h4>
                  {selectedRun?.output ? (
                    <JsonViewer data={selectedRun.output} />
                  ) : (
                    <p className="muted">Output will appear when this step completes.</p>
                  )}
                </div>
                <div className="obs-simulation-note">
                  <Bot size={16} />
                  <span>Demo execution data. Inputs and outputs are simulated locally.</span>
                </div>
              </>
            )}
            {tab === 'Input' && (
              <>
                <div className="obs-inspector-section">
                  <h4>Step input</h4>
                  <p className="muted">Data passed into this node.</p>
                </div>
                <JsonViewer data={selectedRun?.input || {}} />
              </>
            )}
            {tab === 'Output' && (
              <>
                <div className="obs-inspector-section">
                  <h4>Step output</h4>
                  <p className="muted">Structured result returned by this step.</p>
                </div>
                {selectedRun?.output ? (
                  <JsonViewer data={selectedRun.output} />
                ) : (
                  <div className="obs-small-empty">
                    <Braces size={26} />
                    <p>This step has no output yet.</p>
                  </div>
                )}
              </>
            )}
            {tab === 'LLM' &&
              (isAI ? (
                <>
                  <div className="obs-inspector-section">
                    <h4>Model metadata</h4>
                    <dl className="obs-definition">
                      <div>
                        <dt>Model</dt>
                        <dd>{selectedNode.config.model || 'Default demo model'}</dd>
                      </div>
                      <div>
                        <dt>Temperature</dt>
                        <dd>{selectedNode.config.temperature ?? 0.2}</dd>
                      </div>
                      <div>
                        <dt>Input tokens</dt>
                        <dd>{selectedRun?.tokens?.input.toLocaleString() ?? '—'}</dd>
                      </div>
                      <div>
                        <dt>Output tokens</dt>
                        <dd>{selectedRun?.tokens?.output.toLocaleString() ?? '—'}</dd>
                      </div>
                      <div>
                        <dt>Total tokens</dt>
                        <dd>
                          {selectedRun?.tokens
                            ? (
                                selectedRun.tokens.input + selectedRun.tokens.output
                              ).toLocaleString()
                            : '—'}
                        </dd>
                      </div>
                      <div>
                        <dt>Prompt snapshot</dt>
                        <dd>Workflow v{execution.version}</dd>
                      </div>
                      <div>
                        <dt>Estimated cost</dt>
                        <dd>Unavailable in demo</dd>
                      </div>
                      <div>
                        <dt>Tool calls</dt>
                        <dd>None recorded</dd>
                      </div>
                      <div>
                        <dt>Latency</dt>
                        <dd>{formatDuration(selectedRun?.duration || 0)}</dd>
                      </div>
                    </dl>
                  </div>
                  <div className="obs-inspector-section">
                    <h4>System prompt</h4>
                    <pre className="obs-prompt">
                      {selectedNode.config.systemPrompt ||
                        'Use the configured task instructions and return structured, validated output.'}
                    </pre>
                    <h4>User prompt</h4>
                    <pre className="obs-prompt">
                      {selectedNode.config.prompt ||
                        'Process the incoming workflow data according to this node’s configuration.'}
                    </pre>
                  </div>
                  <p className="obs-simulation-note">
                    Token counts and model responses are simulated. No LLM API was called.
                  </p>
                </>
              ) : (
                <div className="obs-small-empty">
                  <Bot size={28} />
                  <h4>No model call in this step</h4>
                  <p>Select an AI node to inspect model metadata and prompts.</p>
                </div>
              ))}
            {tab === 'Trace' && (
              <div className="obs-inspector-section">
                <h4>Trace context</h4>
                <dl className="obs-definition vertical">
                  <div>
                    <dt>Trace ID</dt>
                    <dd>
                      <code>{execution.traceId}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Span ID</dt>
                    <dd>
                      <code>
                        {selectedNode?.id}-{execution.id.slice(-6)}
                      </code>
                    </dd>
                  </div>
                  <div>
                    <dt>Parent span ID</dt>
                    <dd>
                      <code>
                        {(() => {
                          const predecessor = execution.graph.edges.find(
                            (edge) =>
                              edge.target === selectedNode?.id &&
                              execution.nodeRuns.find((run) => run.nodeId === edge.source)
                                ?.status === 'succeeded',
                          );
                          return predecessor
                            ? `${predecessor.source}-${execution.id.slice(-6)}`
                            : 'Root span';
                        })()}
                      </code>
                    </dd>
                  </div>
                  <div>
                    <dt>Span duration</dt>
                    <dd>{formatDuration(selectedRun?.duration || 0)}</dd>
                  </div>
                  <div>
                    <dt>Execution ID</dt>
                    <dd>
                      <code>{execution.id}</code>
                    </dd>
                  </div>
                  <div>
                    <dt>Workflow version</dt>
                    <dd>v{execution.version}</dd>
                  </div>
                  <div>
                    <dt>Started at</dt>
                    <dd>
                      {selectedRun?.startedAt
                        ? new Date(selectedRun.startedAt).toLocaleString()
                        : 'Not started'}
                    </dd>
                  </div>
                  <div>
                    <dt>Finished at</dt>
                    <dd>
                      {selectedRun?.endedAt
                        ? new Date(selectedRun.endedAt).toLocaleString()
                        : 'Not finished'}
                    </dd>
                  </div>
                </dl>
                <p className="obs-simulation-note">
                  Local demo trace identifiers for this execution snapshot.
                </p>
              </div>
            )}
            {tab === 'Logs' && <Logs execution={execution} nodeId={selectedNode?.id} />}
          </div>
        </aside>
      </div>
      <div className="obs-bottom-note">
        <span>
          <Circle size={10} /> Select a node to inspect its input, output, and trace.
        </span>
        <span>Read-only execution snapshot</span>
      </div>
      <ConfirmDialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        onConfirm={() => {
          cancelExecution(execution.id);
          setConfirmCancel(false);
        }}
        title="Cancel this execution?"
        description="The simulated run will stop immediately. Completed steps and logs will remain available for inspection."
        confirmLabel="Cancel execution"
        danger
      />
    </div>
  );
}
