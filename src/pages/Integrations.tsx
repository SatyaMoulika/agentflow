import { useEffect, useState } from 'react';
import {
  Check,
  CheckCircle2,
  CircleHelp,
  Cloud,
  Code2,
  Database,
  ExternalLink,
  Globe,
  KeyRound,
  Mail,
  MessageSquare,
  Plug,
  Search,
  Sheet,
  Sparkles,
  Unplug,
} from 'lucide-react';
import { useAppStore } from '../stores/useAppStore';
import { Button, EmptyState, Modal, PageHeader, SearchInput } from '../components/ui';
import type { Integration } from '../types';
import './management.css';

const categories = [
  'All',
  'Communication',
  'Productivity',
  'Developer Tools',
  'Storage',
  'AI Providers',
];
function IntegrationIcon({ integration }: { integration: Integration }) {
  const Icon = /gmail/i.test(integration.name)
    ? Mail
    : /sheets/i.test(integration.name)
      ? Sheet
      : /slack/i.test(integration.name)
        ? MessageSquare
        : /drive/i.test(integration.name)
          ? Cloud
          : /postgres/i.test(integration.name)
            ? Database
            : /llm|openai/i.test(integration.name)
              ? Sparkles
              : /webhook/i.test(integration.name)
                ? Globe
                : Code2;
  return (
    <span
      className="integration-icon"
      style={{ color: integration.color, backgroundColor: `${integration.color}12` }}
    >
      <Icon size={26} strokeWidth={1.8} />
    </span>
  );
}
export default function Integrations() {
  const { integrations, updateIntegration, notify } = useAppStore();
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('All');
  const [selected, setSelected] = useState<Integration | null>(null);
  const [connectionName, setConnectionName] = useState('');
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success'>('idle');
  const [nameError, setNameError] = useState('');
  useEffect(() => {
    if (testStatus !== 'testing') return;
    const timeout = setTimeout(() => setTestStatus('success'), 850);
    return () => clearTimeout(timeout);
  }, [testStatus]);
  const open = (integration: Integration) => {
    setSelected(integration);
    setConnectionName(integration.connectionName || `${integration.name} demo connection`);
    setTestStatus('idle');
    setNameError('');
  };
  const visible = integrations.filter(
    (integration) =>
      (category === 'All' || integration.category.toLowerCase() === category.toLowerCase()) &&
      `${integration.name} ${integration.description}`.toLowerCase().includes(search.toLowerCase()),
  );
  const test = () => {
    if (!connectionName.trim()) {
      setNameError('Enter a name for this demo connection.');
      return;
    }
    setTestStatus('testing');
  };
  const save = () => {
    if (!selected || !connectionName.trim() || testStatus !== 'success') return;
    updateIntegration(selected.id, { connected: true, connectionName: connectionName.trim() });
    setSelected(null);
    notify(`${selected.name} demo connection saved.`);
  };
  return (
    <div className="management-page">
      <PageHeader
        title="Integrations"
        description="Bring your favorite tools into the flow."
        actions={
          <span className="connection-count">
            <span className="summary-dot" />
            {integrations.filter((i) => i.connected).length} connected
          </span>
        }
      />
      <div className="integration-banner">
        <span className="banner-icon">
          <Plug size={22} />
        </span>
        <div>
          <strong>A connected workspace. Endless possibilities.</strong>
          <p>Give your workflows the tools they need to turn decisions into action.</p>
        </div>
        <span className="integration-demo-pill">Demo connections</span>
      </div>
      <div className="integration-search">
        <SearchInput value={search} onChange={setSearch} placeholder="Search integrations..." />
      </div>
      <div className="category-tabs" aria-label="Integration categories">
        {categories.map((item) => (
          <button
            key={item}
            aria-pressed={category === item}
            className={category === item ? 'active' : ''}
            onClick={() => setCategory(item)}
          >
            {item}
          </button>
        ))}
      </div>
      {visible.length ? (
        <div className="integrations-grid">
          {visible.map((integration) => (
            <article className="card integration-card" key={integration.id}>
              <div className="integration-top">
                <IntegrationIcon integration={integration} />
                {integration.connected ? (
                  <span className="integration-connected">
                    <CheckCircle2 size={13} /> Connected
                  </span>
                ) : (
                  <span className="integration-unconnected">Not connected</span>
                )}
              </div>
              <h3>{integration.name}</h3>
              <p>{integration.description}</p>
              <div className="integration-card-bottom">
                <span>{integration.category}</span>
                <Button variant="secondary" size="sm" onClick={() => open(integration)}>
                  {integration.connected ? 'Configure' : 'Connect'}
                  {!integration.connected && <PlusIcon />}
                </Button>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<Search size={25} />}
          title="No integrations found"
          description="Try a different search or category."
          action={
            <Button
              variant="secondary"
              onClick={() => {
                setSearch('');
                setCategory('All');
              }}
            >
              Clear filters
            </Button>
          }
        />
      )}
      <div className="integration-help">
        <CircleHelp size={17} />
        <span>
          All connections are simulated for this prototype. No OAuth sign-in or API keys are
          required.
        </span>
      </div>
      <Modal
        open={!!selected}
        onClose={() => setSelected(null)}
        title={
          selected
            ? `${selected.connected ? 'Configure' : 'Connect'} ${selected.name}`
            : 'Connect integration'
        }
        footer={
          <>
            <Button variant="ghost" onClick={() => setSelected(null)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={testStatus !== 'success'} onClick={save}>
              Save connection
            </Button>
          </>
        }
      >
        {selected && (
          <div className="integration-modal">
            <div className="modal-provider">
              <IntegrationIcon integration={selected} />
              <div>
                <strong>{selected.name}</strong>
                <p className="muted">{selected.description}</p>
              </div>
            </div>
            <div className="demo-callout">
              <KeyRound size={17} />
              <span>Demo mode — this connection is simulated. Don’t enter real credentials.</span>
            </div>
            <div className="field">
              <label className="label" htmlFor="connection-name">
                Connection name
              </label>
              <input
                id="connection-name"
                className="input"
                value={connectionName}
                onChange={(e) => {
                  setConnectionName(e.target.value);
                  setTestStatus('idle');
                  setNameError('');
                }}
              />
              {nameError && <span className="form-error">{nameError}</span>}
            </div>
            <div className="field">
              <label className="label" htmlFor="connection-provider">
                Provider
              </label>
              <input id="connection-provider" className="input" value={selected.name} readOnly />
            </div>
            <div className="field">
              <label className="label" htmlFor="connection-method">
                Authentication method
              </label>
              <select id="connection-method" className="input" defaultValue="demo">
                <option value="demo">Simulated connection (no credentials)</option>
              </select>
            </div>
            <div className="test-connection">
              <Button variant="secondary" loading={testStatus === 'testing'} onClick={test}>
                {testStatus === 'success' ? <Check size={16} /> : <Plug size={16} />}
                {testStatus === 'success' ? 'Test again' : 'Test demo connection'}
              </Button>
              {testStatus === 'success' && (
                <span role="status">
                  <CheckCircle2 size={15} /> Simulated test passed
                </span>
              )}
            </div>
            {selected.connected && (
              <button
                className="disconnect-button"
                onClick={() => {
                  updateIntegration(selected.id, { connected: false, connectionName: undefined });
                  setSelected(null);
                  notify(`${selected.name} disconnected.`);
                }}
              >
                <Unplug size={15} /> Disconnect integration
              </button>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
function PlusIcon() {
  return <ExternalLink size={13} />;
}
