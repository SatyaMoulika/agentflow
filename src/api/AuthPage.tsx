import { useState, type FormEvent } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Workflow, ArrowRight, ShieldCheck } from 'lucide-react';
import { Button } from '../components/ui';
import { client } from './client';
import { Failure, Pending } from './common';
import { useSession } from './session';
import { FlowIllustration } from './FlowIllustration';
export default function AuthPage({ registration = false }: { registration?: boolean }) {
  const session = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [created, setCreated] = useState(false);
  if (session.status === 'loading') return <Pending />;
  const from = (location.state as { from?: string } | null)?.from;
  const target =
    from?.startsWith('/') && !from.startsWith('//') && !from.startsWith('/login')
      ? from
      : '/dashboard';
  if (session.status === 'authenticated') return <Navigate to={target} replace />;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const length = [...password].length;
      if (length > 128 || (registration && (length < 8 || !password.trim())))
        throw new Error(
          registration
            ? 'Use 8–128 characters with at least one non-whitespace character.'
            : 'Passwords must be at most 128 characters.',
        );
      if (registration) {
        await client.register(email, password, name);
        setPassword('');
        setCreated(true);
      } else {
        await client.login(email, password);
        setPassword('');
        navigate(target, { replace: true });
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="api-auth">
      <section className="api-auth-story">
        <Link className="brand" to="/login">
          <span className="brand-mark">
            <Workflow size={24} color="white" />
          </span>
          <span className="brand-name">agentflow.</span>
        </Link>
        <span className="api-kicker">YOUR AUTOMATION STUDIO</span>
        <h1>
          Build a workflow.
          <br />
          <span>See what actually happens.</span>
        </h1>
        <p>
          Save your definitions, follow each selected branch, and inspect persisted inputs and
          results.
        </p>
        <FlowIllustration />
        <div className="api-auth-path">
          <span>Design</span>
          <ArrowRight />
          <span>Validate</span>
          <ArrowRight />
          <span>Execute</span>
        </div>
      </section>
      <section className="api-auth-form">
        <ShieldCheck size={30} className="api-accent" />
        <h2>{registration ? 'Create your account' : 'Welcome back'}</h2>
        <p className="muted">
          {registration
            ? 'Create an account to start building workflows.'
            : 'Sign in to your saved workflows and execution history.'}
        </p>
        {session.error && (
          <p role="status" className="api-error">
            {session.error}
          </p>
        )}
        {created ? (
          <div className="api-panel">
            <h3>Account created</h3>
            <p>Your account is saved. Sign in to start building workflows.</p>
            <Button asChild variant="primary">
              <Link to="/login">Go to sign in</Link>
            </Button>
          </div>
        ) : (
          <form onSubmit={submit}>
            <label className="label" htmlFor="auth-email">
              Email
            </label>
            <input
              id="auth-email"
              className="input"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy}
            />
            {registration && (
              <>
                <label className="label" htmlFor="auth-name">
                  Display name
                </label>
                <input
                  id="auth-name"
                  className="input"
                  autoComplete="name"
                  required
                  maxLength={100}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={busy}
                />
              </>
            )}
            <label className="label" htmlFor="auth-password">
              Password
            </label>
            <input
              id="auth-password"
              className="input"
              type="password"
              autoComplete={registration ? 'new-password' : 'current-password'}
              required
              minLength={registration ? 8 : 1}
              maxLength={256}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy}
            />
            {registration && (
              <p className="muted">Use 8–128 characters. Spaces and case are preserved.</p>
            )}
            {error !== null && <Failure error={error} />}
            <Button type="submit" variant="primary" loading={busy} disabled={busy}>
              {registration ? 'Create account' : 'Sign in'} <ArrowRight size={16} />
            </Button>
          </form>
        )}
        <p className="api-auth-switch">
          {registration ? 'Already registered?' : 'New to AgentFlow?'}{' '}
          <Link to={registration ? '/login' : '/register'} state={location.state}>
            {registration ? 'Sign in' : 'Create an account'}
          </Link>
        </p>
      </section>
    </main>
  );
}
