import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { JsonViewer } from '../components/ui';

type ModelAttempt = { node_id: string; status: string; output: unknown };
type DefinitionNode = { id: string; type: string };

function sameJson(left: unknown, right: unknown): boolean {
  if (left === right) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return (
      Array.isArray(left) &&
      Array.isArray(right) &&
      left.length === right.length &&
      left.every((value, index) => sameJson(value, right[index]))
    );
  }
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object') return false;
  const a = left as Record<string, unknown>;
  const b = right as Record<string, unknown>;
  const keys = Object.keys(a);
  return (
    keys.length === Object.keys(b).length &&
    keys.every((key) => Object.hasOwn(b, key) && sameJson(a[key], b[key]))
  );
}

export function RunOutput({
  output,
  attempts,
  nodes,
}: {
  output: unknown;
  attempts: ModelAttempt[];
  nodes: DefinitionNode[];
}) {
  if (output === null) return <p className="muted">No successful output stored.</p>;
  const isModelOutput = attempts.some(
    (attempt) =>
      attempt.status === 'succeeded' &&
      nodes.some((node) => node.id === attempt.node_id && ['agent', 'groq'].includes(node.type)) &&
      sameJson(attempt.output, output),
  );
  const content =
    isModelOutput && typeof output === 'object' && output !== null && 'content' in output
      ? output.content
      : null;
  if (typeof content !== 'string' || !content.trim()) {
    const fields =
      typeof output === 'object' && output !== null && !Array.isArray(output)
        ? Object.entries(output)
        : null;
    return (
      <div className="api-output">
        {fields ? (
          fields.length ? (
            <dl className="execution-fields">
              {fields.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>
                    {value !== null && typeof value === 'object' ? (
                      <details>
                        <summary>View structured value</summary>
                        <JsonViewer data={value} />
                      </details>
                    ) : (
                      <span>{value === null ? 'null' : String(value)}</span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="muted">The workflow returned an empty object.</p>
          )
        ) : (
          <p className="execution-value">{String(output)}</p>
        )}
        <details className="api-output-raw">
          <summary>View raw output</summary>
          <JsonViewer data={output} />
        </details>
      </div>
    );
  }
  return (
    <div className="api-output">
      <div className="api-output-label">Generated response</div>
      <div className="api-markdown">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ),
            img: ({ alt }) => <span>{alt || 'Image'}</span>,
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
      <details className="api-output-raw">
        <summary>View raw output</summary>
        <JsonViewer data={output} />
      </details>
    </div>
  );
}
