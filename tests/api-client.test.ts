import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiClient, ApiError, browserAuthLock, csrfCookie } from '../src/api/client';
const A = 'A'.repeat(43),
  B = 'B'.repeat(43),
  C = 'C'.repeat(43);
const user = { id: 'owner-a', email: 'owner@example.com', display_name: 'Owner', is_active: true };
const response = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
const login = (token = 'access-a', csrf = A, profile = user) => ({
  access_token: token,
  csrf_token: csrf,
  user: profile,
  expires_in: 900,
});
const unlocked = async <T>(_operation: string, work: () => Promise<T>) => work();
const unauthorized = () =>
  response({ error: { code: 'UNAUTHENTICATED', message: 'Authentication is required.' } }, 401);
beforeEach(() => {
  vi.stubGlobal('BroadcastChannel', undefined);
});
afterEach(() => vi.unstubAllGlobals());

describe('real HTTP client session and command behavior', () => {
  it('preserves provider wait guidance without replaying requests or ending the session', async () => {
    const transport = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(response(login()))
      .mockResolvedValueOnce(response({ error: { code: 'PROVIDER_RATE_LIMITED', message: 'Wait before trying again.' } }, 429, { 'Retry-After': '2' }));
    const api = new ApiClient(transport, () => `agentflow_csrf=${A}`, unlocked);
    await api.login(user.email, 'password');
    await expect(api.request('/ai/completions', { method: 'POST', body: JSON.stringify({ prompt: 'Synthetic' }) }))
      .rejects.toMatchObject({ code: 'PROVIDER_RATE_LIMITED', retryAfterSeconds: 2 });
    expect(transport).toHaveBeenCalledTimes(2);
    expect(api.snapshot().status).toBe('authenticated');
  });
  it('starts anonymous without reading a browser-local authentication flag', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('Auth must not read storage');
      },
    });
    const transport = vi.fn<typeof fetch>();
    const api = new ApiClient(transport, () => '', unlocked);
    await api.initialize();
    expect(api.snapshot().status).toBe('anonymous');
    expect(transport).not.toHaveBeenCalled();
  });
  it('preserves credentials exactly and keeps access tokens in memory', async () => {
    const transport = vi.fn<typeof fetch>().mockResolvedValue(response(login()));
    const api = new ApiClient(transport, () => `agentflow_csrf=${A}`, unlocked);
    await api.login(' Owner@Example.COM ', '  private-password  ');
    const [path, init] = transport.mock.calls[0];
    expect(path).toBe('/api/v1/auth/login');
    expect(JSON.parse(init!.body as string)).toEqual({
      email: ' Owner@Example.COM ',
      password: '  private-password  ',
    });
    expect(init?.credentials).toBe('same-origin');
    expect(init?.headers).not.toHaveProperty('Authorization');
    expect(api.snapshot()).toMatchObject({ status: 'authenticated', user });
    expect(JSON.stringify(api.snapshot())).not.toContain('access-a');
  });
  it('refuses a successful login when matching session cookies were blocked', async () => {
    const api = new ApiClient(
      vi.fn<typeof fetch>().mockResolvedValue(response(login())),
      () => `agentflow_csrf=${B}`,
      unlocked,
    );
    await expect(api.login(user.email, 'password')).rejects.toThrow('matching session cookie');
    expect(api.snapshot().user).toBeNull();
  });
  it.each([
    ['agentflow_csrf', '__Host-agentflow_csrf', true],
    ['agentflow_csrf', '__Host-agentflow_csrf', false],
    ['__Host-agentflow_csrf', 'agentflow_csrf', true],
    ['__Host-agentflow_csrf', 'agentflow_csrf', false],
  ])(
    'uses the accepted %s cookie despite stale %s cookies (stale first: %s)',
    async (active, stale, staleFirst) => {
      let proof = A;
      const transport = vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
        if (path === '/api/v1/auth/login') return response(login());
        expect(init?.headers).toMatchObject({ 'X-AgentFlow-CSRF': proof });
        if (path === '/api/v1/auth/logout') return response(null, 204);
        expect(path).toBe('/api/v1/auth/refresh');
        proof = B;
        return response(login('rotated', B));
      });
      const api = new ApiClient(
        transport,
        () => {
          const entries = [`${active}=${proof}`, `${stale}=${C}`];
          return (staleFirst ? entries.reverse() : entries).join('; ');
        },
        unlocked,
      );
      await api.login(user.email, 'password');
      await api.refresh();
      expect(api.snapshot().status).toBe('authenticated');
      await api.logout();
      expect(api.snapshot().status).toBe('anonymous');
      expect(transport).toHaveBeenCalledTimes(3);
    },
  );
  it('does not rotate a guessed cookie family when bootstrap has conflicting modes', async () => {
    const transport = vi.fn<typeof fetch>();
    const api = new ApiClient(
      transport,
      () => `agentflow_csrf=${A}; __Host-agentflow_csrf=${B}`,
      unlocked,
    );
    await api.initialize();
    expect(api.snapshot().status).toBe('anonymous');
    expect(transport).not.toHaveBeenCalled();
  });
  it('rejects conflicting same-name cookies even when one matches the response', async () => {
    const api = new ApiClient(
      vi.fn<typeof fetch>().mockResolvedValue(response(login())),
      () => `agentflow_csrf=${A}; agentflow_csrf=${B}`,
      unlocked,
    );
    await expect(api.login(user.email, 'password')).rejects.toThrow('matching session cookie');
    expect(api.snapshot().user).toBeNull();
  });
  it('restores a fresh client using the cookie protocol and deduplicates initialization', async () => {
    let proof = A;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (_path, init) => {
      expect(init?.headers).toMatchObject({ 'X-AgentFlow-Client': 'web', 'X-AgentFlow-CSRF': A });
      proof = B;
      return response(login('restored', B));
    });
    const api = new ApiClient(transport, () => `agentflow_csrf=${proof}`, unlocked);
    await Promise.all([api.initialize(), api.initialize()]);
    expect(transport).toHaveBeenCalledTimes(1);
    expect(api.snapshot().user).toEqual(user);
  });
  it('serializes concurrent 401 refreshes and retries each protected request once', async () => {
    let proof = A;
    let rotations = 0;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
      if (path === '/api/v1/auth/login') return response(login());
      if (path === '/api/v1/auth/refresh') {
        rotations++;
        await Promise.resolve();
        proof = B;
        return response(login('access-b', B));
      }
      return (init?.headers as Record<string, string>).Authorization === 'Bearer access-b'
        ? response({ ok: true })
        : unauthorized();
    });
    const api = new ApiClient(transport, () => `agentflow_csrf=${proof}`, unlocked);
    await api.login(user.email, 'password');
    expect(await Promise.all([api.request('/workflows'), api.request('/runs')])).toEqual([
      { ok: true },
      { ok: true },
    ]);
    expect(rotations).toBe(1);
  });
  it('opens an authenticated event stream and preserves the replay cursor', async () => {
    const stream = new Response('id: 7\nevent: execution\ndata: {}\n\n', {
      headers: { 'Content-Type': 'text/event-stream' },
    });
    const transport = vi.fn<typeof fetch>().mockImplementation(async (path, init) => {
      if (path === '/api/v1/auth/login') return response(login());
      expect(path).toBe('/api/v1/runs/example/events/stream');
      expect(init?.headers).toMatchObject({
        Accept: 'text/event-stream', Authorization: 'Bearer access-a', 'Last-Event-ID': '6',
      });
      return stream;
    });
    const api = new ApiClient(transport, () => `agentflow_csrf=${A}`, unlocked);
    await api.login(user.email, 'password');
    const result = await api.request<Response>(
      '/runs/example/events/stream', { headers: { 'Last-Event-ID': '6' } }, true,
    );
    expect(result).toBe(stream);
    expect(await result.text()).toContain('id: 7');
  });
  it('reads the current CSRF cookie only after the cross-tab lock is granted', async () => {
    let proof = A;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (_path, init) => {
      expect(init?.headers).toMatchObject({ 'X-AgentFlow-CSRF': B });
      proof = C;
      return response(login('new', C));
    });
    const api = new ApiClient(
      transport,
      () => `agentflow_csrf=${proof}`,
      async (_operation, work) => {
        proof = B;
        return work();
      },
    );
    await api.refresh();
    expect(api.snapshot().status).toBe('authenticated');
  });
  it('never retries an ambiguous network failure from a run POST', async () => {
    const transport = vi.fn<typeof fetch>().mockRejectedValue(new Error('private-driver-detail'));
    const api = new ApiClient(transport, () => '', unlocked);
    await expect(api.request('/workflows/id/runs', { method: 'POST', body: '{}' })).rejects.toThrow(
      'Cannot reach AgentFlow',
    );
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it('keeps retained-run Location and request ID on 503 without repeating the mutation', async () => {
    const id = '12345678-1234-1234-1234-123456789abc';
    const transport = vi.fn<typeof fetch>().mockResolvedValue(
      response(
        {
          error: {
            code: 'SERVICE_UNAVAILABLE',
            message: 'The service is temporarily unavailable.',
          },
          request_id: `req_${'a'.repeat(32)}`,
        },
        503,
        { Location: `/api/v1/runs/${id}` },
      ),
    );
    const api = new ApiClient(transport, () => '', unlocked);
    const failure = await api
      .request('/workflows/id/runs', { method: 'POST', body: '{}' })
      .catch((error) => error);
    expect(failure).toBeInstanceOf(ApiError);
    if (!(failure instanceof ApiError)) throw new Error('Expected an API failure');
    expect(failure.location).toBe(`/api/v1/runs/${id}`);
    expect(failure.requestId).toMatch(/^req_/);
    expect(transport).toHaveBeenCalledTimes(1);
  });
  it('discards malformed request identifiers and external redirect locations', async () => {
    const api = new ApiClient(
      vi.fn<typeof fetch>().mockResolvedValue(
        response({ error: { message: 'Unavailable' }, request_id: 'private-id' }, 503, {
          Location: 'https://other.example/run',
        }),
      ),
      () => '',
      unlocked,
    );
    const failure = await api.request('/runs').catch((error) => error);
    if (!(failure instanceof ApiError)) throw new Error('Expected an API failure');
    expect(failure.requestId).toBeUndefined();
    expect(failure.location).toBeUndefined();
  });
  it('retains authenticated state when server logout fails, then clears after 204', async () => {
    let fail = true;
    const transport = vi
      .fn<typeof fetch>()
      .mockImplementation(async (path) =>
        path === '/api/v1/auth/login'
          ? response(login())
          : fail
            ? response({ error: { message: 'Unavailable' } }, 503)
            : response(null, 204),
      );
    const api = new ApiClient(transport, () => `agentflow_csrf=${A}`, unlocked);
    await api.login(user.email, 'password');
    await expect(api.logout()).rejects.toBeInstanceOf(ApiError);
    expect(api.snapshot().status).toBe('authenticated');
    fail = false;
    await api.logout();
    expect(api.snapshot().status).toBe('anonymous');
  });
  it('rejects an old account response that finishes after a new login', async () => {
    let release!: (response: Response) => void;
    let count = 0;
    const transport = vi.fn<typeof fetch>().mockImplementation(async (path) =>
      path === '/api/v1/auth/login'
        ? response(login(`access-${++count}`, A, count === 1 ? user : { ...user, id: 'owner-b' }))
        : new Promise<Response>((resolve) => {
            release = resolve;
          }),
    );
    const api = new ApiClient(transport, () => `agentflow_csrf=${A}`, unlocked);
    await api.login(user.email, 'password');
    const pending = api.request('/workflows');
    await api.login('second@example.com', 'password');
    release(response({ private: 'old account data' }));
    await expect(pending).rejects.toThrow('account changed');
    expect(api.snapshot().user?.id).toBe('owner-b');
  });
  it('clears local identity on invalid refresh without retrying the consumed credential', async () => {
    const transport = vi
      .fn<typeof fetch>()
      .mockImplementation(async (path) =>
        path === '/api/v1/auth/login' ? response(login()) : unauthorized(),
      );
    const api = new ApiClient(transport, () => `agentflow_csrf=${A}`, unlocked);
    await api.login(user.email, 'password');
    await expect(api.request('/runs')).rejects.toBeInstanceOf(ApiError);
    expect(api.snapshot().status).toBe('anonymous');
    expect(transport.mock.calls.filter(([path]) => path === '/api/v1/auth/refresh')).toHaveLength(
      1,
    );
  });
  it('does not attempt automatic refresh without Web Locks support', async () => {
    vi.stubGlobal('navigator', {});
    const operation = vi.fn(async () => user);
    await expect(browserAuthLock('refresh', operation)).rejects.toThrow('sign in again');
    expect(operation).not.toHaveBeenCalled();
  });
  it.each([
    ['agentflow_csrf', A],
    ['__Host-agentflow_csrf', B],
  ])('reads only readable proof cookie %s', (name, proof) => {
    expect(csrfCookie(`agentflow_refresh=private; ${name}=${proof}`)).toBe(proof);
  });
  it.each(['', 'agentflow_refresh=private', 'agentflow_csrf=%zz', 'agentflow_csrf=too-short'])(
    'rejects unusable cookie proof %s',
    (cookie) => {
      expect(csrfCookie(cookie)).toBeNull();
    },
  );
});

it('does not replay an expired mutation into another account after refresh', async () => {
  let proof = A;
  let mutations = 0;
  const transport = vi.fn<typeof fetch>().mockImplementation(async (path) => {
    if (path === '/api/v1/auth/login') return response(login());
    if (path === '/api/v1/auth/refresh') {
      proof = B;
      return response(login('access-b', B, { ...user, id: 'other-owner' }));
    }
    mutations++;
    return unauthorized();
  });
  const api = new ApiClient(transport, () => `agentflow_csrf=${proof}`, unlocked);
  await api.login(user.email, 'password');
  await expect(api.request('/workflows', { method: 'POST', body: '{}' })).rejects.toThrow(
    'account changed',
  );
  expect(mutations).toBe(1);
  expect(api.snapshot().user?.id).toBe('other-owner');
});
