import { useState, type ReactNode } from 'react';
import type { GraphNode, JsonObject } from './types';
import { Button } from '../components/ui';

/** Basic controls edit only their own keys; switching modes preserves the full config. */
export function NodeConfiguration({
  node,
  disabled,
  onChange,
  renderJson,
}: {
  node: GraphNode;
  disabled: boolean;
  onChange: (value: JsonObject) => void;
  renderJson: (value: JsonObject, onChange: (value: JsonObject) => void) => ReactNode;
}) {
  const supported = ['groq', 'agent', 'json_parser', 'classify', 'extract'].includes(node.type);
  const [advanced, setAdvanced] = useState(!supported);
  const [invalid, setInvalid] = useState(false);
  const update = (key: string, value: string) => onChange({ ...node.config, [key]: value });
  return (
    <div className="api-form">
      {supported && (
        <Button type="button" disabled={disabled || invalid} onClick={() => setAdvanced(!advanced)}>
          {advanced ? 'Use simple fields' : 'Advanced configuration (JSON)'}
        </Button>
      )}
      {advanced ? (
        <div
          onInput={(event) => {
            const target = event.target;
            if (target instanceof HTMLTextAreaElement) {
              try {
                const parsed: unknown = JSON.parse(target.value);
                setInvalid(!parsed || typeof parsed !== 'object' || Array.isArray(parsed));
              } catch {
                setInvalid(true);
              }
            }
          }}
        >
          {renderJson(node.config, onChange)}
        </div>
      ) : (
        <>
          {['groq', 'agent'].includes(node.type) && (
            <label className="label" htmlFor={`instruction-${node.id}`}>
              Instructions
              <textarea
                id={`instruction-${node.id}`}
                aria-label="Instructions"
                className="input"
                rows={5}
                disabled={disabled}
                value={typeof node.config.instruction === 'string' ? node.config.instruction : ''}
                onChange={(e) => update('instruction', e.target.value)}
              />
            </label>
          )}
          <label className="label" htmlFor={`input-field-${node.id}`}>
            Input field name
            <input
              id={`input-field-${node.id}`}
              aria-label="Input field name"
              className="input"
              disabled={disabled}
              value={typeof node.config.input_field === 'string' ? node.config.input_field : ''}
              onChange={(e) => update('input_field', e.target.value)}
            />
          </label>
          <p className="muted">
            Use the exact key from the workflow input or input mapping. Configure labels, extraction
            fields and additional options in advanced JSON.
          </p>
        </>
      )}
    </div>
  );
}
