import { describe, expect, it } from 'vitest';
import { starterDefinition } from '../src/api/graph';
import { summarizeProposal } from '../src/api/proposalDiff';

describe('AI edit proposal review', () => {
  it('reports added, removed, and modified nodes and connections', () => {
    const before = starterDefinition();
    const after = structuredClone(before);
    after.nodes[0].label = 'Changed start';
    after.nodes.pop();
    after.nodes.push({ id: 'replacement', type: 'end', config: {} });
    after.edges[0].target = 'replacement';
    expect(summarizeProposal(before, after)).toEqual({
      nodes: { added: ['replacement'], removed: ['finish'], changed: ['start'] },
      edges: { added: [], removed: [], changed: ['start_finish'] },
      otherChanged: false,
    });
  });

  it('ignores object key ordering but detects changes in other definition properties', () => {
    const before = starterDefinition();
    before.nodes[0].config = { z: 1, a: { right: true, left: false } };
    const after = structuredClone(before);
    after.nodes[0].config = { a: { left: false, right: true }, z: 1 };
    after.metadata = { note: 'changed' };
    const result = summarizeProposal(before, after);
    expect(result.nodes.changed).toEqual([]);
    expect(result.otherChanged).toBe(true);
  });
});
