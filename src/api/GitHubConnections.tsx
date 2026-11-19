import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '../components/ui';
import { api } from './client';
import { Failure } from './common';
import { githubEndpoint } from './github';
import { useScope } from './session';

export default function GitHubConnections() {
  const scope = useScope();
  const cache = useQueryClient();
  const [owner, setOwner] = useState('');
  const [repository, setRepository] = useState('');
  const [resource, setResource] = useState<'issues' | 'pulls'>('issues');
  const [token, setToken] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState('');
  const endpoint = githubEndpoint(owner.trim(), repository.trim(), resource);

  async function create(event: FormEvent) {
    event.preventDefault();
    if (!endpoint) return;
    setPending(true);
    setError(null);
    setNotice('');
    try {
      const row = await api.createConnection({
        name: `GitHub ${owner.trim()}/${repository.trim()} ${resource}`.slice(0, 100),
        endpoint_url: endpoint,
        auth_type: token ? 'bearer' : 'none',
        ...(token ? { secret: token } : {}),
      });
      setToken('');
      setNotice(`Created ${row.name}. Select it on an HTTP GET node in your workflow.`);
      await cache.invalidateQueries({ queryKey: [...scope, 'connections'] });
    } catch (failure) {
      setError(failure);
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="card api-panel api-form">
      <h2>GitHub</h2>
      <p>
        Read a repository’s issues or pull requests in a manually started workflow. Create one
        connection for each list; GitHub credentials are encrypted on the server.
      </p>
      <form className="api-form" onSubmit={(event) => void create(event)}>
        <label className="label" htmlFor="github-owner">
          Repository owner
        </label>
        <input
          id="github-owner"
          className="input"
          required
          value={owner}
          disabled={pending}
          onChange={(event) => setOwner(event.target.value)}
        />
        <label className="label" htmlFor="github-repository">
          Repository name
        </label>
        <input
          id="github-repository"
          className="input"
          required
          value={repository}
          disabled={pending}
          onChange={(event) => setRepository(event.target.value)}
        />
        <label className="label" htmlFor="github-resource">
          Read
        </label>
        <select
          id="github-resource"
          className="input"
          value={resource}
          disabled={pending}
          onChange={(event) => setResource(event.target.value as 'issues' | 'pulls')}
        >
          <option value="issues">Issues</option>
          <option value="pulls">Pull requests</option>
        </select>
        <label className="label" htmlFor="github-token">
          Fine-grained token (optional for public repositories)
        </label>
        <input
          id="github-token"
          className="input"
          type="password"
          autoComplete="new-password"
          value={token}
          disabled={pending}
          onChange={(event) => setToken(event.target.value)}
        />
        <p className="muted">
          For private repositories, grant read-only Issues or Pull requests permission for the
          selected repository. Do not include the word Bearer.
        </p>
        {!endpoint && (owner || repository) && (
          <p>Enter a valid GitHub owner and repository name.</p>
        )}
        <Button type="submit" variant="primary" disabled={pending || !endpoint}>
          {pending ? 'Saving…' : 'Create GitHub connection'}
        </Button>
      </form>
      {error ? <Failure error={error} /> : null}
      {notice && (
        <p className="api-notice" role="status">
          {notice}
        </p>
      )}
      <p className="muted">
        Use Manage & revoke connections below to remove access. GitHub returns its first page; large
        responses can exceed the 64 KiB limit. The issues list can also contain pull requests. No
        automatic triggers or GitHub writes are available.
      </p>
    </section>
  );
}
