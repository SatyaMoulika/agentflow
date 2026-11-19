import { describe, expect, it } from 'vitest';
import {
  buildInput,
  formValues,
  readInputFields,
  suggestedInputs,
} from '../src/api/workflowInputs';
import type { Definition } from '../src/api/types';

const definition: Definition = {
  schema_version: '1.0',
  nodes: [
    { id: 'start', type: 'manual', config: {} },
    { id: 'agent', type: 'agent', config: { input_field: 'message' } },
    { id: 'end', type: 'end', config: {} },
  ],
  edges: [
    { id: 'a', source: 'start', target: 'agent' },
    { id: 'b', source: 'agent', target: 'end' },
  ],
};

describe('saved workflow input fields', () => {
  it('suggests only input fields read directly from manual input', () => {
    expect(suggestedInputs(definition)).toEqual([
      { name: 'message', label: 'message', type: 'text', required: true },
    ]);
    expect(
      suggestedInputs({
        ...definition,
        nodes: definition.nodes.map((node) =>
          node.id === 'agent'
            ? { ...node, input_mapping: { message: '$.start.output.text' } }
            : node,
        ),
      }),
    ).toEqual([]);
  });

  it('preserves typed defaults and safely rejects malformed definitions', () => {
    const fields = [
      { name: 'amount', label: 'Amount', type: 'number', required: true, default: 2 },
      { name: 'confirmed', label: 'Confirmed', type: 'boolean', required: false, default: false },
    ];
    expect(
      readInputFields({ ...definition, metadata: { agentflow_input_fields: fields } }),
    ).toEqual(fields);
    expect(
      readInputFields({
        ...definition,
        metadata: { agentflow_input_fields: [...fields, fields[0]] },
      }),
    ).toBeNull();
    expect(
      readInputFields({
        ...definition,
        metadata: { agentflow_input_fields: [{ ...fields[0], default: 'bad' }] },
      }),
    ).toBeNull();
  });

  it('produces JSON with exact keys and typed values and checks required input', () => {
    const fields = [
      { name: 'CustomerID', label: 'Customer', type: 'text' as const, required: true },
      { name: 'amount', label: 'Amount', type: 'number' as const, required: true },
      { name: 'enabled', label: 'Enabled', type: 'boolean' as const, required: false },
      { name: '__proto__', label: 'Special key', type: 'text' as const, required: true },
    ];
    const result = buildInput(fields, {
      CustomerID: 'ABC',
      amount: '3.5',
      enabled: 'false',
      ['__proto__']: 'safe',
    });
    expect(JSON.stringify(result)).toBe(
      '{"CustomerID":"ABC","amount":3.5,"enabled":false,"__proto__":"safe"}',
    );
    expect(() =>
      buildInput(fields, { CustomerID: 'ABC', amount: '', ['__proto__']: 'safe' }),
    ).toThrow('Enter Amount');
    expect(() =>
      buildInput(fields, { CustomerID: 'ABC', amount: 'Infinity', ['__proto__']: 'safe' }),
    ).toThrow('valid number');
    expect(formValues(fields, result)).toEqual({
      CustomerID: 'ABC',
      amount: '3.5',
      enabled: 'false',
      ['__proto__']: 'safe',
    });
    expect(() => formValues(fields, { ...result, other: true })).toThrow('additional fields');
    expect(() => formValues(fields, { ...result, amount: '3.5' })).toThrow('different type');
  });
});
