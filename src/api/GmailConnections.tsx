import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Button } from '../components/ui';
import { api } from './client';
import { Failure, Pending } from './common';
import { useScope } from './session';
import { captureGmailCallback } from './gmailCallback';
import { IntegrationHeading } from './IntegrationHeading';

// Remove the OAuth code from the URL before rendering and hold it only in memory.
// StrictMode and re-renders share one promise, so a callback is submitted at most once.
let callback =
  typeof window === 'undefined' ? null : captureGmailCallback(window.location, window.history);
let callbackRequest: Promise<unknown> | null = null;

export function GmailCallback() {
  const [status, setStatus] = useState<'pending' | 'done' | 'error'>('pending');
  useEffect(() => {
    let active = true;
    if (!callbackRequest) {
      if (!callback?.code || !callback.state) {
        setStatus('error');
        return;
      }
      callbackRequest = api.gmailComplete(callback.state, callback.code);
      callback = null;
    }
    void callbackRequest.then(
      () => active && setStatus('done'),
      () => active && setStatus('error'),
    );
    return () => {
      active = false;
    };
  }, []);
  return (
    <section className="card api-panel">
      <h2>Gmail connection</h2>
      {status === 'pending' && <Pending />}
      {status === 'done' && (
        <p>Gmail authorization saved. Return to Integrations to select a message.</p>
      )}
      {status === 'error' && (
        <p>Gmail authorization could not be completed. Start again from Integrations.</p>
      )}
      <Link to="/integrations">Back to integrations</Link>
    </section>
  );
}

export default function GmailConnections({
  view = 'all',
}: {
  view?: 'all' | 'connect' | 'manage';
}) {
  const scope = useScope();
  const cache = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [messages, setMessages] = useState<{ connectionId: string; ids: string[] } | null>(null);
  const rows = useQuery({
    queryKey: [...scope, 'gmail-connections'],
    queryFn: ({ signal }) => api.gmailConnections(signal),
    enabled: view !== 'connect',
  });
  async function connect() {
    setPending(true);
    setError(null);
    try {
      const { url } = await api.gmailAuthorize();
      const target = new URL(url);
      if (target.protocol !== 'https:' || target.hostname !== 'accounts.google.com')
        throw new Error('Invalid authorization destination.');
      window.location.assign(url);
    } catch (failure) {
      setError(failure);
      setPending(false);
    }
  }
  async function revoke(id: string) {
    setPending(true);
    setError(null);
    try {
      await api.gmailRevoke(id);
      await cache.invalidateQueries({ queryKey: [...scope, 'gmail-connections'] });
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }
  async function listMessages(id: string) {
    setPending(true);
    setError(null);
    try {
      setMessages({ connectionId: id, ids: await api.gmailMessages(id) });
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      {view !== 'manage' && (
        <section className="card api-panel api-form">
          <IntegrationHeading service="gmail" />
          <p>
            Connect with Google to grant read-only Gmail access. You can manually select a recent
            inbox message for a workflow. Automatic triggers and sending are still being built.
          </p>
          <Button type="button" disabled={pending} onClick={() => void connect()}>
            Connect Gmail
          </Button>
          {error ? <Failure error={error} /> : null}
        </section>
      )}
      {view !== 'connect' && (
        <section className="card api-panel api-form" aria-label="Manage Gmail connections">
          <h3>Gmail connections</h3>
          {view === 'manage' && error ? <Failure error={error} /> : null}
          {rows.isPending ? (
            <Pending />
          ) : rows.isError ? (
            <Failure error={rows.error} />
          ) : (
            <>
              {rows.data.length === 0 && <p>No Gmail connections yet.</p>}
              {rows.data.map((row) => (
                <div className="integration-connection" key={row.id}>
                  <code>{row.id}</code>
                  <span className="muted">{row.revoked_at ? 'Disconnected' : 'Connected'}</span>
                  {!row.revoked_at && (
                    <Button disabled={pending} onClick={() => void listMessages(row.id)}>
                      Show recent message IDs
                    </Button>
                  )}
                  {!row.revoked_at && (
                    <Button disabled={pending} onClick={() => void revoke(row.id)}>
                      Disconnect
                    </Button>
                  )}
                  {messages?.connectionId === row.id && !row.revoked_at && (
                    <div>
                      <p>
                        Enter a message ID in your workflow's manual input as{' '}
                        <code>message_id</code>.
                      </p>
                      {messages.ids.length ? (
                        messages.ids.map((id) => (
                          <p key={id}>
                            <code>{id}</code>
                          </p>
                        ))
                      ) : (
                        <p>No inbox messages returned.</p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </>
          )}
          <p className="muted">
            Disconnect removes the stored credential from AgentFlow. Google account permissions can
            also be reviewed in Google account settings.
          </p>
        </section>
      )}
    </>
  );
}

export function GmailConnectionSelector({
  value,
  disabled,
  onChange,
}: {
  value: string;
  disabled: boolean;
  onChange: (id: string) => void;
}) {
  const scope = useScope();
  const rows = useQuery({
    queryKey: [...scope, 'gmail-connections'],
    queryFn: ({ signal }) => api.gmailConnections(signal),
  });
  return (
    <div className="api-form">
      <label className="label" htmlFor="gmail-connection">
        Gmail connection
      </label>
      <select
        id="gmail-connection"
        className="input"
        value={value}
        disabled={disabled || !rows.data}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Choose a Gmail connection</option>
        {value && !rows.data?.some((row) => row.id === value) && (
          <option value={value}>Saved connection · {value}</option>
        )}
        {rows.data?.map((row) => (
          <option key={row.id} value={row.id} disabled={!!row.revoked_at}>
            {row.id}
            {row.revoked_at ? ' (disconnected)' : ''}
          </option>
        ))}
      </select>
      {rows.isError && <Failure error={rows.error} />}
      <p className="muted">
        The selected email text is stored in run history and can be sent to Groq by later nodes.
      </p>
    </div>
  );
}
