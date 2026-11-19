import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '../components/ui';
import { api } from './client';
import { useScope } from './session';
import { Failure, Pages } from './common';
import { isGitHubReadEndpoint, starterWorkflow, type StarterKind } from './journey';
export function StarterChooser({ onBusyChange }: { onBusyChange?: (busy: boolean) => void }) {
  const [kind, setKind] = useState<StarterKind>('calculator');
  const [page, setPage] = useState(1);
  const [connection, setConnection] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const scope = useScope();
  const cache = useQueryClient();
  const navigate = useNavigate();
  const connections = useQuery({
    queryKey: [...scope, 'connections', page],
    queryFn: ({ signal }) => api.connections(page, signal),
    enabled: kind === 'github',
  });
  const candidates =
    connections.data?.items.filter((c) => !c.revoked_at && isGitHubReadEndpoint(c.endpoint_url)) ||
    [];
  async function create() {
    if (busy) return;
    setBusy(true);
    onBusyChange?.(true);
    setError(null);
    try {
      const current = kind === 'github' ? await api.connections(page) : null;
      if (
        kind === 'github' &&
        !current?.items.some(
          (c) => c.id === connection && !c.revoked_at && isGitHubReadEndpoint(c.endpoint_url),
        )
      )
        throw new Error('Refresh and select an active GitHub connection on this page.');
      const draft = starterWorkflow(kind, connection);
      const result = await api.create(draft.name, draft.description, draft.definition);
      await cache.invalidateQueries({ queryKey: [...scope, 'workflows'] });
      navigate(`/workflows/${result.id}/edit`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  }
  return (
    <section className="card api-panel api-form" aria-label="Guided starters">
      <h2>Start with a working structure</h2>
      <p>
        Choose a draft to review and configure. Nothing runs and no model is called when you create
        it.
      </p>
      <div className="workflow-starters" role="group" aria-label="Starter workflow">
        <Button
          disabled={busy}
          variant={kind === 'calculator' ? 'primary' : 'secondary'}
          aria-pressed={kind === 'calculator'}
          onClick={() => {
            setKind('calculator');
            setError(null);
          }}
        >
          First calculation · no connection
        </Button>
        <Button
          disabled={busy}
          variant={kind === 'github' ? 'primary' : 'secondary'}
          aria-pressed={kind === 'github'}
          onClick={() => {
            setKind('github');
            setError(null);
          }}
        >
          GitHub briefing · read only
        </Button>
      </div>
      {kind === 'github' ? (
        <>
          <p>
            A Tool Agent reads one selected repository issues/PR endpoint and prepares a briefing.
            Running it sends the request and fetched data to Groq; credentials stay server-side.
            Collection results may be partial. There is no posting, scheduling or automatic trigger.
          </p>
          <Link to="/integrations">Set up a GitHub connection in Integrations ↗</Link>
          <label htmlFor="starter-github">GitHub repository connection</label>
          <select
            id="starter-github"
            className="input"
            disabled={busy || connections.isFetching}
            value={connection}
            onChange={(e) => setConnection(e.target.value)}
          >
            <option value="">Choose an active repository connection</option>
            {candidates.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          {connections.isPending && <p role="status">Loading connections…</p>}
          {connections.isError && (
            <Failure error={connections.error} retry={() => void connections.refetch()} />
          )}
          {connections.data && (
            <>
              <Pages
                page={page}
                total={connections.data.total}
                size={20}
                onChange={(next) => {
                  setPage(next);
                  setConnection('');
                }}
              />
              {!candidates.length && (
                <p className="muted">
                  No eligible connection on this page. Add one in Integrations or check another
                  page.
                </p>
              )}
            </>
          )}
          <Button
            onClick={() => {
              setConnection('');
              void connections.refetch();
            }}
            disabled={busy}
          >
            Refresh connections
          </Button>
          <p className="muted">
            Groq availability is checked when you run; selecting a connection does not prove the
            provider is configured.
          </p>
        </>
      ) : (
        <p>
          Manual input → multiply by two → output. Enter 12 on the Run page to expect a result of
          24. This is an example to run yourself, not a pre-existing execution.
        </p>
      )}
      {error !== null && <Failure error={error} />}
      <Button
        variant="primary"
        disabled={
          busy ||
          (kind === 'github' && (!connection || connections.isFetching || connections.isError))
        }
        loading={busy}
        onClick={() => void create()}
      >
        Create starter draft
      </Button>
    </section>
  );
}
