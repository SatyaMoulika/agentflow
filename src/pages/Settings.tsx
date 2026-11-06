import { useEffect, useState } from 'react';
import {
  Bell,
  Bot,
  Check,
  Cpu,
  Eye,
  Laptop,
  Moon,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Sun,
  User,
} from 'lucide-react';
import { useForm, type FieldErrors } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useAppStore } from '../stores/useAppStore';
import { Button, PageHeader } from '../components/ui';
import type { Settings as SettingsType } from '../types';
import './management.css';

const schema = z.object({
  name: z.string().trim().min(2, 'Enter a display name of at least 2 characters.'),
  email: z.email('Enter a valid email address.'),
  theme: z.enum(['light', 'dark', 'system']),
  model: z.string().min(1),
  temperature: z.number().min(0).max(2),
  maxSteps: z.number().int().min(1).max(100),
  timeout: z.number().int().min(5).max(3600),
  retries: z.number().int().min(0).max(10),
  concurrency: z.number().int().min(1).max(50),
  tracing: z.boolean(),
  retention: z.string(),
  logLevel: z.string(),
  redaction: z.boolean(),
  notifyFailure: z.boolean(),
  notifyApproval: z.boolean(),
  notifyCompletion: z.boolean(),
});
const sections = [
  { id: 'profile', label: 'Profile', icon: User },
  { id: 'appearance', label: 'Appearance', icon: Sun },
  { id: 'agent', label: 'Agent configuration', icon: Bot },
  { id: 'execution', label: 'Execution', icon: Cpu },
  { id: 'observability', label: 'Observability', icon: Eye },
  { id: 'notifications', label: 'Notifications', icon: Bell },
];

