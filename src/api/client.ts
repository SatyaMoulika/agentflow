import type {
  Catalog,
  Definition,
  JsonObject,
  LoginResult,
  Page,
  RunDetail,
  RunItem,
  User,
  Validation,
  WorkflowDetail,
  WorkflowProposal,
  WorkflowItem,
} from './types';

export class ApiError extends Error {
  constructor(
    message: string,
    public status = 0,
    public code = 'NETWORK_ERROR',
    public requestId?: string,
    public location?: string,
  ) {
    super(message);
  }
}
export type Session = {
  status: 'loading' | 'anonymous' | 'authenticated';
  user: User | null;
  error?: string;
  generation: number;
};
type Lock = <T>(operation: 'refresh' | 'login' | 'logout', work: () => Promise<T>) => Promise<T>;
export const browserAuthLock: Lock = async (operation, work) => {
  if (typeof navigator !== 'undefined' && navigator.locks)
    return navigator.locks.request('agentflow-auth-session', work);
  if (operation === 'refresh')
    return Promise.reject(
      new ApiError('This browser cannot safely restore the session. Please sign in again.'),
    );
  return work();
};
const csrfNames = ['agentflow_csrf', '__Host-agentflow_csrf'] as const;
type CsrfName = (typeof csrfNames)[number];
function readCsrfCookie(
  cookies: string,
  selection: { name?: CsrfName; expected?: string } = {},
): { name: CsrfName; value: string } | null {
  const proofs: { name: CsrfName; value: string }[] = [];
  for (const part of cookies.split(';')) {
    const [name, ...value] = part.trim().split('=');
    if (csrfNames.includes(name as CsrfName) && (!selection.name || selection.name === name)) {
      try {
        const decoded = decodeURIComponent(value.join('='));
        if (/^[A-Za-z0-9_-]{43}$/.test(decoded))
          proofs.push({ name: name as CsrfName, value: decoded });
      } catch {
        /* Invalid cookie proof is never sent. */
      }
    }
  }
  // Same-name cookies with different paths/values cannot be safely disambiguated.
  if (
    proofs.some((proof) =>
      proofs.some((other) => other.name === proof.name && other.value !== proof.value),
    )
  )
    return null;
  if (selection.expected !== undefined)
    return proofs.find((proof) => proof.value === selection.expected) ?? null;
  // On bootstrap, mixed cookie modes require a fresh login rather than guessing.
  return new Set(proofs.map((proof) => proof.value)).size === 1 ? proofs[0] : null;
}
export function csrfCookie(cookies: string): string | null {
  return readCsrfCookie(cookies)?.value ?? null;
}

