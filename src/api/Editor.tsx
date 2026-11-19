import { WorkflowJourney, WorkflowReadiness } from './WorkflowJourney';
import { NodeConfiguration } from './NodeConfiguration';
import { date } from './format';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Link,
  useBeforeUnload,
  useBlocker,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';
import { Braces, Download, Play, Plus, Save, ShieldCheck } from 'lucide-react';
import { Badge, Button, JsonViewer, Modal, PageHeader } from '../components/ui';
import { api } from './client';
import Canvas from './Canvas';
import { AgentConnectionPicker, ConnectionSelector, PlannerConnectionPicker } from './Connections';
import { GmailConnectionSelector } from './GmailConnections';
import { InputFieldsEditor } from './InputFieldsEditor';
import { ConnectionReview, ProviderDetails } from './ProviderDetails';
import { Failure, Pending } from './common';
import { summarizeProposal } from './proposalDiff';
import {
  defaultNode,
  downloadDraft,
  parseDefinition,
  parseObject,
  starterDefinition,
} from './graph';
import { useScope } from './session';
import type {
  CatalogItem,
  Definition,
  Validation,
  WorkflowDetail,
  WorkflowEditProposal,
} from './types';

function JsonField<T>({
  label,
  value,
  parse,
  onValue,
  onValidity,
  disabled = false,
}: {
  label: string;
  value: T;
  parse: (text: string) => T;
  onValue: (value: T) => void;
  onValidity: (valid: boolean) => void;
  disabled?: boolean;
}) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState('');
  const serialized = JSON.stringify(value);
  const [observed, setObserved] = useState(serialized);
  if (observed !== serialized) {
    setObserved(serialized);
    setText(JSON.stringify(value, null, 2));
    setError('');
  }
  return (
    <label className="api-json-field">
      <span className="label">{label}</span>
      <textarea
        aria-label={label}
        className="input api-code"
        value={text}
        rows={10}
        disabled={disabled}
        spellCheck={false}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          try {
            const parsed = parse(next);
            setObserved(JSON.stringify(parsed));
            setError('');
            onValidity(true);
            onValue(parsed);
          } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Invalid JSON');
            onValidity(false);
          }
        }}
      />
      {error !== null && (
        <span role="alert" className="api-inline-error">
          {error}
        </span>
      )}
    </label>
  );
}
export default function Editor() {
  const { workflowId = '' } = useParams();
  const [params] = useSearchParams();
  const version = params.get('version_id') || undefined;
  const scope = useScope();
  const workflow = useQuery({
    queryKey: [...scope, 'workflow', workflowId, version],
    queryFn: ({ signal }) => api.workflow(workflowId, version, signal),
  });
  const catalog = useQuery({
    queryKey: [...scope, 'catalog'],
    queryFn: ({ signal }) => api.catalog(signal),
  });
  if (workflow.isPending || catalog.isPending) return <Pending />;
  if (workflow.isError)
    return <Failure error={workflow.error} retry={() => void workflow.refetch()} />;
  if (catalog.isError)
    return <Failure error={catalog.error} retry={() => void catalog.refetch()} />;
  return (
    <Designer
      key={`${workflowId}:${version || 'current'}`}
      initial={workflow.data}
      catalog={catalog.data.items}
      snapshot={!!version}
    />
  );
}
function Designer({
  initial,
  catalog,
  snapshot,
}: {
  initial: WorkflowDetail;
  catalog: CatalogItem[];
  snapshot: boolean;
}) {
  const [saved, setSaved] = useState(initial);
  const [definition, setDefinition] = useState<Definition>(() =>
    structuredClone(initial.version?.definition || starterDefinition()),
  );
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const [report, setReport] = useState<Validation | null>(null);
  const [editPrompt, setEditPrompt] = useState('');
  const [proposalConnections, setProposalConnections] = useState<string[]>([]);
  const [editProposal, setEditProposal] = useState<WorkflowEditProposal | null>(null);
  const [input, setInput] = useState('{}');
  const [maxAttempts, setMaxAttempts] = useState(1);
  const pendingRun = useRef<{ signature: string; key: string } | null>(null);
  const [invalid, setInvalid] = useState<Record<string, boolean>>({});
  const [source, setSource] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [edgeSource, setEdgeSource] = useState('');
  const [edgeTarget, setEdgeTarget] = useState('');
  const [handle, setHandle] = useState('default');
  const navigate = useNavigate();
  const cache = useQueryClient();
  const scope = useScope();
  const allowNavigation = useRef(false);
  const readOnly = saved.status === 'archived' || snapshot;
  const invalidJson = Object.values(invalid).some(Boolean);
  const dirty =
    invalidJson ||
    JSON.stringify({ name, description, definition }) !==
      JSON.stringify({
        name: saved.name,
        description: saved.description,
        definition: saved.version?.definition || null,
      });
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      !allowNavigation.current &&
      (dirty || !!busy) &&
      (currentLocation.pathname !== nextLocation.pathname ||
        currentLocation.search !== nextLocation.search),
  );
  useBeforeUnload(
    useCallback(
      (event: BeforeUnloadEvent) => {
        if (dirty || busy) {
          event.preventDefault();
          event.returnValue = '';
        }
      },
      [dirty, busy],
    ),
  );
  const selectedNode = definition.nodes.find((node) => node.id === selected);
  const selectedContract = catalog.find((item) => item.type === selectedNode?.type);
  useEffect(() => {
    allowNavigation.current = false;
  }, []);
  const validity = (field: string) => (valid: boolean) =>
    setInvalid((old) => ({ ...old, [field]: !valid }));
  const edit = (next: Definition) => {
    setDefinition(next);
    setEditProposal(null);
    setReport(null);
    setNotice('');
  };
  function choose(id: string) {
    if (invalidJson) {
      setError(new Error('Fix or discard the invalid JSON before changing node selection.'));
      return;
    }
    setSelected(id);
  }
  async function save() {
    setBusy('save');
    setError(null);
    setNotice('');
    try {
      const next = await api.save(
        saved.id,
        name,
        description,
        parseDefinition(JSON.stringify(definition)),
        saved.current_version_number,
      );
      setSaved(next);
      setName(next.name);
      setDescription(next.description);
      setDefinition(structuredClone(next.version!.definition));
      setEditProposal(null);
      setNotice(`Saved version ${next.current_version_number} · ${date(next.updated_at)}`);
      void cache.invalidateQueries({ queryKey: [...scope, 'workflows'] });
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy('');
    }
  }
  async function validate() {
    setBusy('validate');
    setError(null);
    try {
      setReport(await api.validate(saved.id, parseDefinition(JSON.stringify(definition))));
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy('');
    }
  }
  async function proposeEdit() {
    if (!saved.current_version_id || dirty || !editPrompt.trim()) return;
    setBusy('proposal');
    setError(null);
    setEditProposal(null);
    try {
      setEditProposal(
        await api.generateWorkflowEdit(
          saved.id,
          saved.current_version_id,
          editPrompt,
          proposalConnections,
        ),
      );
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy('');
    }
  }
  async function run() {
    setBusy('run');
    setError(null);
    try {
      if (!saved.current_version_id || dirty)
        throw new Error('Save your current definition before running.');
      const payload = parseObject(input);
      const signature = JSON.stringify([saved.current_version_id, payload, maxAttempts]);
      if (pendingRun.current?.signature !== signature)
        pendingRun.current = { signature, key: crypto.randomUUID() };
      const checked = await api.validate(saved.id, definition);
      setReport(checked);
      if (!checked.execution_ready) throw new Error('Fix the validation issues before running.');
      const result = await api.run(
        saved.id,
        saved.current_version_id,
        payload,
        pendingRun.current.key,
        maxAttempts,
      );
      pendingRun.current = null;
      void cache.invalidateQueries({ queryKey: [...scope, 'runs'] });
      allowNavigation.current = true;
      navigate(`/executions/${result.id}`);
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy('');
    }
  }
  async function reload() {
    if (snapshot) {
      allowNavigation.current = true;
      navigate(`/workflows/${saved.id}/edit`);
      return;
    }
    if (
      dirty &&
      !window.confirm(
        'Discard this unsaved draft and load the latest saved definition? Download your draft first if you want to retain it.',
      )
    )
      return;
    setBusy('reload');
    setError(null);
    try {
      const next = await api.workflow(saved.id);
      setSaved(next);
      setName(next.name);
      setDescription(next.description);
      setDefinition(structuredClone(next.version?.definition || starterDefinition()));
      setEditProposal(null);
      setSelected(null);
      setInvalid({});
      setSource(false);
      setEpoch((e) => e + 1);
      setReport(null);
      setNotice('Loaded the latest server version.');
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy('');
    }
  }
  const disabled = readOnly || !!busy;
  const palette = (
    <section className="api-palette">
      <h2>Node library</h2>
      <p className="muted">The server advertises these contracts.</p>
      {catalog.map((item) => (
        <Button
          key={item.type}
          disabled={disabled || invalidJson || !item.execution_ready}
          onClick={() => {
            const node = defaultNode(
              item.type,
              definition.nodes.find((n) => n.type === 'manual')?.id || 'start',
              definition.nodes.length,
            );
            edit({ ...definition, nodes: [...definition.nodes, node] });
            setSelected(node.id);
          }}
        >
          <Plus size={14} />
          {item.name}
        </Button>
      ))}
      <p className="muted">
        Connect handles or use the connection form. Validation checks the entire graph before a run.
      </p>
    </section>
  );
  let inspector: ReactNode = (
    <div className="api-panel">
      <h2>Step configuration</h2>
      <p className="muted">
        Select a node to edit its label, typed JSON configuration and upstream input mapping.
      </p>
    </div>
  );
  if (selectedNode)
    inspector = (
      <section className="api-inspector" key={`${selectedNode.id}:${epoch}`}>
        <div className="api-section">
          <h2>{selectedNode.type}</h2>
          <Button
            disabled={disabled}
            variant="ghost"
            onClick={() => {
              edit({
                ...definition,
                nodes: definition.nodes.filter((n) => n.id !== selectedNode.id),
                edges: definition.edges.filter(
                  (e) => e.source !== selectedNode.id && e.target !== selectedNode.id,
                ),
              });
              setSelected(null);
              setInvalid({});
            }}
          >
            Remove
          </Button>
        </div>
        <code>{selectedNode.id}</code>
        <label className="label" htmlFor="node-label">
          Label
        </label>
        <input
          id="node-label"
          className="input"
          maxLength={200}
          disabled={disabled}
          value={selectedNode.label || ''}
          onChange={(e) =>
            edit({
              ...definition,
              nodes: definition.nodes.map((n) =>
                n.id === selectedNode.id ? { ...n, label: e.target.value } : n,
              ),
            })
          }
        />
        {selectedNode.type === 'http' && (
          <ConnectionSelector
            value={
              typeof selectedNode.config.connection_id === 'string'
                ? selectedNode.config.connection_id
                : ''
            }
            disabled={disabled || invalidJson}
            onChange={(id) =>
              edit({
                ...definition,
                nodes: definition.nodes.map((node) =>
                  node.id === selectedNode.id ? { ...node, config: { connection_id: id } } : node,
                ),
              })
            }
          />
        )}
        {selectedNode.type === 'gmail_read' && (
          <GmailConnectionSelector
            value={
              typeof selectedNode.config.connection_id === 'string'
                ? selectedNode.config.connection_id
                : ''
            }
            disabled={disabled || invalidJson}
            onChange={(id) =>
              edit({
                ...definition,
                nodes: definition.nodes.map((node) =>
                  node.id === selectedNode.id
                    ? { ...node, config: { ...node.config, connection_id: id } }
                    : node,
                ),
              })
            }
          />
        )}
        {selectedNode.type !== 'http' && (
          <NodeConfiguration
            key={selectedNode.id}
            node={selectedNode}
            disabled={disabled}
            renderJson={(value, onValue) => (
              <JsonField
                label="Configuration (JSON)"
                value={value}
                parse={parseObject}
                disabled={disabled}
                onValidity={validity('config')}
                onValue={onValue}
              />
            )}
            onChange={(value) =>
              edit({
                ...definition,
                nodes: definition.nodes.map((n) =>
                  n.id === selectedNode.id ? { ...n, config: value } : n,
                ),
              })
            }
          />
        )}
        {selectedNode.type === 'agent' && (
          <label>
            <input
              type="checkbox"
              checked={selectedNode.config.pause_after_tools === true}
              disabled={disabled || invalidJson}
              onChange={(event) =>
                edit({
                  ...definition,
                  nodes: definition.nodes.map((node) =>
                    node.id === selectedNode.id
                      ? {
                          ...node,
                          config: { ...node.config, pause_after_tools: event.target.checked },
                        }
                      : node,
                  ),
                })
              }
            />{' '}
            Pause after each tool. Save its result and continue explicitly from execution details.
          </label>
        )}
        {selectedNode.type === 'agent' && (
          <AgentConnectionPicker
            value={
              Array.isArray(selectedNode.config.connection_ids)
                ? selectedNode.config.connection_ids.filter(
                    (id): id is string => typeof id === 'string',
                  )
                : []
            }
            disabled={disabled || invalidJson}
            onChange={(ids) =>
              edit({
                ...definition,
                nodes: definition.nodes.map((node) =>
                  node.id === selectedNode.id
                    ? { ...node, config: { ...node.config, connection_ids: ids } }
                    : node,
                ),
              })
            }
          />
        )}
        <JsonField
          label="Input mapping (JSON)"
          value={selectedNode.input_mapping || {}}
          disabled={disabled}
          parse={(text) => {
            const value = parseObject(text);
            if (Object.values(value).some((v) => typeof v !== 'string'))
              throw new Error('Mapping values must be upstream output-reference strings.');
            return value as Record<string, string>;
          }}
          onValidity={validity('mapping')}
          onValue={(value) =>
            edit({
              ...definition,
              nodes: definition.nodes.map((n) =>
                n.id === selectedNode.id ? { ...n, input_mapping: value } : n,
              ),
            })
          }
        />
        <small className="muted">
          Use exact references such as $.start.output.amount. Empty mappings use the previous
          output. Numbers and booleans in configuration JSON keep their types.
        </small>
        {invalidJson && (
          <Button
            disabled={disabled}
            onClick={() => {
              setInvalid({});
              setEpoch((value) => value + 1);
            }}
          >
            Discard invalid JSON edits
          </Button>
        )}
        <details>
          <summary>Configuration contract</summary>
          <JsonViewer data={selectedContract?.config_schema || {}} />
        </details>
      </section>
    );
  return (
    <div className="api-page">
      <PageHeader
        title={readOnly ? 'Saved workflow' : 'Workflow editor'}
        description={`${saved.version && saved.version.id !== saved.current_version_id ? 'Historical snapshot · ' : ''}Version ${saved.version?.version_number || 0} · ${dirty && !readOnly ? 'Unsaved changes' : 'Saved definition'}`}
        actions={
          <>
            <Button disabled={!!busy} onClick={() => downloadDraft(name, definition)}>
              <Download size={15} />
              Download draft
            </Button>
            <Button disabled={!!busy} onClick={() => void reload()}>
              Load latest
            </Button>
            <Button
              loading={busy === 'validate'}
              disabled={!!busy || invalidJson}
              onClick={() => void validate()}
            >
              <ShieldCheck size={15} />
              Validate
            </Button>
            <Button
              variant="primary"
              loading={busy === 'save'}
              disabled={disabled || invalidJson || !name.trim()}
              onClick={() => void save()}
            >
              <Save size={15} />
              Save
            </Button>
            {!readOnly && saved.current_version_id && !dirty && (
              <Button asChild>
                <Link to={`/workflows/${saved.id}/run`}>Run workflow</Link>
              </Button>
            )}
          </>
        }
      />
      <WorkflowJourney stage="configure" />
      <WorkflowReadiness definition={definition} saved={!dirty} validation={report} />
      {readOnly && (
        <p className="api-notice">
          {saved.status === 'archived'
            ? 'Archived workflows are read-only.'
            : 'Saved version snapshots are read-only.'}{' '}
          <Link to={`/workflows/${saved.id}/edit`}>Open current definition</Link>
        </p>
      )}
      {error !== null && <Failure error={error} />}
      {notice && (
        <p role="status" className="api-notice">
          {notice}
        </p>
      )}
      <section className="card api-panel api-two-columns">
        <div>
          <label className="label" htmlFor="editor-name">
            Workflow name
          </label>
          <input
            id="editor-name"
            className="input"
            value={name}
            maxLength={200}
            disabled={disabled}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="editor-description">
            Description
          </label>
          <input
            id="editor-description"
            className="input"
            value={description}
            maxLength={5000}
            disabled={disabled}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
      </section>
      {!readOnly && (
        <section className="card api-panel">
          <h2>Propose changes with AI</h2>
          <p className="muted">
            Your request, saved definition, and metadata for existing or selected HTTP connections
            are sent to Groq. Credentials stay on the server. Save any current changes first. Review
            the proposal before applying it to the editor.
          </p>
          <label className="label" htmlFor="edit-prompt">
            Requested changes
          </label>
          <textarea
            id="edit-prompt"
            className="input"
            rows={3}
            maxLength={2000}
            value={editPrompt}
            disabled={!!busy}
            onChange={(event) => {
              setEditPrompt(event.target.value);
              setEditProposal(null);
            }}
          />
          <PlannerConnectionPicker
            value={proposalConnections}
            disabled={!!busy}
            onChange={(ids) => {
              setProposalConnections(ids);
              setEditProposal(null);
            }}
          />
          <Button
            disabled={!!busy || dirty || !saved.current_version_id || !editPrompt.trim()}
            loading={busy === 'proposal'}
            onClick={() => void proposeEdit()}
          >
            Generate edit proposal
          </Button>
          {dirty && (
            <p className="muted">Save or discard your edits before generating a proposal.</p>
          )}
          {editProposal && (
            <div>
              <h3>Review proposal for version {editProposal.base_version_number}</h3>
              <p>{editProposal.message}</p>
              <ConnectionReview connections={editProposal.connections} />
              {editProposal.provider_calls?.map((metadata, index) => (
                <ProviderDetails key={index} metadata={metadata} />
              ))}
              {editProposal.definition && (
                <>
                  <p className="muted">
                    The proposed definition replaces the editor draft when applied. The workflow
                    name and description stay unchanged. Save separately to create a new version.
                  </p>
                  {saved.version &&
                    (() => {
                      const changes = summarizeProposal(
                        saved.version.definition,
                        editProposal.definition,
                      );
                      return (
                        <section aria-label="Summary of proposed changes">
                          <h4>Changes to review</h4>
                          {(['nodes', 'edges'] as const).map((kind) => (
                            <div key={kind}>
                              <strong>{kind === 'nodes' ? 'Nodes' : 'Connections'}</strong>
                              {(['added', 'removed', 'changed'] as const).map((action) => (
                                <p key={action}>
                                  {action}: {changes[kind][action].join(', ') || 'none'}
                                </p>
                              ))}
                            </div>
                          ))}
                          {changes.otherChanged && <p>Other definition properties changed.</p>}
                          <p className="muted">
                            Compare the full definitions below to review the details.
                          </p>
                        </section>
                      );
                    })()}
                  <details>
                    <summary>Current saved definition</summary>
                    <JsonViewer data={saved.version?.definition || {}} />
                  </details>
                  <details open>
                    <summary>Proposed definition</summary>
                    <JsonViewer data={editProposal.definition} />
                  </details>
                  <Button
                    disabled={
                      !!busy || dirty || saved.current_version_id !== editProposal.base_version_id
                    }
                    onClick={() => {
                      if (!editProposal.definition) return;
                      edit(structuredClone(editProposal.definition));
                      setSelected(null);
                      setInvalid({});
                      setEpoch((value) => value + 1);
                      setEditProposal(null);
                      setNotice(
                        'Proposal applied to the unsaved editor draft. Review and save when ready.',
                      );
                    }}
                  >
                    Apply to editor
                  </Button>
                </>
              )}
            </div>
          )}
        </section>
      )}
      <div className="api-section">
        <div className="api-actions">
          <Badge status={saved.status} />
          <small className="muted">
            Drag to arrange · Select to configure · Delete selected edges to disconnect
          </small>
        </div>
        <Button
          disabled={!!busy || invalidJson}
          onClick={() => {
            setSource(!source);
            setSelected(null);
            setInvalid({});
          }}
        >
          <Braces size={15} />
          {source ? 'Visual editor' : 'Definition JSON'}
        </Button>
      </div>
      {source ? (
        <section className="card api-panel">
          {readOnly ? (
            <JsonViewer data={definition} />
          ) : (
            <JsonField
              key={`source:${epoch}`}
              label="Workflow definition (JSON)"
              value={definition}
              parse={parseDefinition}
              disabled={disabled}
              onValue={edit}
              onValidity={validity('source')}
            />
          )}
        </section>
      ) : (
        <div className="card api-editor-grid">
          {palette}
          <Canvas
            definition={definition}
            catalog={catalog}
            selected={selected}
            onSelect={choose}
            onChange={disabled || invalidJson ? undefined : edit}
          />
          {inspector}
        </div>
      )}
      {!source && !readOnly && (
        <section className="card api-panel">
          <h2>Connections</h2>
          <form
            className="api-actions"
            onSubmit={(event) => {
              event.preventDefault();
              if (!edgeSource || !edgeTarget) return;
              edit({
                ...definition,
                edges: [
                  ...definition.edges,
                  {
                    id: `e_${crypto.randomUUID().replaceAll('-', '')}`,
                    source: edgeSource,
                    target: edgeTarget,
                    source_handle: handle,
                  },
                ],
              });
            }}
          >
            <select
              className="input"
              aria-label="Connection source"
              value={edgeSource}
              disabled={disabled || invalidJson}
              onChange={(e) => {
                setEdgeSource(e.target.value);
                setHandle(
                  catalog.find(
                    (item) =>
                      item.type === definition.nodes.find((n) => n.id === e.target.value)?.type,
                  )?.output_handles[0] || 'default',
                );
              }}
            >
              <option value="">Source node</option>
              {definition.nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label || n.id} ({n.id})
                </option>
              ))}
            </select>
            <select
              className="input"
              aria-label="Connection handle"
              value={handle}
              disabled={disabled || invalidJson}
              onChange={(e) => setHandle(e.target.value)}
            >
              {(
                catalog.find(
                  (item) => item.type === definition.nodes.find((n) => n.id === edgeSource)?.type,
                )?.output_handles || ['default']
              ).map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
            <select
              className="input"
              aria-label="Connection target"
              value={edgeTarget}
              disabled={disabled || invalidJson}
              onChange={(e) => setEdgeTarget(e.target.value)}
            >
              <option value="">Target node</option>
              {definition.nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label || n.id} ({n.id})
                </option>
              ))}
            </select>
            <Button type="submit" disabled={disabled || invalidJson || !edgeSource || !edgeTarget}>
              Connect
            </Button>
          </form>
          <div className="api-connections">
            {definition.edges.map((edge) => (
              <div key={edge.id}>
                <code>
                  {edge.source} → {edge.source_handle || 'default'} → {edge.target}
                </code>
                <Button
                  disabled={disabled || invalidJson}
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    edit({ ...definition, edges: definition.edges.filter((e) => e.id !== edge.id) })
                  }
                >
                  Remove connection
                </Button>
              </div>
            ))}
          </div>
        </section>
      )}
      {report && (
        <section className="card api-panel" aria-live="polite">
          <h2>{report.valid ? 'Graph is valid' : 'Validation issues'}</h2>
          <p>
            {report.execution_ready
              ? 'Supported executors are available. Runtime input is checked during execution.'
              : 'This candidate cannot execute yet.'}
          </p>
          {report.issues.map((issue, index) => (
            <div className="api-error" key={index}>
              <strong>{issue.code}</strong>
              <p>{issue.message}</p>
              <code>{issue.path}</code>
            </div>
          ))}
          {report.issues_truncated && (
            <p>Additional issues were omitted. Resolve these and validate again.</p>
          )}
        </section>
      )}
      {!source && (
        <InputFieldsEditor
          key={`${saved.version?.id || 'new'}:${epoch}`}
          definition={definition}
          disabled={disabled}
          onChange={edit}
          onValidity={validity('inputFields')}
        />
      )}
      <section className="card api-panel">
        <div className="api-section">
          <h2>Manual run input</h2>
          <Button
            variant="primary"
            loading={busy === 'run'}
            disabled={disabled || dirty || invalidJson || !saved.current_version_id}
            onClick={() => void run()}
          >
            <Play size={15} />
            Run saved version
          </Button>
        </div>
        {definition.nodes.some((node) =>
          ['groq', 'classify', 'extract', 'agent'].includes(node.type),
        ) && (
          <p className="api-notice">
            Running this workflow sends the selected input and node configuration to Groq. Inputs
            and responses are stored in execution history.
          </p>
        )}
        {definition.nodes.some((node) => node.type === 'agent') && (
          <p className="api-notice">
            Agents may make several Groq requests within their tool limit. Selected HTTP connections
            allow fetched JSON responses to be sent to Groq and stored in execution history. They
            run synchronously, with no automatic retry. Optional pauses retain tool results for
            explicit continuation; unknown in-flight calls cannot be resumed automatically. Review
            their answer and tool results.
          </p>
        )}
        {definition.nodes.some((node) => node.type === 'http') && (
          <p className="api-notice">
            HTTP nodes contact their selected endpoints and store JSON responses. HTTP workflows run
            synchronously and have no automatic retry or recovery.
          </p>
        )}
        <p className="muted">
          Enter your own JSON object and save changes before running. A failed submission is never
          repeated automatically. Trying the same command again in this editor reuses its key; after
          reloading, inspect history before starting another run.
        </p>
        <label className="label" htmlFor="max-attempts">
          Maximum attempts per node
        </label>
        <select
          id="max-attempts"
          className="input"
          value={maxAttempts}
          disabled={disabled}
          onChange={(event) => setMaxAttempts(Number(event.target.value))}
        >
          <option value={1}>1 — no automatic retry</option>
          <option value={2}>2 — retry transient failures once</option>
          <option value={3}>3 — retry transient failures twice</option>
        </select>
        <textarea
          className="input api-code"
          aria-label="Manual run input"
          rows={5}
          spellCheck={false}
          value={input}
          disabled={disabled}
          onChange={(e) => setInput(e.target.value)}
        />
      </section>
      <Modal
        open={blocker.state === 'blocked'}
        onClose={() => {
          if (blocker.state === 'blocked') blocker.reset();
        }}
        title="Leave this workflow?"
        footer={
          <>
            <Button onClick={() => blocker.state === 'blocked' && blocker.reset()}>Stay</Button>
            <Button
              variant="danger"
              onClick={() => blocker.state === 'blocked' && blocker.proceed()}
            >
              Leave without saving
            </Button>
          </>
        }
      >
        <p>
          Your unsaved edits will be discarded. Leaving does not cancel an in-progress server
          request.
        </p>
      </Modal>
    </div>
  );
}