export default function Settings() {
  const { settings, updateSettings, notify } = useAppStore();
  const [section, setSection] = useState('profile');
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors, isDirty, dirtyFields },
  } = useForm<SettingsType>({
    resolver: zodResolver(schema),
    defaultValues: { ...settings, retention: `${parseInt(settings.retention, 10) || 30} days` },
  });
  useEffect(() => {
    reset(settings, { keepDirtyValues: true });
  }, [settings, reset]);
  const theme = watch('theme');
  const submit = (data: SettingsType) => {
    const changed = Object.fromEntries(
      Object.keys(dirtyFields).map((key) => [key, data[key as keyof SettingsType]]),
    );
    updateSettings(changed);
    reset(useAppStore.getState().settings);
    notify('Your workspace preferences have been saved.');
  };
  const showErrors = (invalid: FieldErrors<SettingsType>) => {
    const field = Object.keys(invalid)[0];
    setSection(
      ['name', 'email'].includes(field)
        ? 'profile'
        : ['model', 'temperature', 'maxSteps'].includes(field)
          ? 'agent'
          : ['timeout', 'retries', 'concurrency'].includes(field)
            ? 'execution'
            : field === 'theme'
              ? 'appearance'
              : 'observability',
    );
    notify('Review the highlighted fields before saving.', 'error');
  };
  const checkbox = (
    name: 'tracing' | 'redaction' | 'notifyFailure' | 'notifyApproval' | 'notifyCompletion',
    title: string,
    description: string,
  ) => (
    <label className="settings-toggle-row">
      <span>
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <input type="checkbox" className="switch-input" {...register(name)} />
    </label>
  );
  return (
    <div className="management-page">
      <PageHeader title="Settings" description="Make AgentFlow work the way you do." />
      <form onSubmit={handleSubmit(submit, showErrors)} noValidate>
        <div className="settings-layout">
          <nav className="settings-nav" aria-label="Settings sections">
            {sections.map(({ id, label, icon: Icon }) => (
              <button
                type="button"
                key={id}
                aria-current={section === id ? 'page' : undefined}
                className={section === id ? 'active' : ''}
                onClick={() => setSection(id)}
              >
                <Icon size={17} />
                {label}
              </button>
            ))}
          </nav>
          <div className="settings-main">
            <section className="card settings-section" hidden={section !== 'profile'}>
              <div className="settings-section-heading">
                <h2>Your profile</h2>
                <p>Your personal information in this demo workspace.</p>
              </div>
              <div className="profile-avatar-row">
                <span className="settings-avatar">
                  {watch('name')
                    .split(' ')
                    .map((n) => n[0])
                    .join('')
                    .slice(0, 2)
                    .toUpperCase()}
                </span>
                <div>
                  <strong>Profile avatar</strong>
                  <p>Your initials are used automatically.</p>
                </div>
              </div>
              <div className="settings-fields">
                <div className="field">
                  <label className="label" htmlFor="profile-name">
                    Display name
                  </label>
                  <input id="profile-name" className="input" {...register('name')} />
                  {errors.name && <span className="form-error">{errors.name.message}</span>}
                </div>
                <div className="field">
                  <label className="label" htmlFor="profile-email">
                    Email address
                  </label>
                  <input id="profile-email" className="input" type="email" {...register('email')} />
                  {errors.email && <span className="form-error">{errors.email.message}</span>}
                  <small className="muted">Used as your identity in the local demo.</small>
                </div>
              </div>
            </section>
            <section className="card settings-section" hidden={section !== 'appearance'}>
              <div className="settings-section-heading">
                <h2>Appearance</h2>
                <p>Choose a theme that feels right for your workspace.</p>
              </div>
              <div className="theme-options">
                {(
                  [
                    { value: 'light', label: 'Light', icon: Sun },
                    { value: 'dark', label: 'Dark', icon: Moon },
                    { value: 'system', label: 'System', icon: Laptop },
                  ] as const
                ).map(({ value, label, icon: Icon }) => (
                  <button
                    type="button"
                    key={value}
                    className={`theme-option ${theme === value ? 'selected' : ''}`}
                    onClick={() => setValue('theme', value, { shouldDirty: true })}
                  >
                    <div className={`theme-preview ${value}`}>
                      <div className="theme-mini-sidebar" />
                      <div className="theme-mini-main">
                        <span />
                        <div>
                          <i />
                          <i />
                        </div>
                        <span />
                      </div>
                    </div>
                    <span>
                      <Icon size={16} />
                      {label}
                      {theme === value && <Check size={15} />}
                    </span>
                  </button>
                ))}
              </div>
              <p className="muted settings-small-note">
                Save your preferences to apply this theme throughout the app.
              </p>
            </section>
            <section className="card settings-section" hidden={section !== 'agent'}>
              <div className="settings-section-heading">
                <h2>Agent configuration</h2>
                <p>Default values for new AI nodes in your workspace.</p>
              </div>
              <div className="settings-fields">
                <div className="field">
                  <label className="label" htmlFor="default-model">
                    Default model
                  </label>
                  <select id="default-model" className="input" {...register('model')}>
                    <option value="gpt-4.1-mini">GPT-4.1 mini</option>
                    <option value="gpt-4.1">GPT-4.1</option>
                    <option value="gpt-4o-mini">GPT-4o mini</option>
                    <option value="claude-sonnet-4">Claude Sonnet 4 (demo)</option>
                    <option value="local-model">Local model (demo)</option>
                  </select>
                  <small className="muted">
                    Model selection is simulated. No provider is called.
                  </small>
                </div>
                <div className="field">
                  <label className="label" htmlFor="temperature">
                    Temperature <span className="range-value">{watch('temperature')}</span>
                  </label>
                  <input
                    id="temperature"
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    {...register('temperature', { valueAsNumber: true })}
                  />
                  <div className="range-labels">
                    <span>Precise</span>
                    <span>Creative</span>
                  </div>
                </div>
                <div className="settings-field-grid">
                  <div className="field">
                    <label className="label" htmlFor="max-steps">
                      Maximum agent steps
                    </label>
                    <input
                      id="max-steps"
                      className="input"
                      type="number"
                      min="1"
                      max="100"
                      {...register('maxSteps', { valueAsNumber: true })}
                    />
                    {errors.maxSteps && <span className="form-error">Use 1–100 steps.</span>}
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="agent-timeout">
                      Default timeout (seconds)
                    </label>
                    <input
                      id="agent-timeout"
                      className="input"
                      type="number"
                      min="5"
                      max="3600"
                      value={Number.isNaN(watch('timeout')) ? '' : watch('timeout')}
                      {...register('timeout', { valueAsNumber: true })}
                    />
                    {errors.timeout && <span className="form-error">Use 5–3600 seconds.</span>}
                  </div>
                </div>
              </div>
            </section>
            <section className="card settings-section" hidden={section !== 'execution'}>
              <div className="settings-section-heading">
                <h2>Execution settings</h2>
                <p>Configure the default behavior of simulated workflow runs.</p>
              </div>
              <div className="settings-fields">
                <div className="settings-field-grid">
                  <div className="field">
                    <label className="label" htmlFor="retries">
                      Retry attempts
                    </label>
                    <input
                      id="retries"
                      className="input"
                      type="number"
                      min="0"
                      max="10"
                      {...register('retries', { valueAsNumber: true })}
                    />
                    {errors.retries && <span className="form-error">Use 0–10 retry attempts.</span>}
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="concurrency">
                      Concurrent executions
                    </label>
                    <input
                      id="concurrency"
                      className="input"
                      type="number"
                      min="1"
                      max="50"
                      {...register('concurrency', { valueAsNumber: true })}
                    />
                    {errors.concurrency && (
                      <span className="form-error">Use 1–50 concurrent executions.</span>
                    )}
                  </div>
                </div>
                <div className="field">
                  <label className="label" htmlFor="execution-timeout">
                    Execution timeout (seconds)
                  </label>
                  <input
                    id="execution-timeout"
                    className="input"
                    type="number"
                    min="5"
                    max="3600"
                    value={Number.isNaN(watch('timeout')) ? '' : watch('timeout')}
                    {...register('timeout', { valueAsNumber: true })}
                  />
                  {errors.timeout && <span className="form-error">Use 5–3600 seconds.</span>}
                  <small className="muted">
                    Shared with the default agent timeout in this prototype.
                  </small>
                </div>
              </div>
            </section>
            <section className="card settings-section" hidden={section !== 'observability'}>
              <div className="settings-section-heading">
                <h2>Observability</h2>
                <p>Choose how you inspect and retain your execution data.</p>
              </div>
              {checkbox(
                'tracing',
                'Execution tracing',
                'Show node spans and trace metadata in the execution inspector.',
              )}
              <div className="settings-fields">
                <div className="settings-field-grid">
                  <div className="field">
                    <label className="label" htmlFor="retention">
                      Trace retention preference
                    </label>
                    <select id="retention" className="input" {...register('retention')}>
                      <option value="7 days">7 days</option>
                      <option value="30 days">30 days</option>
                      <option value="90 days">90 days</option>
                    </select>
                  </div>
                  <div className="field">
                    <label className="label" htmlFor="log-level">
                      Log level
                    </label>
                    <select id="log-level" className="input" {...register('logLevel')}>
                      <option value="debug">Debug</option>
                      <option value="info">Info</option>
                      <option value="warn">Warning</option>
                      <option value="error">Error</option>
                    </select>
                  </div>
                </div>
              </div>
              {checkbox(
                'redaction',
                'Sensitive data redaction',
                'Remember a preference for hiding sensitive fields in future backend traces.',
              )}
              <div className="settings-disclaimer">
                <ShieldCheck size={17} />
                These are local preferences. Retention and security policies require a backend
                implementation.
              </div>
            </section>
            <section className="card settings-section" hidden={section !== 'notifications'}>
              <div className="settings-section-heading">
                <h2>Notifications</h2>
                <p>Decide which events you want to hear about.</p>
              </div>
              {checkbox(
                'notifyFailure',
                'Workflow failures',
                'When an execution fails and needs your attention.',
              )}
              {checkbox(
                'notifyApproval',
                'Approval requests',
                'When a workflow is waiting for a human decision.',
              )}
              {checkbox(
                'notifyCompletion',
                'Execution completion',
                'When a workflow finishes successfully.',
              )}
              <p className="muted settings-small-note">
                Preferences are saved locally. This demo does not send emails or push notifications.
              </p>
            </section>
            <div className="settings-save">
              <span>
                {isDirty ? 'You have unsaved changes' : 'Your preferences are up to date'}
              </span>
              <div>
                <Button
                  type="button"
                  variant="secondary"
                  disabled={!isDirty}
                  onClick={() => reset(settings)}
                >
                  Discard
                </Button>
                <Button variant="primary" type="submit" disabled={!isDirty}>
                  <Save size={16} /> Save changes
                </Button>
              </div>
            </div>
          </div>
        </div>
      </form>
      <div className="settings-footer">
        <SlidersHorizontal size={14} /> Workspace preferences are stored in this browser.
      </div>
    </div>
  );
}
