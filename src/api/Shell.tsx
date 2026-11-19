import { useState } from 'react';
import { NavLink, Outlet, Link } from 'react-router-dom';
import {
  Activity,
  ClipboardCheck,
  House,
  Layers3,
  LogOut,
  Menu,
  Play,
  Settings,
  Workflow,
  X,
} from 'lucide-react';
import { Button, UserAvatar } from '../components/ui';
import { client } from './client';
import { Failure } from './common';
import { useSession } from './session';
import '../layouts/shell.css';
const links = [
  ['/dashboard', 'Overview', House],
  ['/workflows', 'Workflows', Workflow],
  ['/run', 'Run workflow', Play],
  ['/executions', 'Executions', Activity],
  ['/integrations', 'Integrations', Layers3],
  ['/approvals', 'Approvals', ClipboardCheck],
  ['/settings', 'Account', Settings],
] as const;
export default function Shell() {
  const { user } = useSession();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function logout() {
    setBusy(true);
    setError(null);
    try {
      await client.logout();
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="app-shell api-shell">
      <button
        aria-label="Close navigation"
        className={`sidebar-backdrop ${open ? 'visible' : ''}`}
        onClick={() => setOpen(false)}
      />
      <aside className={`sidebar ${open ? 'mobile-open' : ''}`}>
        <Link className="brand" to="/dashboard">
          <span className="brand-mark">
            <Workflow size={22} color="white" />
          </span>
          <span className="brand-name">
            agentflow<span className="brand-period">.</span>
          </span>
        </Link>
        <div className="workspace-picker">
          <UserAvatar name={user?.display_name || ''} />
          <span className="workspace-info">
            <strong>My workspace</strong>
            <span>Personal account</span>
          </span>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {links.map(([path, label, Icon]) => (
            <NavLink
              key={path}
              to={path}
              onClick={() => setOpen(false)}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            >
              <Icon size={18} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="api-panel">
            <strong>A little structure. More flow.</strong>
            <p className="muted">Save workflows and inspect actual execution results.</p>
          </div>
          <div className="sidebar-user">
            <UserAvatar name={user?.display_name || ''} />
            <div className="api-grow">
              <strong>{user?.display_name}</strong>
              <small className="api-email">{user?.email}</small>
            </div>
            <Button
              loading={busy}
              disabled={busy}
              variant="ghost"
              onClick={logout}
              title="Sign out"
            >
              <LogOut size={17} />
            </Button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="api-actions">
            <Button
              className="api-mobile"
              onClick={() => setOpen(!open)}
              aria-label="Open navigation"
            >
              {open ? <X size={18} /> : <Menu size={18} />}
            </Button>
            <span className="muted">Personal workspace</span>
          </div>
          <span className="api-connected">Workflow studio</span>
        </header>
        <main className="page-content">
          {error !== null && <Failure error={error} />}
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>Thoughtfully automated.</span>
          <span>AgentFlow · Workflow studio</span>
        </footer>
      </div>
    </div>
  );
}
