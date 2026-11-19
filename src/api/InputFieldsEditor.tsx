import { useState } from 'react';
import { Button } from '../components/ui';
import { readInputFields, suggestedInputs, type InputField } from './workflowInputs';
import type { Definition, Json } from './types';

type Draft = {
  name: string;
  label: string;
  type: InputField['type'];
  required: boolean;
  defaultText: string;
};

export function InputFieldsEditor({
  definition,
  disabled,
  onChange,
  onValidity,
}: {
  definition: Definition;
  disabled: boolean;
  onChange: (definition: Definition) => void;
  onValidity: (valid: boolean) => void;
}) {
  const existing = readInputFields(definition);
  const [rows, setRows] = useState<Draft[]>(() =>
    (existing || []).map((field) => ({
      name: field.name,
      label: field.label,
      type: field.type,
      required: field.required,
      defaultText: field.default === undefined ? '' : String(field.default),
    })),
  );
  const [error, setError] = useState('');
  const unknownMetadata =
    existing === null && definition.metadata?.agentflow_input_fields !== undefined;
  function update(next: Draft[]) {
    setRows(next);
    let message = '';
    const seen = new Set<string>();
    const fields = next.map((row) => {
      if (
        !row.name.trim() ||
        !row.label.trim() ||
        row.name.length > 200 ||
        row.label.length > 200 ||
        seen.has(row.name)
      )
        message = 'Each field needs a unique name and label, up to 200 characters.';
      seen.add(row.name);
      let fallback: string | number | boolean | undefined;
      if (row.defaultText !== '') {
        if (row.type === 'number') {
          fallback = Number(row.defaultText);
          if (!Number.isFinite(fallback)) message = 'Number defaults must be valid finite numbers.';
        } else if (row.type === 'boolean') {
          if (!['true', 'false'].includes(row.defaultText))
            message = 'Boolean defaults must be true or false.';
          fallback = row.defaultText === 'true';
        } else fallback = row.defaultText;
      }
      return {
        name: row.name,
        label: row.label,
        type: row.type,
        required: row.required,
        ...(fallback !== undefined ? { default: fallback } : {}),
      };
    });
    setError(message);
    onValidity(!message);
    if (!message)
      onChange({
        ...definition,
        metadata: { ...definition.metadata, agentflow_input_fields: fields as unknown as Json },
      });
  }
  const suggestions = suggestedInputs(definition).filter(
    (item) => !rows.some((row) => row.name === item.name),
  );
  return (
    <section className="card api-panel">
      <h2>Run form fields</h2>
      <p className="muted">
        Define fields for the saved version’s run page. Field names must match the manual input keys
        used by the workflow. These fields guide the form; the API does not enforce them.
      </p>
      {unknownMetadata ? (
        <p className="api-error">
          This definition has input metadata that cannot be edited here. Review it in Definition
          JSON.
        </p>
      ) : (
        <>
          {rows.map((row, index) => (
            <div className="api-input-definition" key={index}>
              <label>
                Input key
                <input
                  className="input"
                  value={row.name}
                  disabled={disabled}
                  onChange={(e) =>
                    update(
                      rows.map((item, i) =>
                        i === index ? { ...item, name: e.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <label>
                Label
                <input
                  className="input"
                  value={row.label}
                  disabled={disabled}
                  onChange={(e) =>
                    update(
                      rows.map((item, i) =>
                        i === index ? { ...item, label: e.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <label>
                Type
                <select
                  className="input"
                  value={row.type}
                  disabled={disabled}
                  onChange={(e) =>
                    update(
                      rows.map((item, i) =>
                        i === index
                          ? { ...item, type: e.target.value as Draft['type'], defaultText: '' }
                          : item,
                      ),
                    )
                  }
                >
                  <option value="text">Text</option>
                  <option value="number">Number</option>
                  <option value="boolean">Yes / no</option>
                </select>
              </label>
              <label>
                Default (optional)
                <input
                  className="input"
                  value={row.defaultText}
                  disabled={disabled}
                  placeholder={row.type === 'boolean' ? 'true or false' : ''}
                  onChange={(e) =>
                    update(
                      rows.map((item, i) =>
                        i === index ? { ...item, defaultText: e.target.value } : item,
                      ),
                    )
                  }
                />
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={row.required}
                  disabled={disabled}
                  onChange={(e) =>
                    update(
                      rows.map((item, i) =>
                        i === index ? { ...item, required: e.target.checked } : item,
                      ),
                    )
                  }
                />{' '}
                Required
              </label>
              <Button
                type="button"
                disabled={disabled}
                onClick={() => update(rows.filter((_, i) => i !== index))}
              >
                Remove field
              </Button>
            </div>
          ))}
          {error && (
            <p role="alert" className="api-inline-error">
              {error}
            </p>
          )}
          <div className="api-actions">
            <Button
              type="button"
              disabled={disabled || rows.length >= 30}
              onClick={() =>
                update([
                  ...rows,
                  { name: '', label: '', type: 'text', required: true, defaultText: '' },
                ])
              }
            >
              Add field
            </Button>
            {suggestions.length > 0 && (
              <Button
                type="button"
                disabled={disabled || rows.length + suggestions.length > 30}
                onClick={() =>
                  update([...rows, ...suggestions.map((item) => ({ ...item, defaultText: '' }))])
                }
              >
                Add suggested fields
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
