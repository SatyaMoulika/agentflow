import { WorkflowJourney, WorkflowReadiness } from './WorkflowJourney';
import { useRef, useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, PageHeader } from '../components/ui';
import { api } from './client';
import { Failure, Pages, Pending } from './common';
import { parseObject } from './graph';
import { useScope } from './session';
import {
  buildInput,
  formValues,
  readInputFields,
  suggestedInputs,
  type InputField,
} from './workflowInputs';
import type { WorkflowDetail } from './types';

export function RunWorkflowList() {
  const scope = useScope();
  const [page, setPage] = useState(1);
  const workflows = useQuery({
    queryKey: [...scope, 'run-workflows', page],
    queryFn: ({ signal }) => api.workflows({ page, page_size: 12 }, signal),
    refetchOnMount: 'always',
  });
  return (
    <div className="api-page">
      <PageHeader
        title="Run a workflow"
        description="Choose a saved workflow to enter its input."
      />
      {workflows.isPending ? (
        <Pending />
      ) : workflows.isError ? (
        <Failure error={workflows.error} retry={() => void workflows.refetch()} />
      ) : (
        <>
          <div className="api-grid">
            {workflows.data.items.map((workflow) => (
              <article className="card api-workflow-card" key={workflow.id}>
                <h2>{workflow.name}</h2>
                <p className="muted">{workflow.description || 'No description'}</p>
                {workflow.current_version_id ? (
                  <Button asChild>
                    <Link to={`/workflows/${workflow.id}/run`}>Enter input</Link>
                  </Button>
                ) : (
                  <p className="muted">Save a definition before running.</p>
                )}
              </article>
            ))}
          </div>
          {!workflows.data.items.length && (
            <p className="muted">No workflows yet. Create one in Workflows.</p>
          )}
          <Pages page={page} size={12} total={workflows.data.total} onChange={setPage} />
        </>
      )}
    </div>
  );
}

export default function RunWorkflow() {
  const { workflowId = '' } = useParams();
  const scope = useScope();
  const workflow = useQuery({
    queryKey: [...scope, 'workflow', workflowId, undefined],
    queryFn: ({ signal }) => api.workflow(workflowId, undefined, signal),
    refetchOnMount: 'always',
  });
  if (workflow.isPending || workflow.isFetching) return <Pending />;
  if (workflow.isError)
    return <Failure error={workflow.error} retry={() => void workflow.refetch()} />;
  return <RunForm key={workflow.data.version?.id || workflowId} workflow={workflow.data} />;
}

