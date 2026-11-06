import { useState } from 'react';
import { ArrowRight, Braces, ChevronDown, Settings2, Trash2, X } from 'lucide-react';
import { nodeRegistry } from '../../lib/node-registry';
import { validateNode } from '../../lib/graph';
import type { NodeConfig, Workflow, WorkflowNode } from '../../types';

interface Props {
  node: WorkflowNode;
  workflow: Workflow;
  onChange: (node: WorkflowNode) => void;
  onClose: () => void;
  onDelete: () => void;
}

export default function NodeConfigForm({ node, workflow, onChange, onClose, onDelete }: Props) {
  const [tab, setTab] = useState<'settings' | 'input' | 'output'>('settings');
  const definition = nodeRegistry[node.type];
  const Icon = definition.icon;
  const issues = validateNode(node);
  const change = (key: keyof NodeConfig, value: string | number) =>
    onChange({ ...node, config: { ...node.config, [key]: value } });
  const field = (
    key: keyof NodeConfig,
    label: string,
    options: {
      area?: boolean;
      placeholder?: string;
      type?: string;
      min?: number;
      max?: number;
      step?: number;
      choices?: string[];
      help?: string;
    } = {},
  ) => {
    const issue = issues.find((item) => item.field === key);
    const id = `config-${node.id}-${key}`;
    const common = {
      id,
      className: `input ${issue ? 'input-invalid' : ''}`,
      value: node.config[key] ?? '',
      'aria-invalid': Boolean(issue),
      onChange: (
        event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
      ) => change(key, options.type === 'number' ? Number(event.target.value) : event.target.value),
    };
    return (
      <div className="field" key={key}>
        <label className="label" htmlFor={id}>
          {label}
        </label>
        {options.choices ? (
          <select {...common}>
            {!node.config[key] && <option value="">Select…</option>}
            {options.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice.replaceAll('_', ' ')}
              </option>
            ))}
          </select>
        ) : options.area ? (
          <textarea {...common} rows={3} placeholder={options.placeholder} />
        ) : (
          <input
            {...common}
            type={options.type || 'text'}
            min={options.min}
            max={options.max}
            step={options.step}
            placeholder={options.placeholder}
          />
        )}
        {issue ? (
          <small className="field-error">{issue.message.replace(`${node.label}: `, '')}</small>
        ) : (
          options.help && <small className="config-help">{options.help}</small>
        )}
      </div>
    );
  };
  const isAi = ['llm', 'classify', 'extract', 'agent'].includes(node.type);
  return (
    <aside className="node-config" aria-label={`${node.label} configuration`}>
      <div className="config-heading">
        <span className="config-type-icon" style={{ color: definition.color }}>
          <Icon size={18} />
        </span>
        <div>
          <strong>Node configuration</strong>
          <span>{definition.name}</span>
        </div>
        <button
          className="editor-icon-button"
          onClick={onClose}
          aria-label="Close node configuration"
        >
          <X size={17} />
        </button>
      </div>
      <div className="config-tabs" role="tablist" aria-label="Node configuration views">
        {(['settings', 'input', 'output'] as const).map((item) => (
          <button
            key={item}
            role="tab"
            aria-selected={tab === item}
            className={tab === item ? 'active' : ''}
            onClick={() => setTab(item)}
          >
            {item === 'settings' ? <Settings2 size={13} /> : <Braces size={13} />}
            {item[0].toUpperCase() + item.slice(1)}
          </button>
        ))}
      </div>
      <div className="config-content">
        {tab === 'settings' && (
          <>
            <div className="field">
              <label className="label" htmlFor="node-label">
                Node name
              </label>
              <input
                id="node-label"
                className="input"
                value={node.label}
                onChange={(event) => onChange({ ...node, label: event.target.value })}
              />
            </div>
            {field('description', 'Description', {
              area: true,
              placeholder: 'What does this step do?',
            })}
            {isAi && (
              <>
                <div className="config-section-label">MODEL & PROMPTS</div>
                {field('model', 'Model', {
                  choices: [
                    ...new Set(
                      [
                        node.config.model || '',
                        'gpt-4o-mini',
                        'gpt-4o',
                        'claude-sonnet-4',
                        'local-model',
                      ].filter(Boolean),
                    ),
                  ],
                })}
                {field('systemPrompt', 'System instructions', {
                  area: true,
                  placeholder: 'You are a precise, helpful assistant…',
                })}
                {field('prompt', 'User prompt', {
                  area: true,
                  placeholder: 'Analyze {{input.document}}…',
                })}
                <div className="config-field-pair">
                  {field('temperature', 'Temperature', {
                    type: 'number',
                    min: 0,
                    max: 2,
                    step: 0.1,
                  })}
                  {field('maxTokens', 'Max. tokens', { type: 'number', min: 1 })}
                </div>
              </>
            )}
            {node.type === 'condition' && (
              <>
                <div className="config-section-label">CONDITION</div>
                {field('variable', 'Input variable', { placeholder: 'amount' })}
                {field('operator', 'Operator', {
                  choices: ['greater_than', 'less_than', 'equals', 'not_equals', 'contains'],
                })}
                {field('value', 'Comparison value', { placeholder: '50000' })}
                <div className="config-branch-box">
                  {['true', 'false'].map((branch) => {
                    const target = workflow.edges.find(
                      (edge) => edge.source === node.id && edge.sourceHandle === branch,
                    )?.target;
                    return (
                      <div key={branch}>
                        <span className={`branch-dot ${branch}`} />
                        {branch === 'true' ? 'True' : 'False'}
                        <ArrowRight size={12} />
                        <span>
                          {workflow.nodes.find((item) => item.id === target)?.label ||
                            'Not connected'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
            {node.type === 'http' && (
              <>
                <div className="config-section-label">REQUEST</div>
                {field('method', 'Method', { choices: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] })}
                {field('url', 'Request URL', { placeholder: 'https://example.com/api' })}
                {field('connection', 'Connection', {
                  choices: ['No authentication (demo)', 'Demo API connection'],
                })}
                {field('headers', 'Headers (JSON)', {
                  area: true,
                  placeholder: '{"Content-Type":"application/json"}',
                  help: 'Use sample values. Do not enter credentials.',
                })}
                {field('body', 'Request body (JSON)', {
                  area: true,
                  placeholder: '{"data":"{{previous.output}}"}',
                })}
              </>
            )}
            {node.type === 'approval' && (
              <>
                <div className="config-section-label">HUMAN REVIEW</div>
                {field('title', 'Approval title', { placeholder: 'Invoice approval required' })}
                {field('approver', 'Assigned approver', { placeholder: 'Finance team' })}
                {field('expiration', 'Expiration behavior', {
                  choices: [
                    ...new Set(
                      [
                        node.config.expiration || '',
                        'Reject after 24 hours',
                        'Keep waiting',
                        'Escalate after 48 hours',
                      ].filter(Boolean),
                    ),
                  ],
                })}
                <div className="config-help">
                  Approved requests continue the simulated workflow. Rejected requests follow the
                  configured rejection branch.
                </div>
              </>
            )}
            {(node.type === 'transform' || node.type === 'calculator') &&
              field('expression', 'Expression', {
                area: true,
                placeholder:
                  node.type === 'calculator'
                    ? '60000 * 1.18'
                    : 'Return a normalized result from {{input}}',
                help:
                  node.type === 'calculator'
                    ? 'The demo supports two numbers and one operator: +, -, *, or /.'
                    : 'Transform expressions are configuration only; simulated output preserves the input.',
              })}
            {node.type === 'manual' && (
              <div className="config-note">
                This trigger starts a simulated execution when you select Run. No external event is
                required.
              </div>
            )}
            {node.type === 'end' && (
              <div className="config-note">
                The final step records the simulated workflow result.
              </div>
            )}
            {node.type === 'merge' && (
              <div className="config-note">
                Connect the branches you want to combine. The demo execution follows a single active
                condition route.
              </div>
            )}
            {node.type === 'parser' &&
              field('input', 'Document input', { placeholder: '{{trigger.document}}' })}
            {!['manual', 'end'].includes(node.type) && (
              <details className="config-advanced">
                <summary>
                  Error handling <ChevronDown size={13} />
                </summary>
                <div className="config-field-pair">
                  {field('timeout', 'Timeout (seconds)', { type: 'number', min: 1 })}
                  {field('retries', 'Retries', { type: 'number', min: 0, max: 10 })}
                </div>
              </details>
            )}
          </>
        )}
        {tab === 'input' && (
          <>
            <div className="config-section-label">INPUT MAPPING</div>
            <p className="config-help">
              Reference the trigger or an upstream step with double braces.
            </p>
            {field('input', 'Input mapping', { area: true, placeholder: '{{previous.output}}' })}
            <div className="config-code-example">
              <span>AVAILABLE UPSTREAM STEPS</span>
              {workflow.edges
                .filter((edge) => edge.target === node.id)
                .map((edge) => (
                  <code
                    key={edge.id}
                  >{`{{${workflow.nodes.find((item) => item.id === edge.source)?.label || edge.source}.output}}`}</code>
                ))}
              {!workflow.edges.some((edge) => edge.target === node.id) && (
                <small>No upstream nodes connected.</small>
              )}
            </div>
          </>
        )}
        {tab === 'output' && (
          <>
            <div className="config-section-label">OUTPUT CONTRACT</div>
            <p className="config-help">
              Describe the expected result with a JSON schema. The prototype validates JSON syntax
              locally.
            </p>
            {field('outputSchema', 'Output schema (JSON)', {
              area: true,
              placeholder: '{"type":"object","properties":{}}',
            })}
            <div className="config-note">
              Execution output, logs, and trace information are available after a simulated run.
            </div>
          </>
        )}
      </div>
      <div className="config-footer">
        <span>
          <span className="live-dot" />
          Changes update the canvas
        </span>
        <button title="Delete node" aria-label="Delete selected node" onClick={onDelete}>
          <Trash2 size={14} />
        </button>
      </div>
    </aside>
  );
}
