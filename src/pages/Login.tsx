import { useEffect, useRef, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import {
  ArrowRight,
  Check,
  CheckCircle2,
  FileText,
  GitBranch,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
  Workflow,
  Zap,
} from 'lucide-react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useAppStore } from '../stores/useAppStore';
import { Button } from '../components/ui';
import './management.css';

const schema = z.object({
  email: z.email('Enter a valid email address.'),
  password: z.string().min(1, 'Enter any demo password to continue.'),
});
type LoginValues = z.infer<typeof schema>;
export default function Login() {
  const { authenticated, settings, signIn } = useAppStore();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [help, setHelp] = useState('');
  const [rememberEmail, setRememberEmail] = useState(true);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      email: localStorage.getItem('agentflow-demo-email') || settings.email,
      password: '',
    },
  });
  if (authenticated) return <Navigate to="/dashboard" replace />;
  const submit = ({ email }: LoginValues) => {
    if (rememberEmail) localStorage.setItem('agentflow-demo-email', email);
    else localStorage.removeItem('agentflow-demo-email');
    setLoading(true);
    timer.current = setTimeout(() => {
      signIn(
        email
          .split('@')[0]
          .replace(/[._-]/g, ' ')
          .replace(/\b\w/g, (character) => character.toUpperCase()),
        email,
      );
      navigate('/dashboard', { replace: true });
    }, 450);
  };
  return (
    <main className="login-page">
      <section className="login-story">
        <a className="login-brand" href="/login">
          <span>
            <Workflow size={24} />
          </span>
          agentflow<span className="brand-period">.</span>
        </a>
        <div className="login-story-content">
          <span className="login-eyebrow">
            <Sparkles size={14} /> THE INTELLIGENT AUTOMATION WORKSPACE
          </span>
          <h1>
            Design intelligent
            <br />
            workflows.
            <br />
            <span>
              Observe every
              <br />
              decision.
            </span>
          </h1>
          <p>
            Create, automate, and monitor AI-powered workflows from one beautifully connected
            workspace.
          </p>
          <div className="login-flow">
            <div className="login-flow-node">
              <span>
                <FileText size={18} />
              </span>
              <div>
                <strong>Invoice received</strong>
                <small>Workflow triggered</small>
              </div>
              <Check size={15} />
            </div>
            <div className="login-flow-connector" />
            <div className="login-flow-node ai">
              <span>
                <Sparkles size={18} />
              </span>
              <div>
                <strong>Extract & understand</strong>
                <small>AI-powered processing</small>
              </div>
              <Check size={15} />
            </div>
            <div className="login-flow-connector" />
            <div className="login-flow-node">
              <span>
                <ShieldCheck size={18} />
              </span>
              <div>
                <strong>Human approval</strong>
                <small>You stay in control</small>
              </div>
              <CheckCircle2 size={15} />
            </div>
          </div>
        </div>
        <div className="login-story-footer">
          <span>
            <GitBranch size={16} /> Build with confidence.
          </span>
          <span>Understand every step.</span>
        </div>
      </section>
      <section className="login-form-side">
        <div className="login-mobile-brand">
          <span>
            <Workflow size={23} />
          </span>
          agentflow.
        </div>
        <div className="login-form-wrap">
          <span className="login-form-icon">
            <Zap size={23} />
          </span>
          <h2>Welcome to your flow.</h2>
          <p className="login-form-description">Sign in to build something remarkable.</p>
          <div className="login-demo-note">
            <Sparkles size={16} />
            <span>Explore the interactive demo. Any email and any demo password work.</span>
          </div>
          <form onSubmit={handleSubmit(submit)} noValidate>
            <div className="field">
              <label className="label" htmlFor="login-email">
                Email address
              </label>
              <div className="login-input-wrap">
                <Mail size={17} />
                <input
                  id="login-email"
                  type="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  className="input"
                  {...register('email')}
                />
              </div>
              {errors.email && <span className="form-error">{errors.email.message}</span>}
            </div>
            <div className="field">
              <label className="label" htmlFor="login-password">
                Demo password
              </label>
              <div className="login-input-wrap">
                <LockKeyhole size={17} />
                <input
                  id="login-password"
                  type="password"
                  autoComplete="off"
                  placeholder="Enter any demo password"
                  className="input"
                  {...register('password')}
                />
              </div>
              {errors.password && <span className="form-error">{errors.password.message}</span>}
            </div>
            <div className="login-form-options">
              <label>
                <input
                  type="checkbox"
                  checked={rememberEmail}
                  onChange={(event) => setRememberEmail(event.target.checked)}
                />{' '}
                Remember my demo email
              </label>
              <button
                type="button"
                onClick={() =>
                  setHelp(
                    'No password reset is needed in the demo. Enter any password; it is never stored or sent anywhere.',
                  )
                }
              >
                Forgot password?
              </button>
            </div>
            {help && (
              <p className="login-help" role="status">
                {help}
              </p>
            )}
            <Button variant="primary" type="submit" loading={loading} disabled={loading}>
              Sign in to workspace <ArrowRight size={16} />
            </Button>
          </form>
          <div className="login-or">
            <span />
            or explore first
            <span />
          </div>
          <Button
            variant="secondary"
            onClick={() => {
              signIn();
              navigate('/dashboard');
            }}
          >
            Continue with demo workspace <ArrowRight size={16} />
          </Button>
          <p className="login-signup">
            New to AgentFlow?{' '}
            <button
              onClick={() =>
                setHelp(
                  'The demo workspace is ready to use. Choose “Continue with demo workspace” to explore without creating an account.',
                )
              }
            >
              Create an account
            </button>
          </p>
          <p className="login-security-note">
            <ShieldCheck size={14} /> Local demo only. Passwords are never stored. This sign-in does
            not provide real authentication.
          </p>
        </div>
        <footer className="login-footer">
          © {new Date().getFullYear()} AgentFlow{' '}
          <span>Intelligent automation, thoughtfully built.</span>
        </footer>
      </section>
    </main>
  );
}
