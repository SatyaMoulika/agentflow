import { describe, expect, it } from 'vitest';
import { defaultNode, parseDefinition, parseObject, starterDefinition } from '../src/api/graph';
describe('server graph and input editing', () => {
  it('preserves native scalar types and business key casing', () => {
    expect(parseObject('{"InvoiceID":1,"flag":false,"nested":{"A.B":null}}')).toEqual({
      InvoiceID: 1,
      flag: false,
      nested: { 'A.B': null },
    });
  });
  it.each(['[]', 'null', '"scalar"', '{"number":1e400}', '{bad json}'])(
    'refuses invalid run object %s',
    (value) => {
      expect(() => parseObject(value)).toThrow();
    },
  );
  it('retains graph extensions, typed config, snake_case handles and input mappings', () => {
    const graph = { ...starterDefinition(), metadata: { BusinessKey: 'value' }, extension: 'kept' };
    graph.nodes[0].input_mapping = { 'Literal.Dot': '$.earlier.output.Amount' };
    expect(parseDefinition(JSON.stringify(graph))).toEqual(graph);
  });
  it('allows incomplete node configurations to be saved for later validation', () => {
    const graph = starterDefinition();
    graph.nodes[0].type = 'condition';
    graph.nodes[0].config = {};
    expect(parseDefinition(JSON.stringify(graph))).toEqual(graph);
  });
  it('bounds UTF-8 payload bytes and nesting before requests', () => {
    expect(() => parseObject(JSON.stringify({ data: '界'.repeat(100000) }))).toThrow('256 KiB');
    let value: Record<string, unknown> = {};
    for (let i = 0; i < 34; i++) value = { nested: value };
    expect(() => parseObject(JSON.stringify(value))).toThrow('32 levels');
  });
  it('creates independent explicit starter definitions, without demo business values', () => {
    const first = starterDefinition();
    first.nodes[0].label = 'Changed';
    expect(starterDefinition().nodes[0].label).toBe('Manual start');
    expect(starterDefinition().nodes.map((n) => n.type)).toEqual(['manual', 'end']);
  });
  it('gives the parser and structured AI nodes valid starting configurations', () => {
    expect(defaultNode('json_parser').config).toEqual({ input_field: 'text' });
    expect(defaultNode('classify').config).toEqual({
      input_field: 'text',
      labels: ['positive', 'negative'],
    });
    expect(defaultNode('extract').config).toEqual({
      input_field: 'text',
      fields: ['name', 'email'],
    });
  });
  it('starts calculator agents with an explicit instruction, selected field and bounded tool limit', () => {
    expect(defaultNode('agent').config).toEqual({
      instruction: 'Use the calculator for arithmetic and explain the result.',
      input_field: 'message',
      max_tool_rounds: 3,
      connection_ids: [],
      pause_after_tools: false,
    });
  });
  it('requires an explicit Gmail connection and message ID field', () => {
    expect(defaultNode('gmail_read').config).toEqual({
      connection_id: '',
      message_id_field: 'message_id',
    });
  });
});