export function RunForm({ workflow }: { workflow: WorkflowDetail }) {
  const scope = useScope();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const definition = workflow.version?.definition;
  const savedFields = definition ? readInputFields(definition) : null;
  const hasInvalidMetadata =
    definition?.metadata?.agentflow_input_fields !== undefined && savedFields === null;
  const fields: InputField[] =
    savedFields ?? (definition && !hasInvalidMetadata ? suggestedInputs(definition) : []);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      fields.map((field) => [field.name, field.default === undefined ? '' : String(field.default)]),
    ),
  );
  const [advanced, setAdvanced] = useState(fields.length === 0);
  const [json, setJson] = useState('{}');
  const [attempts, setAttempts] = useState(1);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const pendingRun = useRef<{ signature: string; key: string } | null>(null);
  function switchInputMode(next: boolean) {
    try {
      if (next) {
        setJson(
          JSON.stringify(
            buildInput(
              fields.map((field) => ({ ...field, required: false })),
              values,
            ),
            null,
            2,
          ),
        );
      } else {
        setValues(formValues(fields, parseObject(json)));
      }
      setError(null);
      setAdvanced(next);
    } catch (failure) {
      setError(failure);
    }
  }
  async function run(event: FormEvent) {
    event.preventDefault();
    if (!workflow.version || workflow.status === 'archived' || pending) return;
    setPending(true);
    setError(null);
    try {
      const input = advanced ? parseObject(json) : buildInput(fields, values);
      const signature = JSON.stringify([workflow.version.id, input, attempts]);
      if (pendingRun.current?.signature !== signature)
        pendingRun.current = { signature, key: crypto.randomUUID() };
      const checked = await api.validate(workflow.id, workflow.version.definition);
      if (!checked.execution_ready)
        throw new Error(
          'This workflow is not ready to run. Open the editor and validate it to review the issues.',
        );
      const result = await api.run(
        workflow.id,
        workflow.version.id,
        input,
        pendingRun.current.key,
        attempts,
      );
      pendingRun.current = null;
      void cache.invalidateQueries({ queryKey: [...scope, 'runs'] });
      navigate(`/executions/${result.id}`);
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="api-page">
      <PageHeader
        title={`Run ${workflow.name}`}
        description={`Saved version ${workflow.version?.version_number ?? 'unavailable'}`}
        actions={
          <Button asChild>
            <Link to={`/workflows/${workflow.id}/edit`}>Open editor</Link>
          </Button>
        }
      />
      <WorkflowJourney stage="run" />
      {definition && <WorkflowReadiness definition={definition} />}
      {!workflow.version || workflow.status === 'archived' ? (
        <p className="api-notice">Save an active workflow definition before running it.</p>
      ) : (
        <section className="card api-panel">
          <h2>Workflow input</h2>
          {savedFields === null && fields.length > 0 && (
            <p className="muted">
              Suggested fields are inferred from the first node. Review them in the editor; other
              inputs may be needed.
            </p>
          )}
          {definition?.metadata?.agentflow_input_fields !== undefined && savedFields === null && (
            <p className="api-error">
              The saved input definition is invalid. Use advanced JSON or correct it in the editor.
            </p>
          )}
          {definition?.nodes.some((node) =>
            ['groq', 'classify', 'extract', 'agent'].includes(node.type),
          ) && (
            <p className="api-notice">
              This workflow may send input, node configuration and selected tool results to Groq.
              Inputs and results are saved in execution history.
            </p>
          )}
          <form className="api-form" onSubmit={(event) => void run(event)}>
            {fields.length > 0 && (
              <label>
                <input
                  type="checkbox"
                  checked={advanced}
                  onChange={(event) => switchInputMode(event.target.checked)}
                />{' '}
                Advanced JSON input
              </label>
            )}
            {advanced ? (
              <label className="api-json-field">
                <span className="label">Input JSON</span>
                <textarea
                  className="input api-code"
                  rows={7}
                  value={json}
                  onChange={(event) => setJson(event.target.value)}
                />
              </label>
            ) : (
              fields.map((field, index) => (
                <label key={field.name} className="api-json-field" htmlFor={`run-field-${index}`}>
                  <span className="label">
                    {field.label}
                    {field.required ? ' *' : ''}
                  </span>
                  {field.type === 'boolean' ? (
                    <select
                      id={`run-field-${index}`}
                      className="input"
                      value={values[field.name] ?? ''}
                      required={field.required}
                      onChange={(event) =>
                        setValues({ ...values, [field.name]: event.target.value })
                      }
                    >
                      <option value="">Select</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  ) : (
                    <input
                      id={`run-field-${index}`}
                      className="input"
                      type={field.type === 'number' ? 'number' : 'text'}
                      step={field.type === 'number' ? 'any' : undefined}
                      required={field.required}
                      value={values[field.name] ?? ''}
                      onChange={(event) =>
                        setValues({ ...values, [field.name]: event.target.value })
                      }
                    />
                  )}
                </label>
              ))
            )}
            <label className="api-json-field">
              <span className="label">Maximum attempts per pure node</span>
              <select
                className="input"
                value={attempts}
                onChange={(event) => setAttempts(Number(event.target.value))}
              >
                <option value={1}>1 — no automatic retry</option>
                <option value={2}>2 — retry once</option>
                <option value={3}>3 — retry twice</option>
              </select>
            </label>
            {error !== null && <Failure error={error} />}
            <p className="muted">
              If a request fails, retrying the same input on this page uses the same command key.
              After reloading, check execution history before creating another run.
            </p>
            <Button type="submit" variant="primary" loading={pending} disabled={pending}>
              Run saved version
            </Button>
          </form>
        </section>
      )}
    </div>
  );
}
