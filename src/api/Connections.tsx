import { useState, type FormEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '../components/ui';
import { api } from './client';
import { Failure, Pages, Pending } from './common';
import { useScope } from './session';
import type { ConnectionAuth } from './types';

export default function HttpConnections() {
  const scope = useScope();
  const cache = useQueryClient();
  const [page, setPage] = useState(1);
  const [name, setName] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [auth, setAuth] = useState<ConnectionAuth>('none');
  const [secret, setSecret] = useState('');
  const [pending, setPending] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const connections = useQuery({
    queryKey: [...scope, 'connections', page],
    queryFn: ({ signal }) => api.connections(page, signal),
  });
  async function create(event: FormEvent) {
    event.preventDefault();
    setPending('create');
    setError(null);
    setNotice('');
    try {
      const row = await api.createConnection({
        name,
        endpoint_url: endpoint,
        auth_type: auth,
        ...(auth !== 'none' ? { secret } : {}),
      });
      setName('');
      setEndpoint('');
      setSecret('');
      setPage(1);
      setNotice(`Created ${row.name}. Select it on an HTTP GET or Tool Agent node in the editor.`);
      void cache.invalidateQueries({ queryKey: [...scope, 'connections'] });
    } catch (failure) {
      setError(failure);
    } finally {
      setPending('');
    }
  }
  async function revoke(id: string) {
    setPending(id);
    setError(null);
    setNotice('');
    try {
      await api.revokeConnection(id);
      setNotice('Connection revoked and its stored credential removed.');
      void cache.invalidateQueries({ queryKey: [...scope, 'connections'] });
    } catch (failure) {
      setError(failure);
    } finally {
      setPending('');
    }
  }
  return (
    <section className="card api-panel api-form">
      <h2>HTTP connections</h2>
      <p>
        Authorize one fixed public HTTPS endpoint per connection. HTTP GET nodes and selected agent
        tools retrieve JSON when you run a workflow. Workflow input is not sent to endpoints. Agent
        HTTP results are sent to Groq and stored in execution history.
      </p>
      <form className="api-form" onSubmit={(event) => void create(event)}>
        <label className="label" htmlFor="connection-name">
          Name
        </label>
        <input
          id="connection-name"
          className="input"
          required
          maxLength={100}
          value={name}
          disabled={!!pending}
          onChange={(event) => setName(event.target.value)}
        />
        <label className="label" htmlFor="connection-endpoint">
          HTTPS endpoint
        </label>
        <input
          id="connection-endpoint"
          className="input"
          type="url"
          required
          maxLength={1000}
          placeholder="https://api.example.com/status"
          value={endpoint}
          disabled={!!pending}
          onChange={(event) => setEndpoint(event.target.value)}
        />
        <p className="muted">
          Port 443 only. Redirects, private networks, URL credentials and query strings are blocked.
        </p>
        <label className="label" htmlFor="connection-auth">
          Authentication
        </label>
        <select
          id="connection-auth"
          className="input"
          value={auth}
          disabled={!!pending}
          onChange={(event) => {
            setAuth(event.target.value as ConnectionAuth);
            setSecret('');
          }}
        >
          <option value="none">None</option>
          <option value="bearer">Bearer token</option>
          <option value="api_key">X-API-Key</option>
        </select>
        {auth !== 'none' && (
          <>
            <label className="label" htmlFor="connection-secret">
              Credential
            </label>
            <input
              id="connection-secret"
              className="input"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              maxLength={4096}
              value={secret}
              disabled={!!pending}
              onChange={(event) => setSecret(event.target.value)}
            />
            <p className="muted">
              Credentials are encrypted on the server and never returned. Server encryption must be
              configured.
            </p>
          </>
        )}
        <Button type="submit" variant="primary" disabled={!!pending}>
          {pending === 'create' ? 'Saving…' : 'Create connection'}
        </Button>
      </form>
      {error ? <Failure error={error} /> : null}
      {notice && (
        <p className="api-notice" role="status">
          {notice}
        </p>
      )}
      <h3>Your connections</h3>
      {connections.isPending ? (
        <Pending />
      ) : connections.isError ? (
        <Failure error={connections.error} retry={() => void connections.refetch()} />
      ) : (
        <>
          {connections.data.items.length === 0 && <p>No HTTP connections yet.</p>}
          {connections.data.items.map((row) => (
            <div className="card api-panel" key={row.id}>
              <strong>{row.name}</strong>
              <p>{row.endpoint_url}</p>
              <p className="muted">
                {row.auth_type} · {row.revoked_at ? 'Revoked' : 'Active'}
              </p>
              <code>{row.id}</code>
              {!row.revoked_at && (
                <Button variant="danger" disabled={!!pending} onClick={() => void revoke(row.id)}>
                  Revoke connection
                </Button>
              )}
            </div>
          ))}
          <Pages page={page} total={connections.data.total} size={20} onChange={setPage} />
        </>
      )}
      <p className="muted">
        Revocation blocks future calls. A request already in progress may finish.
      </p>
    </section>
  );
}

export function ConnectionSelector({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled: boolean;
  onChange: (id: string) => void;
}) {
  const scope = useScope();
  const [page, setPage] = useState(1);
  const rows = useQuery({
    queryKey: [...scope, 'connections', page],
    queryFn: ({ signal }) => api.connections(page, signal),
  });
  return (
    <div className="api-form">
      <label className="label" htmlFor="http-connection">
        HTTP connection
      </label>
      <select
        id="http-connection"
        className="input"
        value={value}
        disabled={disabled || !rows.data}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Choose an authorized endpoint</option>
        {value && !rows.data?.items.some((row) => row.id === value) && (
          <option value={value}>Saved connection · {value}</option>
        )}
        {rows.data?.items.map((row) => (
          <option key={row.id} value={row.id} disabled={!!row.revoked_at}>
            {row.name}
            {row.revoked_at ? ' (revoked)' : ''}
          </option>
        ))}
      </select>
      {rows.isError && <Failure error={rows.error} retry={() => void rows.refetch()} />}
      {rows.data && <Pages page={page} total={rows.data.total} size={20} onChange={setPage} />}
      <p className="muted">
        Create connections in Integrations. This node makes one GET request and stores the JSON
        response.
      </p>
    </div>
  );
}

interface ConnectionPickerProps {
  value: string[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
}

export function PlannerConnectionPicker(props: ConnectionPickerProps) {
  return <ConnectionPicker {...props} mode="proposal" />;
}

export function AgentConnectionPicker(props: ConnectionPickerProps) {
  return <ConnectionPicker {...props} mode="agent" />;
}

function ConnectionPicker({
  value,
  disabled,
  onChange,
  mode,
}: ConnectionPickerProps & { mode: 'proposal' | 'agent' }) {
  const scope = useScope();
  const [page, setPage] = useState(1);
  const rows = useQuery({
    queryKey: [...scope, 'connections', page],
    queryFn: ({ signal }) => api.connections(page, signal),
  });
  return (
    <details>
      <summary>
        {mode === 'agent'
          ? 'Allow this agent to fetch HTTP connections'
          : 'Allow AI to use HTTP connections'}{' '}
        ({value.length} selected)
      </summary>
      <p className="muted">
        {mode === 'agent'
          ? 'Choose up to 10 connections. When you run this agent, their names, endpoint URLs and fetched JSON responses are sent to Groq and results are stored in execution history. Each endpoint can be fetched once per agent invocation. Credentials stay on the server. HTTP sends no workflow input.'
          : 'Choose up to 10 connections. Their names and endpoint URLs are sent to Groq with your request. Credentials stay on the server. No endpoint is called during generation.'}
      </p>
      {mode === 'agent' && value.length > 0 && (
        <div aria-label="Selected agent connections">
          {value.map((id) => (
            <div key={id} className="api-actions">
              <code>{id}</code>
              <Button
                type="button"
                disabled={disabled}
                onClick={() => onChange(value.filter((item) => item !== id))}
              >
                Remove selection
              </Button>
            </div>
          ))}
          <p className="muted">Missing or revoked selections must be removed before running.</p>
        </div>
      )}
      {rows.isPending && <Pending />}
      {rows.isError && <Failure error={rows.error} retry={() => void rows.refetch()} />}
      {rows.data && (
        <>
          {!rows.data.items.some((row) => !row.revoked_at) && (
            <p>No active connections on this page. Create one in Integrations.</p>
          )}
          {rows.data.items
            .filter((row) => !row.revoked_at)
            .map((row) => (
              <label key={row.id} className="label">
                <input
                  type="checkbox"
                  checked={value.includes(row.id)}
                  disabled={disabled || (!value.includes(row.id) && value.length >= 10)}
                  onChange={(event) =>
                    onChange(
                      event.target.checked
                        ? [...value, row.id]
                        : value.filter((id) => id !== row.id),
                    )
                  }
                />{' '}
                {row.name} · {row.endpoint_url}
              </label>
            ))}
          <Pages page={page} total={rows.data.total} size={20} onChange={setPage} />
        </>
      )}
      {value.length > 0 && (
        <Button type="button" disabled={disabled} onClick={() => onChange([])}>
          Clear connection selection
        </Button>
      )}
    </details>
  );
}
