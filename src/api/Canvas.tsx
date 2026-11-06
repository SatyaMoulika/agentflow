import { memo, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type NodeProps,
} from '@xyflow/react';
import { Bot, Braces, Calculator, Flag, GitBranch, Merge, Play } from 'lucide-react';
import type { CatalogItem, Definition } from './types';
import '@xyflow/react/dist/style.css';
type CanvasNode = Node<
  { label: string; kind: string; handles: string[]; status?: string },
  'apiNode'
>;
const icons: Record<string, typeof Play> = {
  manual: Play,
  transform: Braces,
  condition: GitBranch,
  calculator: Calculator,
  groq: Bot,
  merge: Merge,
  end: Flag,
};
const ApiNode = memo(function ApiNode({ data, selected }: NodeProps<CanvasNode>) {
  const Icon = icons[data.kind] || Braces;
  return (
    <div
      className={`api-node ${selected ? 'selected' : ''} ${data.status ? `status-${data.status}` : ''}`}
    >
      {data.kind !== 'manual' && <Handle type="target" position={Position.Left} />}
      <span className="api-node-icon">
        <Icon size={19} />
      </span>
      <div>
        <small>{data.kind}</small>
        <strong>{data.label}</strong>
        {data.status && <small>{data.status}</small>}
      </div>
      {data.handles.map((handle, index) => (
        <Handle
          key={handle}
          type="source"
          id={handle}
          position={Position.Right}
          style={{ top: `${((index + 1) * 100) / (data.handles.length + 1)}%` }}
        />
      ))}
      {data.handles.length > 1 && <div className="api-handles">{data.handles.join(' / ')}</div>}
    </div>
  );
});
const nodeTypes = { apiNode: ApiNode };
export default function Canvas({
  definition,
  catalog = [],
  selected,
  onSelect,
  onChange,
  statuses = {},
}: {
  definition: Definition;
  catalog?: CatalogItem[];
  selected?: string | null;
  onSelect?: (id: string) => void;
  onChange?: (definition: Definition) => void;
  statuses?: Record<string, string>;
}) {
  const nodes = useMemo<CanvasNode[]>(
    () =>
      definition.nodes
        .filter((n) => typeof n?.id === 'string' && typeof n.type === 'string')
        .map((node, index) => ({
          id: node.id,
          type: 'apiNode',
          position:
            node.position && Number.isFinite(node.position.x) && Number.isFinite(node.position.y)
              ? node.position
              : { x: (index % 4) * 220, y: Math.floor(index / 4) * 120 },
          selected: node.id === selected,
          data: {
            label: node.label || node.id,
            kind: node.type,
            handles:
              catalog.find((item) => item.type === node.type)?.output_handles ||
              (node.type === 'condition'
                ? ['true', 'false']
                : node.type === 'end'
                  ? []
                  : ['default']),
            status: statuses[node.id],
          },
        })),
    [definition, catalog, selected, statuses],
  );
  const edges = useMemo(
    () =>
      definition.edges
        .filter((edge) => typeof edge?.id === 'string')
        .map((edge) => ({
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: edge.source_handle || 'default',
          label:
            edge.label ||
            (edge.source_handle === 'true' || edge.source_handle === 'false'
              ? edge.source_handle
              : undefined),
        })),
    [definition.edges],
  );
  return (
    <div className="api-canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        minZoom={0.25}
        nodesDraggable={!!onChange}
        nodesConnectable={!!onChange}
        elementsSelectable={!!onSelect || !!onChange}
        onNodeClick={(_, node) => onSelect?.(node.id)}
        onNodesChange={
          onChange
            ? (changes) => {
                if (
                  !changes.some((change) => change.type === 'position' || change.type === 'remove')
                )
                  return;
                const next = applyNodeChanges(changes, nodes);
                const ids = new Set(next.map((n) => n.id));
                onChange({
                  ...definition,
                  nodes: definition.nodes
                    .filter((n) => ids.has(n.id))
                    .map((n) => ({
                      ...n,
                      position: next.find((item) => item.id === n.id)?.position || n.position,
                    })),
                  edges: definition.edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
                });
              }
            : undefined
        }
        onEdgesChange={
          onChange
            ? (changes) => {
                const ids = new Set(applyEdgeChanges(changes, edges).map((e) => e.id));
                onChange({ ...definition, edges: definition.edges.filter((e) => ids.has(e.id)) });
              }
            : undefined
        }
        onConnect={
          onChange
            ? (connection) =>
                onChange({
                  ...definition,
                  edges: [
                    ...definition.edges,
                    {
                      id: `e_${crypto.randomUUID().replaceAll('-', '')}`,
                      source: connection.source,
                      target: connection.target,
                      source_handle: connection.sourceHandle || 'default',
                    },
                  ],
                })
            : undefined
        }
        deleteKeyCode={onChange ? ['Backspace', 'Delete'] : null}
      >
        <Background />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
