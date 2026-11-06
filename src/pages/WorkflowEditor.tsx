import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useBlocker, useNavigate, useParams } from 'react-router-dom';
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  type Connection,
  type EdgeChange,
  type NodeChange,
  type NodePositionChange,
  type ReactFlowInstance,
} from '@xyflow/react';
import {
  AlertCircle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronUp,
  Columns3,
  GitBranch,
  LayoutGrid,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Play,
  Plus,
  Redo2,
  Save,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
import '@xyflow/react/dist/style.css';
import { Badge, Button, EmptyState, Modal } from '../components/ui';
import WorkflowNodeCard, { type CanvasNode } from '../components/workflow/WorkflowNodeCard';
import NodeConfigForm from '../components/workflow/NodeConfigForm';
import { autoLayout, canConnect, validateWorkflow } from '../lib/graph';
import { createNode, nodeRegistry } from '../lib/node-registry';
import { useAppStore } from '../stores/useAppStore';
import type { NodeCategory, NodeType, Workflow } from '../types';
import './editor.css';

const nodeTypes = { workflow: WorkflowNodeCard };
const categories: NodeCategory[] = ['Trigger', 'AI', 'Logic', 'Tool', 'Human'];
const categoryLabels: Record<NodeCategory, string> = {
  Trigger: 'Triggers',
  AI: 'AI & language models',
  Logic: 'Logic & flow',
  Tool: 'Tools & integrations',
  Human: 'Human in the loop',
};
const clone = <T,>(value: T): T => structuredClone(value);
interface Suggestion {
  title: string;
  description: string;
  workflow: Workflow;
  baseFingerprint: string;
}

export default function WorkflowEditor() {
  const { workflowId } = useParams();
  const workflow = useAppStore((state) => state.workflows.find((item) => item.id === workflowId));
  const navigate = useNavigate();
  if (!workflow)
    return (
      <div className="page">
        <EmptyState
          icon={<GitBranch />}
          title="Workflow not found"
          description="This workflow may have been removed. Choose another workflow or create a new one."
          action={<Button onClick={() => navigate('/workflows')}>View workflows</Button>}
        />
      </div>
    );
  return <Editor key={workflow.id} initial={workflow} />;
}

function Editor({ initial }: { initial: Workflow }) {
  const navigate = useNavigate();
  const saveWorkflow = useAppStore((state) => state.saveWorkflow);
  const runWorkflow = useAppStore((state) => state.runWorkflow);
  const notify = useAppStore((state) => state.notify);
  const [draft, setDraftState] = useState(() => clone(initial));
  const draftRef = useRef(draft);
  const savedRef = useRef(JSON.stringify(initial));
  const [saved, setSaved] = useState(savedRef.current);
  const savedVersion = useRef(initial.version);
  const [past, setPast] = useState<Workflow[]>([]);
  const [future, setFuture] = useState<Workflow[]>([]);
  const [selection, setSelection] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [selectedEdges, setSelectedEdges] = useState<string[]>([]);
  const [libraryOpen, setLibraryOpen] = useState(true);
  const [search, setSearch] = useState('');
  const [validationOpen, setValidationOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [prompt, setPrompt] = useState('');
  const [planning, setPlanning] = useState(false);
  const [suggestion, setSuggestion] = useState<Suggestion>();
  const [assistantError, setAssistantError] = useState('');
  const [flow, setFlow] = useState<ReactFlowInstance<CanvasNode>>();
  const canvasRef = useRef<HTMLDivElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const dirty = JSON.stringify(draft) !== saved;
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      JSON.stringify(draftRef.current) !== savedRef.current &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search),
  );
  const issues = useMemo(() => validateWorkflow(draft), [draft]);
  const selectedNode = draft.nodes.find((node) => node.id === selectedId);
  const assignDraft = useCallback((next: Workflow) => {
    draftRef.current = next;
    setDraftState(next);
  }, []);
  const commit = useCallback(
    (next: Workflow | ((current: Workflow) => Workflow), remember = true) => {
      const current = draftRef.current;
      const value = typeof next === 'function' ? next(current) : next;
      if (JSON.stringify(current) === JSON.stringify(value)) return;
      if (remember) {
        setPast((history) => [...history.slice(-49), clone(current)]);
        setFuture([]);
      }
      assignDraft(value);
      setSuggestion(undefined);
    },
    [assignDraft],
  );
  const undo = useCallback(() => {
    const previous = past.at(-1);
    if (!previous) return;
    setFuture((items) => [clone(draftRef.current), ...items]);
    setPast((items) => items.slice(0, -1));
    assignDraft(clone(previous));
    setSuggestion(undefined);
  }, [assignDraft, past]);
  const redo = useCallback(() => {
    const next = future[0];
    if (!next) return;
    setPast((items) => [...items, clone(draftRef.current)]);
    setFuture((items) => items.slice(1));
    assignDraft(clone(next));
    setSuggestion(undefined);
  }, [assignDraft, future]);
  const save = useCallback(
    (announce = true) => {
      if (JSON.stringify(draftRef.current) === savedRef.current) return draftRef.current;
      savedVersion.current += 1;
      const next = {
        ...draftRef.current,
        updatedAt: new Date().toISOString(),
        version: savedVersion.current,
      };
      saveWorkflow(next);
      assignDraft(next);
      savedRef.current = JSON.stringify(next);
      setSaved(savedRef.current);
      setSuggestion(undefined);
      if (!announce) setValidationOpen(false);
      return next;
    },
    [assignDraft, saveWorkflow],
  );
  const removeNodes = useCallback(
    (ids: string[]) => {
      commit((current) => ({
        ...current,
        nodes: current.nodes.filter((node) => !ids.includes(node.id)),
        edges: current.edges.filter(
          (edge) => !ids.includes(edge.source) && !ids.includes(edge.target),
        ),
      }));
      setSelection([]);
      setSelectedId(undefined);
    },
    [commit],
  );
  const nodes: CanvasNode[] = useMemo(
    () =>
      draft.nodes.map((node) => ({
        id: node.id,
        type: 'workflow',
        position: node.position,
        selected: selection.includes(node.id),
        data: {
          node,
          issueCount: issues.filter((issue) => issue.nodeId === node.id).length,
          onRemove: (id: string) => removeNodes([id]),
        },
      })),
    [draft.nodes, issues, selection, removeNodes],
  );
  const edges = useMemo(
    () =>
      draft.edges.map((edge) => ({
        ...edge,
        selected: selectedEdges.includes(edge.id),
        type: 'smoothstep',
        markerEnd: { type: MarkerType.ArrowClosed, width: 17, height: 17 },
        style: { strokeWidth: 1.6 },
        labelStyle: { fontSize: 10 },
        labelBgPadding: [5, 3] as [number, number],
        labelBgBorderRadius: 4,
      })),
    [draft.edges, selectedEdges],
  );

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (JSON.stringify(draftRef.current) !== savedRef.current) {
        event.preventDefault();
        event.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, []);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      if (event.key.toLowerCase() === 's') {
        event.preventDefault();
        save();
        return;
      }
      if (
        (event.target as HTMLElement).matches('input, textarea, select, [contenteditable="true"]')
      )
        return;
      if (event.key.toLowerCase() === 'z') {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      }
      if (event.key.toLowerCase() === 'y') {
        event.preventDefault();
        redo();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [redo, save, undo]);
  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const addNode = (type: NodeType, position?: { x: number; y: number }) => {
    if (nodeRegistry[type].comingSoon) {
      notify('This trigger will be available when the backend is connected.', 'info');
      return;
    }
    const rect = canvasRef.current?.getBoundingClientRect();
    const center =
      rect && flow
        ? flow.screenToFlowPosition({
            x: rect.x + rect.width / 2 - 100,
            y: rect.y + rect.height / 2 - 60,
          })
        : { x: 260, y: 220 };
    const node = createNode(type, position || center);
    commit((current) => ({ ...current, nodes: [...current.nodes, node] }));
    setSelection([node.id]);
    setSelectedId(node.id);
  };
  const onNodesChange = (changes: NodeChange<CanvasNode>[]) => {
    const removed = changes.filter((change) => change.type === 'remove').map((change) => change.id);
    if (removed.length) {
      removeNodes(removed);
      return;
    }
    const selects = changes.filter((change) => change.type === 'select');
    if (selects.length)
      setSelection((current) => {
        let result = [...current];
        selects.forEach((change) => {
          result = change.selected
            ? [...new Set([...result, change.id])]
            : result.filter((id) => id !== change.id);
        });
        return result;
      });
    const positions = changes.filter(
      (change): change is NodePositionChange =>
        change.type === 'position' && Boolean(change.position),
    );
    if (positions.length)
      commit(
        (current) => ({
          ...current,
          nodes: current.nodes.map((node) => {
            const position = positions.find((change) => change.id === node.id)?.position;
            return position ? { ...node, position } : node;
          }),
        }),
        false,
      );
  };
  const onEdgesChange = (changes: EdgeChange[]) => {
    const removed = changes.filter((change) => change.type === 'remove').map((change) => change.id);
    if (removed.length)
      commit((current) => ({
        ...current,
        edges: current.edges.filter((edge) => !removed.includes(edge.id)),
      }));
    const selects = changes.filter((change) => change.type === 'select');
    if (selects.length)
      setSelectedEdges((current) => {
        let result = [...current];
        selects.forEach((change) => {
          result = change.selected
            ? [...new Set([...result, change.id])]
            : result.filter((id) => id !== change.id);
        });
        return result;
      });
  };
  const connect = (connection: Connection) => {
    if (!canConnect(draftRef.current, connection)) {
      notify('Connect distinct nodes in a one-way flow. Triggers cannot have inputs.', 'error');
      return;
    }
    const source = draftRef.current.nodes.find((node) => node.id === connection.source);
    commit((current) => ({
      ...current,
      edges: [
        ...current.edges,
        {
          id: `edge-${crypto.randomUUID()}`,
          source: connection.source,
          target: connection.target,
          sourceHandle: connection.sourceHandle || undefined,
          label: source?.type === 'condition' ? connection.sourceHandle || undefined : undefined,
        },
      ],
    }));
  };
  const layout = () => {
    commit((current) => autoLayout(current));
    requestAnimationFrame(() => flow?.fitView({ padding: 0.18, duration: 250 }));
  };
  const validate = () => {
    setValidationOpen(true);
    notify(
      issues.length
        ? `${issues.length} ${issues.length === 1 ? 'issue needs' : 'issues need'} your attention.`
        : 'All checks passed. Your workflow is ready for a demo run.',
      issues.length ? 'error' : 'success',
    );
  };
  const run = () => {
    if (draft.status === 'archived') {
      notify('Restore this workflow before running a demo.', 'error');
      return;
    }
    if (issues.length) {
      setValidationOpen(true);
      notify('Resolve validation issues before running this workflow.', 'error');
      return;
    }
    const current = dirty ? save(false) : draft;
    const id = runWorkflow(current.id);
    if (id) navigate(`/executions/${id}`);
  };
  const propose = () => {
    if (!prompt.trim()) {
      setAssistantError('Describe a change first. Try “Add an email notification after approval.”');
      return;
    }
    if (timerRef.current) clearTimeout(timerRef.current);
    const baseFingerprint = JSON.stringify(draftRef.current);
    const text = prompt.toLowerCase();
    setPlanning(true);
    setSuggestion(undefined);
    setAssistantError('');
    timerRef.current = setTimeout(() => {
      if (JSON.stringify(draftRef.current) !== baseFingerprint) {
        setAssistantError(
          'Your workflow changed while planning. Generate a new proposal to include your latest edits.',
        );
        setPlanning(false);
        return;
      }
      const current = clone(draftRef.current);
      if (/notification|email|notify/.test(text)) {
        const anchor =
          current.nodes.find((node) => node.type === 'approval') ||
          current.nodes.find(
            (node) => node.type !== 'end' && !current.edges.some((edge) => edge.source === node.id),
          );
        const end = current.nodes.find((node) => node.type === 'end');
        const beforeEnd = end && current.edges.find((edge) => edge.target === end.id);
        const source = anchor || current.nodes.find((node) => node.id === beforeEnd?.source);
        if (!source) {
          setAssistantError('Add a trigger or an approval step before adding a notification.');
          setPlanning(false);
          return;
        }
        const node = createNode('http', { x: source.position.x + 290, y: source.position.y + 160 });
        node.label = 'Send email notification';
        node.config = {
          ...node.config,
          method: 'POST',
          url: 'https://example.com/demo/notifications',
          headers: '{"Content-Type":"application/json"}',
          body: '{"to":"finance@example.com","message":"Invoice approved"}',
          description: 'Demo notification; no email is sent.',
        };
        const outgoing = current.edges.find((edge) => edge.source === source.id);
        current.nodes.push(node);
        if (outgoing) {
          current.edges = current.edges.map((edge) =>
            edge.id === outgoing.id ? { ...edge, target: node.id } : edge,
          );
          current.edges.push({
            id: `edge-${crypto.randomUUID()}`,
            source: node.id,
            sourceHandle: nodeRegistry.http.outputs[0],
            target: outgoing.target,
          });
        } else
          current.edges.push({
            id: `edge-${crypto.randomUUID()}`,
            source: source.id,
            sourceHandle: nodeRegistry[source.type].outputs[0],
            target: node.id,
          });
        setSuggestion({
          title: 'Add an email notification',
          description: `Insert one HTTP notification step after “${source.label}” and preserve the downstream connection. This uses a demo endpoint; no message is sent.`,
          workflow: current,
          baseFingerprint,
        });
      } else if (/retr(y|ies)|resilien/.test(text)) {
        const count = current.nodes.filter(
          (node) => !['manual', 'webhook', 'schedule', 'end'].includes(node.type),
        ).length;
        current.nodes = current.nodes.map((node) =>
          ['manual', 'webhook', 'schedule', 'end'].includes(node.type)
            ? node
            : {
                ...node,
                config: { ...node.config, retries: 2, timeout: node.config.timeout || 30 },
              },
        );
        setSuggestion({
          title: 'Add a retry policy',
          description: `Set two retries on ${count} action ${count === 1 ? 'step' : 'steps'} and a 30-second timeout where one is missing. Existing prompts and routes stay intact.`,
          workflow: current,
          baseFingerprint,
        });
      } else if (/layout|arrang|tidy|organiz/.test(text)) {
        setSuggestion({
          title: 'Organize the canvas',
          description:
            'Arrange steps from left to right by dependency, placing parallel branches on separate rows.',
          workflow: autoLayout(current),
          baseFingerprint,
        });
      } else
        setAssistantError(
          'This prototype supports three edits: add an email notification, add retries, or organize the canvas. Try one of these requests.',
        );
      setPlanning(false);
    }, 650);
  };
  const applySuggestion = () => {
    if (!suggestion) return;
    if (JSON.stringify(draftRef.current) !== suggestion.baseFingerprint) {
      setSuggestion(undefined);
      setAssistantError(
        'Your workflow changed after this proposal. Generate it again before applying.',
      );
      return;
    }
    commit(suggestion.workflow);
    notify('Suggested changes applied. Review and save your workflow.', 'success');
  };

  return (
    <div className="workflow-editor">
      <header className="editor-header">
        <button
          className="editor-icon-button editor-back"
          aria-label="Back to workflows"
          onClick={() => navigate('/workflows')}
        >
          <ArrowLeft size={18} />
        </button>
        <div className="editor-title">
          <div>
            <input
              aria-label="Workflow name"
              value={draft.name}
              onChange={(event) => commit((current) => ({ ...current, name: event.target.value }))}
            />
            <Badge status={draft.status} />
          </div>
          <span>
            <span className={`save-state-dot ${dirty ? 'unsaved' : ''}`} />
            {dirty ? 'Unsaved changes' : 'All changes saved'}
            <span className="editor-version">Version {draft.version}</span>
          </span>
        </div>
        <div className="editor-header-actions">
          <div className="editor-history">
            <button
              className="editor-icon-button"
              aria-label="Undo"
              title="Undo (Ctrl/Cmd Z)"
              disabled={!past.length}
              onClick={undo}
            >
              <Undo2 size={16} />
            </button>
            <button
              className="editor-icon-button"
              aria-label="Redo"
              title="Redo (Ctrl/Cmd Shift Z)"
              disabled={!future.length}
              onClick={redo}
            >
              <Redo2 size={16} />
            </button>
          </div>
          <Button variant="ghost" size="sm" onClick={validate}>
            <ShieldCheck size={15} />
            <span className="editor-action-label">Validate</span>
          </Button>
          <Button variant="secondary" size="sm" onClick={() => save()} disabled={!dirty}>
            <Save size={14} />
            <span className="editor-action-label">Save</span>
          </Button>
          <Button variant="primary" size="sm" onClick={run}>
            <Play size={14} fill="currentColor" />
            Run<span className="run-demo-label"> demo</span>
          </Button>
        </div>
      </header>
      <div className="editor-subheader">
        <span>
          <GitBranch size={13} />
          Visual workflow editor<span className="editor-prototype-label">Prototype</span>
        </span>
        <span className="muted">Design, connect, and test your automation</span>
      </div>
      <div
        className={`editor-workspace ${libraryOpen ? '' : 'library-collapsed'} ${selectedNode ? 'has-config' : ''}`}
      >
        {libraryOpen && (
          <aside className="node-library">
            <div className="library-title">
              <strong>Node library</strong>
              <button
                className="editor-icon-button"
                title="Collapse node library"
                aria-label="Collapse node library"
                onClick={() => setLibraryOpen(false)}
              >
                <PanelLeftClose size={15} />
              </button>
            </div>
            <div className="library-search">
              <Search size={14} />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Find a node…"
                aria-label="Search node library"
              />
              <kbd>⌕</kbd>
            </div>
            <div className="library-scroll">
              {categories.map((category) => {
                const definitions = Object.values(nodeRegistry).filter(
                  (item) =>
                    item.category === category &&
                    `${item.name} ${item.description}`.toLowerCase().includes(search.toLowerCase()),
                );
                if (!definitions.length) return null;
                return (
                  <section key={category} className="library-group">
                    <h3>
                      {categoryLabels[category]}
                      <span>{definitions.length}</span>
                    </h3>
                    {definitions.map((definition) => {
                      const Icon = definition.icon;
                      return (
                        <button
                          key={definition.type}
                          className={`library-node ${definition.comingSoon ? 'coming-soon' : ''}`}
                          onClick={() => addNode(definition.type)}
                          draggable={!definition.comingSoon}
                          onDragStart={(event) => {
                            event.dataTransfer.setData(
                              'application/agentflow-node',
                              definition.type,
                            );
                            event.dataTransfer.effectAllowed = 'move';
                          }}
                          aria-disabled={definition.comingSoon}
                        >
                          <span className="library-node-icon" style={{ color: definition.color }}>
                            <Icon size={16} />
                          </span>
                          <span>
                            <strong>{definition.name}</strong>
                            <small>
                              {definition.comingSoon ? 'Coming soon' : definition.description}
                            </small>
                          </span>
                          {!definition.comingSoon && <Plus className="library-add" size={13} />}
                        </button>
                      );
                    })}
                  </section>
                );
              })}
              {!Object.values(nodeRegistry).some((item) =>
                `${item.name} ${item.description}`.toLowerCase().includes(search.toLowerCase()),
              ) && <p className="library-empty">No nodes match “{search}”.</p>}
            </div>
            <div className="library-footer">
              <span className="library-drag-icon">
                <Columns3 size={14} />
              </span>
              Drag to canvas, or click to add
            </div>
          </aside>
        )}
        <div
          className="editor-canvas"
          ref={canvasRef}
          onDragOver={(event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
          }}
          onDrop={(event) => {
            event.preventDefault();
            const type = event.dataTransfer.getData('application/agentflow-node') as NodeType;
            if (type in nodeRegistry)
              addNode(type, flow?.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
          }}
        >
          <div className="canvas-top-tools">
            {!libraryOpen && (
              <button
                className="canvas-tool-button"
                onClick={() => setLibraryOpen(true)}
                title="Open node library"
              >
                <PanelLeftOpen size={15} />
                <span>Node library</span>
              </button>
            )}
            <button
              className="canvas-tool-button"
              onClick={layout}
              title="Arrange workflow from left to right"
            >
              <LayoutGrid size={14} />
              Auto-layout
            </button>
            {(selection.length > 0 || selectedEdges.length > 0) && (
              <button
                className="canvas-tool-button danger-tool"
                onClick={() => {
                  if (selection.length) removeNodes(selection);
                  if (selectedEdges.length)
                    commit((current) => ({
                      ...current,
                      edges: current.edges.filter((edge) => !selectedEdges.includes(edge.id)),
                    }));
                  setSelectedEdges([]);
                }}
              >
                <Trash2 size={13} />
                Delete selected
              </button>
            )}
          </div>
          <ReactFlow<CanvasNode>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onInit={setFlow}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={(_, node) => setSelectedId(node.id)}
            onPaneClick={() => {
              setSelectedId(undefined);
              setSelectedEdges([]);
            }}
            onNodeDragStart={() => {
              setPast((history) => [...history.slice(-49), clone(draftRef.current)]);
              setFuture([]);
            }}
            onConnect={connect}
            isValidConnection={(connection) => canConnect(draftRef.current, connection)}
            fitView
            fitViewOptions={{ padding: 0.18, maxZoom: 1 }}
            minZoom={0.25}
            maxZoom={1.8}
            deleteKeyCode={['Backspace', 'Delete']}
            multiSelectionKeyCode={['Meta', 'Control', 'Shift']}
            selectionOnDrag
            defaultEdgeOptions={{ type: 'smoothstep' }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={20} size={1.1} />
            <Controls showInteractive={false} />
            <MiniMap
              pannable
              zoomable
              nodeColor={(node) =>
                nodeRegistry[(node.data as { node: { type: NodeType } }).node.type].color
              }
              nodeStrokeWidth={0}
              maskColor="var(--minimap-mask, rgba(248,250,252,.7))"
            />
          </ReactFlow>
          {!draft.nodes.length && (
            <div className="canvas-empty">
              <div>
                <GitBranch size={25} />
              </div>
              <strong>Start building your workflow</strong>
              <p>Choose a node from the library or describe a change below.</p>
              <Button size="sm" onClick={() => addNode('manual')}>
                <Plus size={14} />
                Add a manual trigger
              </Button>
            </div>
          )}
          <div className="canvas-status">
            <span>
              <span className="live-dot" />
              {draft.nodes.length} nodes<span className="status-separator">/</span>
              {draft.edges.length} connections
            </span>
            <span>
              Scroll to zoom<span className="status-separator">·</span>Shift + drag to select
            </span>
          </div>
          {validationOpen && (
            <section
              className={`validation-panel ${issues.length ? 'has-errors' : 'all-valid'}`}
              aria-label="Workflow validation"
            >
              <div>
                <strong>
                  {issues.length ? (
                    <>
                      <AlertCircle size={16} />
                      {issues.length} validation {issues.length === 1 ? 'issue' : 'issues'}
                    </>
                  ) : (
                    <>
                      <CheckCheck size={16} />
                      Your workflow is ready
                    </>
                  )}
                </strong>
                <button
                  className="editor-icon-button"
                  aria-label="Close validation results"
                  onClick={() => setValidationOpen(false)}
                >
                  <X size={15} />
                </button>
              </div>
              {issues.length ? (
                <ul>
                  {issues.map((issue, index) => (
                    <li key={`${issue.nodeId}-${issue.field}-${index}`}>
                      <button
                        onClick={() => {
                          if (issue.nodeId) {
                            setSelectedId(issue.nodeId);
                            setSelection([issue.nodeId]);
                            flow?.fitView({
                              nodes: [{ id: issue.nodeId }],
                              maxZoom: 1.1,
                              padding: 0.5,
                              duration: 250,
                            });
                          }
                        }}
                      >
                        <AlertCircle size={12} />
                        <span>{issue.message}</span>
                        {issue.nodeId && <ArrowRight size={12} />}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p>
                  Configuration, routes, and graph connections passed local checks. Run a simulation
                  to inspect the result.
                </p>
              )}
            </section>
          )}
        </div>
        {selectedNode && (
          <NodeConfigForm
            key={selectedNode.id}
            node={selectedNode}
            workflow={draft}
            onChange={(node) =>
              commit((current) => ({
                ...current,
                nodes: current.nodes.map((item) => (item.id === node.id ? node : item)),
              }))
            }
            onClose={() => setSelectedId(undefined)}
            onDelete={() => removeNodes([selectedNode.id])}
          />
        )}
      </div>
      <section
        className={`editor-assistant ${assistantOpen ? '' : 'assistant-collapsed'}`}
        aria-label="Workflow AI assistant"
      >
        <div className="assistant-header">
          <div>
            <span className="assistant-icon">
              <Sparkles size={14} />
            </span>
            <strong>Workflow copilot</strong>
            <span className="assistant-prototype">Mock assistant</span>
            <span className="assistant-subtitle">A little help with the next step.</span>
          </div>
          <button
            className="editor-icon-button"
            aria-label={assistantOpen ? 'Collapse workflow assistant' : 'Expand workflow assistant'}
            onClick={() => setAssistantOpen((value) => !value)}
          >
            {assistantOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          </button>
        </div>
        {assistantOpen && (
          <div className="assistant-body">
            {suggestion && (
              <div className="assistant-proposal">
                <span className="proposal-check">
                  <Check size={15} />
                </span>
                <div>
                  <strong>{suggestion.title}</strong>
                  <p>{suggestion.description}</p>
                </div>
                <div className="proposal-actions">
                  <Button variant="ghost" size="sm" onClick={() => setSuggestion(undefined)}>
                    Reject
                  </Button>
                  <Button variant="secondary" size="sm" onClick={propose}>
                    Regenerate
                  </Button>
                  <Button variant="primary" size="sm" onClick={applySuggestion}>
                    Apply changes
                  </Button>
                </div>
              </div>
            )}
            {assistantError && (
              <div className="assistant-error" role="status">
                <AlertCircle size={13} />
                {assistantError}
              </div>
            )}
            <form
              className="assistant-input"
              onSubmit={(event) => {
                event.preventDefault();
                propose();
              }}
            >
              <Sparkles size={16} />
              <input
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="Describe a change… e.g. Add an email notification after approval"
                aria-label="Describe a workflow modification"
                disabled={planning}
              />
              <button type="submit" aria-label="Propose workflow change" disabled={planning}>
                {planning ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              </button>
            </form>
            <div className="assistant-hints">
              <span>Try a suggestion</span>
              {['Add an email notification', 'Add retry policies', 'Organize the canvas'].map(
                (item) => (
                  <button
                    key={item}
                    onClick={() => {
                      setPrompt(item);
                      setAssistantError('');
                    }}
                  >
                    {item}
                    <Plus size={10} />
                  </button>
                ),
              )}
              <span className="assistant-disclaimer">Review every change before applying.</span>
            </div>
          </div>
        )}
      </section>
      <Modal
        open={blocker.state === 'blocked'}
        onClose={() => {
          if (blocker.state === 'blocked') blocker.reset();
        }}
        title="Leave without saving?"
        footer={
          <>
            <Button
              onClick={() => {
                if (blocker.state === 'blocked') blocker.reset();
              }}
            >
              Keep editing
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (blocker.state === 'blocked') blocker.proceed();
              }}
            >
              Leave without saving
            </Button>
          </>
        }
      >
        <p className="muted">
          Your unsaved workflow changes will be lost. Save the workflow to keep them in this
          browser.
        </p>
      </Modal>
    </div>
  );
}