export class ApiClient {
  private token: string | null = null;
  private csrfName: CsrfName | undefined;
  private state: Session = { status: 'loading', user: null, generation: 0 };
  private listeners = new Set<() => void>();
  private refreshing: Promise<User> | null = null;
  private starting: Promise<void> | null = null;
  private channel: BroadcastChannel | null = null;
  constructor(
    private transport: typeof fetch = (...args) => fetch(...args),
    private cookies = () => (typeof document === 'undefined' ? '' : document.cookie),
    private lock: Lock = browserAuthLock,
  ) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private publish(next: Session) {
    this.state = next;
    this.listeners.forEach((listener) => listener());
  }
  private clear(error?: string) {
    this.token = null;
    this.csrfName = undefined;
    this.publish({ status: 'anonymous', user: null, generation: this.state.generation + 1, error });
  }
  private broadcast(type: 'changed' | 'ended') {
    this.channel?.postMessage({ type });
  }
  initialize() {
    if (this.starting) return this.starting;
    if (typeof BroadcastChannel !== 'undefined') {
      this.channel = new BroadcastChannel('agentflow-session');
      this.channel.onmessage = (event: MessageEvent<unknown>) => {
        const type = (event.data as { type?: string })?.type;
        if (type === 'ended') this.clear();
        else if (type === 'changed') {
          this.clear();
          void this.restore();
        }
      };
    }
    this.starting = this.restore();
    return this.starting;
  }
  private async restore() {
    if (!csrfCookie(this.cookies())) {
      this.clear();
      return;
    }
    this.publish({ ...this.state, status: 'loading', error: undefined });
    try {
      await this.refresh();
    } catch (error) {
      if (this.state.status !== 'anonymous')
        this.clear(
          error instanceof ApiError && error.status === 401
            ? undefined
            : 'Your session could not be restored. Please sign in again.',
        );
    }
  }
  private async raw<T>(path: string, options: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await this.transport(`/api/v1${path}`, {
        ...options,
        credentials: 'same-origin',
        headers: {
          Accept: 'application/json',
          ...(options.body ? { 'Content-Type': 'application/json' } : {}),
          ...options.headers,
        },
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error;
      throw new ApiError('Cannot reach AgentFlow. Check that the API is running and try again.');
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      const id = payload?.request_id;
      const location = response.headers.get('Location');
      throw new ApiError(
        typeof payload?.error?.message === 'string'
          ? payload.error.message
          : 'The API request could not be completed.',
        response.status,
        payload?.error?.code || 'HTTP_ERROR',
        typeof id === 'string' && /^req_[a-f0-9]{32}$/.test(id) ? id : undefined,
        location && /^\/api\/v1\/runs\/[a-f0-9-]{36}$/.test(location) ? location : undefined,
      );
    }
    return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>);
  }
  private proof() {
    const proof = readCsrfCookie(this.cookies(), { name: this.csrfName })?.value;
    if (!proof) throw new ApiError('The session cookie is missing. Please sign in again.', 401);
    return proof;
  }
  private acceptCsrf(expected: string) {
    const proof = readCsrfCookie(this.cookies(), { expected });
    if (!proof)
      throw new ApiError(
        'The browser could not read the matching session cookie. For local HTTP, restart the API with AGENTFLOW_REFRESH_COOKIE_SECURE=false and use localhost:5173. Check blocked cookies in browser DevTools; conflicting AgentFlow cookies may need clearing.',
      );
    this.csrfName = proof.name;
  }
  async refresh(): Promise<User> {
    if (this.refreshing) return this.refreshing;
    const generation = this.state.generation;
    this.refreshing = this.lock('refresh', async () => {
      const result = await this.raw<LoginResult>('/auth/refresh', {
        method: 'POST',
        headers: { 'X-AgentFlow-Client': 'web', 'X-AgentFlow-CSRF': this.proof() },
      });
      if (generation !== this.state.generation)
        throw new ApiError('The session changed. Please sign in again.', 401);
      this.acceptCsrf(result.csrf_token);
      this.token = result.access_token;
      const accountChanged = this.state.user !== null && this.state.user.id !== result.user.id;
      this.publish({
        ...this.state,
        status: 'authenticated',
        user: result.user,
        generation: this.state.generation + (accountChanged ? 1 : 0),
        error: undefined,
      });
      return result.user;
    })
      .catch((error: unknown) => {
        if (generation === this.state.generation) {
          this.clear(
            error instanceof ApiError && error.status === 401
              ? undefined
              : 'Your session expired or could not be restored. Please sign in again.',
          );
          this.broadcast('ended');
        }
        throw error;
      })
      .finally(() => {
        this.refreshing = null;
      });
    return this.refreshing;
  }
  async login(email: string, password: string): Promise<void> {
    await this.lock('login', async () => {
      const result = await this.raw<LoginResult>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
        headers: { 'X-AgentFlow-Client': 'web' },
      });
      this.acceptCsrf(result.csrf_token);
      this.token = result.access_token;
      this.publish({
        status: 'authenticated',
        user: result.user,
        generation: this.state.generation + 1,
      });
      this.broadcast('changed');
    });
  }
  register(email: string, password: string, display_name: string) {
    return this.raw<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name }),
    });
  }
  async logout() {
    await this.lock('logout', async () => {
      const proof = readCsrfCookie(this.cookies(), { name: this.csrfName })?.value;
      await this.raw<void>('/auth/logout', {
        method: 'POST',
        headers: { 'X-AgentFlow-Client': 'web', ...(proof ? { 'X-AgentFlow-CSRF': proof } : {}) },
      });
      this.clear();
      this.broadcast('ended');
    });
  }
  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const generation = this.state.generation;
    const startingToken = this.token;
    const send = () =>
      this.raw<T>(path, {
        ...options,
        headers: {
          ...options.headers,
          ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}),
        },
      });
    let result: T;
    try {
      result = await send();
    } catch (error) {
      if (
        !(error instanceof ApiError) ||
        error.status !== 401 ||
        generation !== this.state.generation
      )
        throw error;
      if (!this.token || this.token === startingToken) await this.refresh();
      if (generation !== this.state.generation)
        throw new ApiError(
          'The account changed while this request was running. Reload this view.',
          0,
          'SESSION_CHANGED',
        );
      result = await send();
    }
    if (generation !== this.state.generation)
      throw new ApiError('The account changed while this request was running. Reload this view.');
    return result;
  }
}
export const client = new ApiClient();
const query = (values: Record<string, string | number | undefined>) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values))
    if (value !== undefined && value !== '') params.set(key, String(value));
  return params.size ? `?${params}` : '';
};
export const api = {
  me: () => client.request<User>('/auth/me'),
  groqCompletion: (prompt: string) =>
    client.request<{ model: string; content: string }>('/ai/completions', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),
  generateWorkflow: (prompt: string) =>
    client.request<WorkflowProposal>('/workflows/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),
  workflows: (values: Record<string, string | number | undefined> = {}, signal?: AbortSignal) =>
    client.request<Page<WorkflowItem>>(`/workflows${query(values)}`, { signal }),
  workflow: (id: string, version?: string, signal?: AbortSignal) =>
    client.request<WorkflowDetail>(
      `/workflows/${encodeURIComponent(id)}${query({ version_id: version })}`,
      { signal },
    ),
  create: (name: string, description: string, definition?: Definition) =>
    client.request<WorkflowDetail>('/workflows', {
      method: 'POST',
      body: JSON.stringify({ name, description, ...(definition ? { definition } : {}) }),
    }),
  save: (
    id: string,
    name: string,
    description: string,
    definition: Definition,
    expected_version: number,
  ) =>
    client.request<WorkflowDetail>(`/workflows/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name, description, definition, expected_version }),
    }),
  archive: (id: string) => client.request<void>(`/workflows/${id}`, { method: 'DELETE' }),
  catalog: (signal?: AbortSignal) => client.request<Catalog>('/node-types', { signal }),
  validate: (id: string, definition: Definition) =>
    client.request<Validation>(`/workflows/${id}/validate`, {
      method: 'POST',
      body: JSON.stringify({ definition }),
    }),
  run: (id: string, version: string, input: JsonObject, key: string, max_attempts = 1) =>
    client.request<RunDetail>(`/workflows/${id}/runs`, {
      method: 'POST',
      headers: { 'Idempotency-Key': key },
      body: JSON.stringify({ workflow_version_id: version, input, max_attempts }),
    }),
  retryRun: (id: string, key: string) =>
    client.request<RunDetail>(`/runs/${encodeURIComponent(id)}/retry`, {
      method: 'POST',
      headers: { 'Idempotency-Key': key },
      body: JSON.stringify({ max_attempts: 1 }),
    }),
  cancelRun: (id: string) =>
    client.request<RunDetail>(`/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  runs: (values: Record<string, string | number | undefined> = {}, signal?: AbortSignal) =>
    client.request<Page<RunItem>>(`/runs${query(values)}`, { signal }),
  runDetail: (id: string, signal?: AbortSignal) =>
    client.request<RunDetail>(`/runs/${encodeURIComponent(id)}`, { signal }),
};
