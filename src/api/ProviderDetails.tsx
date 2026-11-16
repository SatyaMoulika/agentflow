import type { PlannerConnection, ProviderMetadata } from './types';

export function ProviderDetails({ metadata }: { metadata: ProviderMetadata | null | undefined }) {
  if (!metadata) return null;
  return (
    <div className="api-panel" aria-label="Provider metadata">
      <strong>Groq request</strong>
      <p className="muted">
        Requested {metadata.requested_model} · Response model: {metadata.model ?? 'not reported'} ·{' '}
        {metadata.duration_ms} ms
      </p>
      {metadata.usage ? (
        <p>
          Reported tokens: input {metadata.usage.prompt_tokens ?? 'unknown'} · output{' '}
          {metadata.usage.completion_tokens ?? 'unknown'} · total{' '}
          {metadata.usage.total_tokens ?? 'unknown'}
        </p>
      ) : (
        <p className="muted">Token usage was not reported.</p>
      )}
      {metadata.finish_reason && <p className="muted">Finish reason: {metadata.finish_reason}</p>}
      {metadata.error_code && <p>{metadata.error_code}</p>}
      {metadata.retry_after_seconds && (
        <p>
          Provider requested a wait of {metadata.retry_after_seconds} seconds before another
          request.
        </p>
      )}
    </div>
  );
}

export function ConnectionReview({
  connections,
}: {
  connections: PlannerConnection[] | undefined;
}) {
  if (!connections?.length) return null;
  return (
    <section aria-label="Authorized endpoints for proposal">
      <h3>Authorized endpoints for this proposal</h3>
      <ul>
        {connections.map((row) => (
          <li key={row.id}>
            <strong>{row.name}</strong> · GET {row.endpoint_url}
            <br />
            <code>{row.id}</code>
          </li>
        ))}
      </ul>
      <p className="muted">
        Check HTTP node and agent connection IDs against these endpoints. Agent HTTP results are
        sent to Groq when you run the workflow. Generating a proposal does not call endpoints.
      </p>
    </section>
  );
}
