import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  GitBranch,
  Mail,
  Plus,
  RefreshCw,
  Sparkles,
  WandSparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react';
import { useAppStore } from '../stores/useAppStore';
import { Badge, Button, PageHeader } from '../components/ui';
import { nodeRegistry } from '../lib/node-registry';
import {
  createBlankWorkflow,
  generateMockWorkflow,
  generationStages,
  type GeneratedWorkflow,
} from '../services/generation';
import type { Workflow } from '../types';
import './management.css';

const suggestions = [
  {
    icon: Mail,
    title: 'Summarize incoming emails',
    prompt: 'Summarize incoming emails and classify each email by priority.',
  },
  {
    icon: FileText,
    title: 'Process uploaded invoices',
    prompt:
      'Process invoices, extract important details, check whether the amount exceeds ₹50,000, and request approval when necessary.',
  },
  {
    icon: GitBranch,
    title: 'Route support tickets',
    prompt: 'Classify customer support tickets and route them to the right team.',
  },
  {
    icon: FileSpreadsheet,
    title: 'Analyze CSV files',
    prompt: 'Analyze uploaded CSV files and generate a concise summary report.',
  },
];

export default function CreateWorkflow() {
  const navigate = useNavigate();
  const { saveWorkflow } = useAppStore();
  const [prompt, setPrompt] = useState('');
  const [step, setStep] = useState(-1);
  const [preview, setPreview] = useState<GeneratedWorkflow | null>(null);
  const [error, setError] = useState('');
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearInterval(timer.current);
    },
    [],
  );
  const generate = () => {
    if (timer.current) clearInterval(timer.current);
    const result = generateMockWorkflow(prompt);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setError('');
    setPreview(null);
    setStep(0);
    let current = 0;
    timer.current = setInterval(() => {
      current += 1;
      if (current >= generationStages.length) {
        if (timer.current) clearInterval(timer.current);
        setStep(-1);
        setPreview(result);
      } else setStep(current);
    }, 550);
  };
  const blank = () => {
    const workflow = createBlankWorkflow();
    saveWorkflow(workflow);
    navigate(`/workflows/${workflow.id}/edit`);
  };
  return (
    <div className="management-page create-page">
      <button className="text-back" onClick={() => navigate('/workflows')}>
        <ArrowLeft size={15} /> Back to workflows
      </button>
      <PageHeader
        title="Create a workflow"
        description="From a simple idea to a powerful automation."
      />
      <div className="create-layout">
        <div className="create-main">
          <section className="card prompt-card">
            <div className="ai-label">
              <Sparkles size={15} /> AI WORKFLOW BUILDER <span>DEMO</span>
            </div>
            <h2>What would you like to automate?</h2>
            <p>Describe your goal. We’ll turn it into a workflow you can make your own.</p>
            <label className="sr-only" htmlFor="workflow-prompt">
              Describe your workflow
            </label>
            <textarea
              id="workflow-prompt"
              className="prompt-input"
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                setError('');
                setPreview(null);
              }}
              placeholder="Whenever a new invoice arrives, extract its details, validate the amount, and request approval if it exceeds ₹50,000..."
              rows={6}
              disabled={step >= 0}
            />
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="prompt-footer">
              <span>
                <WandSparkles size={14} /> Be specific about triggers, actions, and conditions.
              </span>
              <Button
                variant="primary"
                onClick={generate}
                loading={step >= 0}
                disabled={step >= 0 || !prompt.trim()}
              >
                <Sparkles size={16} /> {step >= 0 ? 'Generating...' : 'Generate workflow'}
              </Button>
            </div>
          </section>
          {step >= 0 && (
            <section className="card generation-progress" aria-live="polite">
              <span className="generation-spark">
                <Sparkles size={22} />
              </span>
              <div>
                <h3>Building your automation</h3>
                <p>Choosing a deterministic demo fixture for your request.</p>
                <div className="generation-steps">
                  {generationStages.map((label, i) => (
                    <div key={label} className={i <= step ? 'complete' : ''}>
                      {i < step ? (
                        <CheckCircle2 size={16} />
                      ) : (
                        <span className={i === step ? 'step-dot pulsing' : 'step-dot'} />
                      )}
                      {label}
                    </div>
                  ))}
                </div>
              </div>
            </section>
          )}
          {preview && (
            <section className="card generation-preview">
              <div className="preview-heading">
                <div>
                  <span className="preview-ready">
                    <CheckCircle2 size={15} /> Your workflow is ready
                  </span>
                  <h2>{preview.workflow.name}</h2>
                </div>
                <Badge status="draft" />
              </div>
              <p className="muted">{preview.workflow.description}</p>
              <div className="preview-meta">
                <span>
                  <GitBranch size={15} />
                  {preview.workflow.nodes.length} connected steps
                </span>
                <span>
                  <Check size={15} />
                  Demo configuration included
                </span>
              </div>
              <WorkflowPreview workflow={preview.workflow} />
              <div className="preview-requirements">
                <strong>Required integrations</strong>
                <div>
                  {preview.requiredIntegrations.map((name) => (
                    <span key={name}>{name}</span>
                  ))}
                </div>
              </div>
              <div className="preview-note">
                <FileText size={16} />
                <ul>
                  {preview.configurationNotes.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              </div>
              <div className="preview-buttons">
                <Button
                  variant="ghost"
                  onClick={() => {
                    setPreview(null);
                    document.getElementById('workflow-prompt')?.focus();
                  }}
                >
                  Edit description
                </Button>
                <Button variant="secondary" onClick={generate}>
                  <RefreshCw size={15} /> Regenerate
                </Button>
                <Button
                  variant="primary"
                  onClick={() => {
                    saveWorkflow(preview.workflow);
                    navigate(`/workflows/${preview.workflow.id}/edit`);
                  }}
                >
                  Create workflow <ArrowRight size={16} />
                </Button>
              </div>
            </section>
          )}
          {step < 0 && !preview && (
            <section className="suggestion-section">
              <h3>Start with an idea</h3>
              <div className="prompt-suggestions">
                {suggestions.map(({ icon: Icon, title, prompt: suggestion }) => (
                  <button key={title} onClick={() => setPrompt(suggestion)}>
                    <Icon size={18} />
                    <span>{title}</span>
                    <ArrowUpRightIcon />
                  </button>
                ))}
              </div>
              <p className="generation-prototype-note">
                This is a local prototype. Generation uses supported workflow examples, without
                calling an AI provider.
              </p>
            </section>
          )}
        </div>
        <aside className="create-aside">
          <div className="card blank-card">
            <span className="blank-icon">
              <Plus size={24} />
            </span>
            <h3>Start from a blank canvas</h3>
            <p>Know what you want to build? Add nodes and connect the dots yourself.</p>
            <Button variant="secondary" onClick={blank}>
              Build from scratch <ArrowRight size={15} />
            </Button>
          </div>
          <div className="create-tips">
            <h4>A little detail goes a long way</h4>
            <p>
              <span>01</span> Start with what triggers your workflow.
            </p>
            <p>
              <span>02</span> Describe the actions you need.
            </p>
            <p>
              <span>03</span> Add conditions or approval steps.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function ArrowUpRightIcon() {
  return <ArrowRight className="suggestion-arrow" size={15} />;
}

function WorkflowPreview({ workflow }: { workflow: Workflow }) {
  const arrowId = useId().replaceAll(':', '');
  const nodeWidth = 168;
  const nodeHeight = 94;
  const minX = Math.min(...workflow.nodes.map((node) => node.position.x));
  const minY = Math.min(...workflow.nodes.map((node) => node.position.y));
  const positions = new Map(
    workflow.nodes.map((node) => [
      node.id,
      { x: (node.position.x - minX) * 0.76 + 25, y: (node.position.y - minY) * 0.6 + 30 },
    ]),
  );
  const width =
    Math.max(...Array.from(positions.values()).map((position) => position.x)) + nodeWidth + 30;
  const height =
    Math.max(...Array.from(positions.values()).map((position) => position.y)) + nodeHeight + 30;
  return (
    <>
      <div className="preview-graph-legend">
        <span>WORKFLOW PREVIEW</span>
        <span>
          Scroll to inspect all steps and branches <ArrowRight size={12} />
        </span>
      </div>
      <div
        className="preview-graph"
        tabIndex={0}
        aria-label="Read-only workflow graph. Scroll horizontally to inspect all connected steps."
      >
        <div className="preview-graph-canvas" style={{ width, height }}>
          <svg
            className="preview-graph-edges"
            width={width}
            height={height}
            aria-label="Workflow connections"
          >
            <defs>
              <marker id={arrowId} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="currentColor" />
              </marker>
            </defs>
            {workflow.edges.map((edge) => {
              const source = positions.get(edge.source);
              const target = positions.get(edge.target);
              if (!source || !target) return null;
              const node = workflow.nodes.find((item) => item.id === edge.source)!;
              const outputs = nodeRegistry[node.type].outputs;
              const handleIndex = Math.max(0, outputs.indexOf(edge.sourceHandle || 'default'));
              const x1 = source.x + nodeWidth;
              const y1 =
                source.y + nodeHeight * (outputs.length > 1 ? 0.36 + handleIndex * 0.32 : 0.5);
              const x2 = target.x;
              const y2 = target.y + nodeHeight / 2;
              const middle = (x1 + x2) / 2;
              return (
                <g key={edge.id}>
                  <title>
                    {node.label} → {workflow.nodes.find((item) => item.id === edge.target)?.label}
                    {edge.sourceHandle ? ` (${edge.sourceHandle})` : ''}
                  </title>
                  <path
                    d={`M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2 - 5} ${y2}`}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    markerEnd={`url(#${arrowId})`}
                  />
                  {edge.sourceHandle && (
                    <text x={x1 + 8} y={y1 - 7} className="preview-edge-label">
                      {edge.sourceHandle}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {workflow.nodes.map((node) => {
            const Icon = nodeRegistry[node.type].icon || WorkflowIcon;
            const position = positions.get(node.id)!;
            return (
              <div
                key={node.id}
                className={`preview-node ${nodeRegistry[node.type].category === 'AI' ? 'ai-node' : ''}`}
                style={{ left: position.x, top: position.y, width: nodeWidth, height: nodeHeight }}
              >
                <span>
                  <Icon size={15} />
                </span>
                <strong>{node.label}</strong>
                <small>{nodeRegistry[node.type].name}</small>
              </div>
            );
          })}
        </div>
      </div>
    </>
  );
}
