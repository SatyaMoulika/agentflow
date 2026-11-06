import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileCheck2,
  MessageSquare,
  ShieldCheck,
  ShieldQuestion,
  X,
} from 'lucide-react';
import {
  Badge,
  Button,
  EmptyState,
  JsonViewer,
  Modal,
  PageHeader,
  SearchInput,
} from '../components/ui';
import { useAppStore } from '../stores/useAppStore';
import { relativeTime } from '../lib/utils';
import type { Approval } from '../types';
import './observability.css';

type Decision = 'approved' | 'rejected';
function Risk({ risk }: { risk: Approval['risk'] }) {
  return (
    <span className={`obs-risk ${risk}`}>
      <ShieldCheck size={12} /> {risk.charAt(0).toUpperCase() + risk.slice(1)} risk
    </span>
  );
}
function dataValue(value: unknown) {
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

export default function Approvals() {
  const params = useParams();
  const approvalId = params.approvalId || params.id;
  const navigate = useNavigate();
  const approvals = useAppStore((s) => s.approvals);
  const executions = useAppStore((s) => s.executions);
  const decideApproval = useAppStore((s) => s.decideApproval);
  const [tab, setTab] = useState('pending');
  const [search, setSearch] = useState('');
  const [decision, setDecision] = useState<{ approval: Approval; decision: Decision } | null>(null);
  const [comment, setComment] = useState('');
  const selected = approvals.find((a) => a.id === approvalId);
  const execution = executions.find((e) => e.id === selected?.executionId);
  const tabs = ['pending', 'approved', 'rejected', 'expired', 'all'];
  const filtered = useMemo(
    () =>
      approvals
        .filter(
          (a) =>
            (tab === 'all' || a.status === tab) &&
            `${a.title} ${a.workflowName} ${a.description}`
              .toLowerCase()
              .includes(search.toLowerCase()),
        )
        .sort((a, b) => +new Date(b.requestedAt) - +new Date(a.requestedAt)),
    [approvals, search, tab],
  );
  const pendingCount = approvals.filter((a) => a.status === 'pending').length;

  function openDecision(approval: Approval, nextDecision: Decision) {
    setComment('');
    setDecision({ approval, decision: nextDecision });
  }
  function confirmDecision() {
    if (!decision) return;
    decideApproval(decision.approval.id, decision.decision, comment.trim() || undefined);
    setDecision(null);
    setComment('');
  }

  const confirmation = (
    <Modal
      open={!!decision}
      onClose={() => setDecision(null)}
      title={decision?.decision === 'approved' ? 'Approve this request?' : 'Reject this request?'}
      footer={
        <>
          <Button variant="secondary" onClick={() => setDecision(null)}>
            Keep reviewing
          </Button>
          <Button
            variant={decision?.decision === 'rejected' ? 'danger' : 'primary'}
            onClick={confirmDecision}
          >
            {decision?.decision === 'approved' ? (
              <>
                <Check size={15} /> Confirm approval
              </>
            ) : (
              <>
                <X size={15} /> Confirm rejection
              </>
            )}
          </Button>
        </>
      }
    >
      <div
        className={`obs-decision-explainer ${decision?.decision === 'rejected' ? 'reject' : ''}`}
      >
        <ShieldQuestion size={24} />
        <div>
          <strong>{decision?.approval.title}</strong>
          <p>
            {decision?.decision === 'approved'
              ? 'The simulated execution will resume along its connected approval branch.'
              : 'The simulated execution will follow its connected rejection branch. The approved action will be skipped.'}
          </p>
        </div>
      </div>
      <label className="field">
        <span className="label">
          Decision note <span className="muted">(optional)</span>
        </span>
        <textarea
          className="input"
          rows={3}
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Add context for your decision..."
          maxLength={1000}
        />
      </label>
      <p className="obs-footnote">
        Your decision and note will be recorded in this local demo workspace.
      </p>
    </Modal>
  );

  if (approvalId && !selected)
    return (
      <EmptyState
        title="Approval request not found"
        description="The request may have been removed, or the link is no longer valid."
        action={<Button onClick={() => navigate('/approvals')}>Back to approvals</Button>}
      />
    );

  if (selected)
    return (
      <div className="obs-page obs-approval-detail">
        <div className="obs-detail-breadcrumb">
          <Link to="/approvals">
            <ArrowLeft size={15} /> Approvals
          </Link>
          <ChevronRight size={13} />
          <span>Request details</span>
        </div>
        <div className="obs-detail-header">
          <div>
            <div className="obs-title-line">
              <h1>{selected.title}</h1>
              <Badge status={selected.status} />
            </div>
            <div className="obs-run-meta">
              <span>{selected.workflowName}</span>
              <span>·</span>
              <code>{selected.id}</code>
              <span className="obs-demo">
                <span /> Demo request
              </span>
            </div>
          </div>
          <Risk risk={selected.risk} />
        </div>
        {selected.status === 'pending' ? (
          <div className="obs-alert warning">
            <ShieldQuestion size={21} />
            <div>
              <strong>Your review is needed</strong>
              <p>The workflow is paused until you approve or reject this action.</p>
            </div>
            <span className="obs-request-time">
              <Clock3 size={14} /> {relativeTime(selected.requestedAt)}
            </span>
          </div>
        ) : (
          <div
            className={`obs-alert ${selected.status === 'approved' ? 'success' : selected.status === 'expired' ? 'warning' : 'error'}`}
          >
            <FileCheck2 size={21} />
            <div>
              <strong>
                {selected.status === 'expired'
                  ? 'This request has expired'
                  : `This request was ${selected.status}`}
              </strong>
              <p>
                {selected.status === 'expired'
                  ? 'This request can no longer receive a decision. Open the workflow to start a new simulated run.'
                  : `${selected.decisionAt ? new Date(selected.decisionAt).toLocaleString() + ' · ' : ''}${selected.comment || 'No decision note was provided.'}`}
              </p>
            </div>
          </div>
        )}
        <div className="obs-approval-detail-grid">
          <div className="obs-approval-main">
            <section className="card obs-approval-section">
              <div className="obs-section-heading">
                <div>
                  <h2>Request context</h2>
                  <p>Understand the action before making a decision.</p>
                </div>
                <ShieldCheck size={21} />
              </div>
              <p className="obs-request-description">{selected.description}</p>
              <dl className="obs-context-grid">
                <div>
                  <dt>Workflow</dt>
                  <dd>{selected.workflowName}</dd>
                </div>
                <div>
                  <dt>Requested</dt>
                  <dd>{new Date(selected.requestedAt).toLocaleString()}</dd>
                </div>
                <div>
                  <dt>Execution</dt>
                  <dd>
                    <Link to={`/executions/${selected.executionId}`}>
                      {selected.executionId} <ExternalLink size={12} />
                    </Link>
                  </dd>
                </div>
                <div>
                  <dt>Approval step</dt>
                  <dd>
                    {execution?.graph.nodes.find((n) => n.id === selected.nodeId)?.label ||
                      selected.nodeId}
                  </dd>
                </div>
              </dl>
            </section>
            <section className="card obs-approval-section">
              <div className="obs-section-heading">
                <div>
                  <h2>Input data</h2>
                  <p>The information available when this request was created.</p>
                </div>
              </div>
              <JsonViewer data={selected.data} />
            </section>
            <section className="card obs-approval-section">
              <div className="obs-section-heading">
                <div>
                  <h2>Previous execution steps</h2>
                  <p>The path taken to reach this approval.</p>
                </div>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => navigate(`/executions/${selected.executionId}`)}
                >
                  View execution <ArrowRight size={14} />
                </Button>
              </div>
              <div className="obs-previous-steps">
                {execution?.nodeRuns
                  .filter(
                    (run) =>
                      run.status === 'succeeded' &&
                      execution.graph.nodes.findIndex((n) => n.id === run.nodeId) <
                        execution.graph.nodes.findIndex((n) => n.id === selected.nodeId),
                  )
                  .map((run, index) => (
                    <div className="obs-previous-step" key={run.nodeId}>
                      <span className="obs-step-number">{index + 1}</span>
                      <strong>
                        {execution.graph.nodes.find((n) => n.id === run.nodeId)?.label ||
                          run.nodeId}
                      </strong>
                      <CheckCircle2 size={16} />
                    </div>
                  ))}
                {!execution && (
                  <p className="muted">The execution snapshot is no longer available.</p>
                )}
              </div>
            </section>
          </div>
          <aside className="obs-approval-aside">
            <section className="card obs-approval-section">
              <div className="obs-section-heading">
                <div>
                  <h2>What happens next?</h2>
                  <p>A human decision is part of this workflow.</p>
                </div>
              </div>
              <div className="obs-consequence">
                <span className="approve">
                  <Check size={16} />
                </span>
                <div>
                  <h4>If approved</h4>
                  <p>
                    The demo run resumes along the approval branch and processes its connected
                    steps.
                  </p>
                </div>
              </div>
              <div className="obs-consequence">
                <span className="reject">
                  <X size={16} />
                </span>
                <div>
                  <h4>If rejected</h4>
                  <p>
                    The demo run follows the rejection branch and skips the approved action. Its
                    history, data, and your decision remain available.
                  </p>
                </div>
              </div>
              {selected.status === 'pending' && (
                <div className="obs-decision-buttons">
                  <Button variant="primary" onClick={() => openDecision(selected, 'approved')}>
                    <Check size={16} /> Approve request
                  </Button>
                  <Button variant="secondary" onClick={() => openDecision(selected, 'rejected')}>
                    <X size={16} /> Reject request
                  </Button>
                </div>
              )}
            </section>
            <div className="obs-simulation-note">
              <ShieldCheck size={17} />
              <p>
                Approvals only affect this local simulation. No payment, email, or external action
                will be performed.
              </p>
            </div>
          </aside>
        </div>
        {confirmation}
      </div>
    );

  return (
    <div className="obs-page">
      <PageHeader
        title="Approvals"
        description="Human judgment, right where it matters."
        actions={
          <div className="obs-review-count">
            <span className="obs-status-dot waiting" /> {pendingCount} awaiting review
          </div>
        }
      />
      <div className="obs-approval-intro">
        <div className="obs-approval-intro-icon">
          <ShieldCheck size={23} />
        </div>
        <div>
          <h3>A thoughtful pause before the next step.</h3>
          <p>
            Review sensitive actions, inspect the context, and keep your workflows moving with
            confidence.
          </p>
        </div>
        <span className="obs-demo">
          <span /> Simulated approvals
        </span>
      </div>
      <div className="obs-approval-filterbar">
        <div className="obs-status-tabs" role="tablist" aria-label="Approval status">
          {tabs.map((status) => (
            <button
              key={status}
              className={tab === status ? 'active' : ''}
              onClick={() => setTab(status)}
              role="tab"
              aria-selected={tab === status}
            >
              {status === 'all' ? 'All requests' : status.charAt(0).toUpperCase() + status.slice(1)}
              <span>
                {status === 'all'
                  ? approvals.length
                  : approvals.filter((a) => a.status === status).length}
              </span>
            </button>
          ))}
        </div>
        <SearchInput value={search} onChange={setSearch} placeholder="Search requests..." />
      </div>
      {filtered.length ? (
        <div className="obs-approval-cards">
          {filtered.map((approval) => (
            <article className="card obs-approval-card" key={approval.id}>
              <div className="obs-approval-card-top">
                <span className={`obs-approval-icon ${approval.status}`}>
                  <ShieldQuestion size={20} />
                </span>
                <div>
                  <strong>{approval.workflowName}</strong>
                  <span>
                    <Clock3 size={12} /> {relativeTime(approval.requestedAt)}
                  </span>
                </div>
                <Badge status={approval.status} />
              </div>
              <button
                className="obs-approval-title"
                onClick={() => navigate(`/approvals/${approval.id}`)}
              >
                <h3>{approval.title}</h3>
                <ArrowRight size={17} />
              </button>
              <p>{approval.description}</p>
              <div className="obs-approval-data">
                {Object.entries(approval.data)
                  .slice(0, 3)
                  .map(([key, value]) => (
                    <div key={key}>
                      <span>{key.replaceAll('_', ' ')}</span>
                      <strong title={dataValue(value)}>{dataValue(value)}</strong>
                    </div>
                  ))}
              </div>
              {approval.comment && (
                <div className="obs-decision-note">
                  <MessageSquare size={13} />
                  <span>{approval.comment}</span>
                </div>
              )}
              <div className="obs-approval-card-footer">
                <Risk risk={approval.risk} />
                <div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => navigate(`/approvals/${approval.id}`)}
                  >
                    View details <ArrowRight size={13} />
                  </Button>
                  {approval.status === 'pending' && (
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => navigate(`/approvals/${approval.id}`)}
                    >
                      Review request
                    </Button>
                  )}
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="card">
          <EmptyState
            title={
              search
                ? 'No matching requests'
                : tab === 'pending'
                  ? 'You’re all caught up'
                  : `No ${tab === 'all' ? '' : tab + ' '}requests yet`
            }
            description={
              search
                ? 'Try a different search or clear your search terms.'
                : tab === 'pending'
                  ? 'Approval requests will appear here when a workflow needs a human decision.'
                  : 'Run a workflow with an approval step to see requests here.'
            }
            action={
              search ? (
                <Button variant="secondary" onClick={() => setSearch('')}>
                  Clear search
                </Button>
              ) : (
                <Button variant="secondary" onClick={() => navigate('/workflows')}>
                  Explore workflows
                </Button>
              )
            }
          />
        </div>
      )}
      <p className="obs-footnote">
        <ShieldCheck size={14} /> Decisions are recorded in your local demo workspace.
      </p>
      {confirmation}
    </div>
  );
}
