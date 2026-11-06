import { memo } from 'react';
import { AlertCircle, Check, MoreHorizontal, Trash2 } from 'lucide-react';
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';
import type { WorkflowNode } from '../../types';
import { nodeRegistry } from '../../lib/node-registry';

export type CanvasNodeData = {
  node: WorkflowNode;
  issueCount: number;
  onRemove?: (id: string) => void;
};
export type CanvasNode = Node<CanvasNodeData, 'workflow'>;

function WorkflowNodeCard({ data, selected }: NodeProps<CanvasNode>) {
  const { node, issueCount, onRemove } = data;
  const definition = nodeRegistry[node.type];
  const Icon = definition.icon;
  const operators: Record<string, string> = {
    greater_than: '>',
    less_than: '<',
    equals: '=',
    not_equals: '≠',
    contains: 'contains',
  };
  const summary =
    node.type === 'condition'
      ? `${node.config.variable || 'value'} ${operators[node.config.operator || ''] || node.config.operator || '>'} ${node.config.value || '…'}`
      : node.type === 'approval'
        ? node.config.approver || 'Assign an approver'
        : ['llm', 'classify', 'extract', 'agent'].includes(node.type)
          ? node.config.model || 'Choose a model'
          : node.type === 'http'
            ? `${node.config.method || 'GET'} request`
            : node.config.description || definition.description;
  const trigger = definition.category === 'Trigger';
  return (
    <div
      className={`workflow-node ${selected ? 'workflow-node-selected' : ''}`}
      style={{ '--node-color': definition.color } as React.CSSProperties}
    >
      {!trigger && <Handle type="target" position={Position.Left} />}
      <div className="workflow-node-top">
        <span className="workflow-node-icon">
          <Icon size={18} />
        </span>
        <span className="workflow-node-type">{definition.name}</span>
        {onRemove ? (
          <button
            className="workflow-node-menu nodrag"
            title={`Delete ${node.label}`}
            aria-label={`Delete ${node.label}`}
            onClick={(event) => {
              event.stopPropagation();
              onRemove(node.id);
            }}
          >
            <Trash2 size={13} />
          </button>
        ) : (
          <MoreHorizontal size={13} />
        )}
      </div>
      <strong>{node.label}</strong>
      <p>{summary}</p>
      <div className="workflow-node-bottom">
        <span>{definition.category}</span>
        <span className={issueCount ? 'node-has-issue' : 'node-is-ready'}>
          {issueCount ? (
            <>
              <AlertCircle size={11} /> {issueCount} {issueCount === 1 ? 'issue' : 'issues'}
            </>
          ) : (
            <>
              <Check size={11} /> Configured
            </>
          )}
        </span>
      </div>
      {definition.outputs.map((output, index) => (
        <Handle
          key={output}
          type="source"
          id={output}
          position={Position.Right}
          style={{ top: definition.outputs.length > 1 ? `${38 + index * 35}%` : '50%' }}
        />
      ))}
      {definition.outputs.length > 1 && (
        <div className="workflow-branch-labels">
          {definition.outputs.map((output) => (
            <span key={output}>{output}</span>
          ))}
        </div>
      )}
    </div>
  );
}

export default memo(WorkflowNodeCard);
