import type { Definition } from './types';

type ChangeSet = { added: string[]; removed: string[]; changed: string[] };

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object')
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonical(item)]),
    );
  return value;
}

function changes<T extends { id: string }>(before: T[], after: T[]): ChangeSet {
  const previous = new Map(before.map((item) => [item.id, item]));
  const next = new Map(after.map((item) => [item.id, item]));
  return {
    added: [...next.keys()].filter((id) => !previous.has(id)).sort(),
    removed: [...previous.keys()].filter((id) => !next.has(id)).sort(),
    changed: [...next.keys()]
      .filter(
        (id) =>
          previous.has(id) &&
          JSON.stringify(canonical(previous.get(id))) !== JSON.stringify(canonical(next.get(id))),
      )
      .sort(),
  };
}

export function summarizeProposal(before: Definition, after: Definition) {
  const other = (definition: Definition) =>
    Object.fromEntries(
      Object.entries(definition).filter(([key]) => key !== 'nodes' && key !== 'edges'),
    );
  return {
    nodes: changes(before.nodes, after.nodes),
    edges: changes(before.edges, after.edges),
    otherChanged:
      JSON.stringify(canonical(other(before))) !== JSON.stringify(canonical(other(after))),
  };
}
