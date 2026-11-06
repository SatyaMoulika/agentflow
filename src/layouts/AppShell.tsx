import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowUpRight,
  Bell,
  BookOpen,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Command,
  House,
  LayoutGrid,
  LogOut,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Workflow,
  X,
} from 'lucide-react';
import { useAppStore } from '../stores/useAppStore';
import { Button, Modal, SearchInput, UserAvatar } from '../components/ui';
import './shell.css';
const navigation = [
  { path: '/dashboard', label: 'Overview', icon: House },
  { path: '/workflows', label: 'Workflows', icon: Workflow },
  { path: '/executions', label: 'Executions', icon: Activity },
  { path: '/integrations', label: 'Integrations', icon: LayoutGrid },
  { path: '/approvals', label: 'Approvals', icon: ShieldCheck },
];
export default function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [search, setSearch] = useState(false);
  const [term, setTerm] = useState('');
  const [notifications, setNotifications] = useState(false);
  const [profile, setProfile] = useState(false);
  const [help, setHelp] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const location = useLocation();
  const navigate = useNavigate();
  const settings = useAppStore((s) => s.settings);
  const workflows = useAppStore((s) => s.workflows);
  const approvals = useAppStore((s) => s.approvals);
  const updateSettings = useAppStore((s) => s.updateSettings);
  const signOut = useAppStore((s) => s.signOut);
  const isEditor =
    /^\/workflows\/[^/]+(?:\/edit)?\/?$/.test(location.pathname) &&
    location.pathname !== '/workflows/new';
  const toggleTheme = () =>
    updateSettings({ theme: document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark' });
  const pending = approvals.filter((a) => a.status === 'pending');
  const current = navigation.find((n) => location.pathname.startsWith(n.path));
  const section = location.pathname.startsWith('/settings')
    ? 'Settings'
    : current?.label || 'Workspace';
  useEffect(() => {
    setMobile(false);
    setProfile(false);
  }, [location.pathname]);
  useEffect(() => {
    if (mobile) sidebarRef.current?.querySelector<HTMLElement>('a,button')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobile(false);
        setProfile(false);
        setNotifications(false);
      }
      if (mobile && event.key === 'Tab') {
        const focusable = Array.from(
          sidebarRef.current?.querySelectorAll<HTMLElement>('a,button') || [],
        ).filter((el) => el.getClientRects().length);
        const first = focusable[0];
        const last = focusable.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [mobile]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearch((v) => !v);
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);
  const go = (path: string) => {
    navigate(path);
    setSearch(false);
    setTerm('');
  };
  return (
    <div className={`app-shell ${collapsed ? 'sidebar-collapsed' : ''}`}>
      <button
        aria-label="Close navigation"
        className={`sidebar-backdrop ${mobile ? 'visible' : ''}`}
        onClick={() => setMobile(false)}
      />
      <aside
        ref={sidebarRef}
        id="workspace-navigation"
        className={`sidebar ${mobile ? 'mobile-open' : ''}`}
      >
        <NavLink className="brand" to="/dashboard">
          <span className="brand-mark">
            <svg viewBox="0 0 32 32" aria-hidden="true">
              <path d="m8 23 8-15 8 15M12 19h8" />
              <circle cx="24" cy="8" r="2" />
            </svg>
          </span>
          <span className="brand-name">
            agentflow<span className="brand-period">.</span>
          </span>
        </NavLink>
        <button
          className="workspace-picker"
          aria-label="Open workspace account menu"
          aria-expanded={profile}
          onClick={() => {
            setProfile((v) => !v);
            setMobile(false);
          }}
        >
          <span className="workspace-avatar">M</span>
          <span className="workspace-info">
            <strong>My workspace</strong>
            <span>Personal workspace</span>
          </span>
          <ChevronDown size={13} />
        </button>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Main navigation">
          {navigation.map(({ path, label, icon: Icon }) => (
            <NavLink
              key={path}
              to={path}
              className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
              title={collapsed ? label : undefined}
              aria-label={label}
            >
              <Icon size={18} />
              <span>{label}</span>
              {path === '/approvals' && pending.length > 0 && (
                <b className="nav-count">{pending.length}</b>
              )}
              {path === '/workflows' && (
                <span className="nav-hover-plus">
                  <Plus size={14} />
                </span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="workspace-health">
            <span className="health-dot" />
            <span>Demo workspace ready</span>
            <ArrowUpRight size={12} />
          </div>
          <div className="sidebar-promo">
            <span className="promo-icon">
              <Sparkles size={16} />
            </span>
            <strong>A little AI. A lot of possibility.</strong>
            <p>Turn your next idea into a workflow.</p>
            <button onClick={() => navigate('/workflows/new')}>
              Build with AI <ArrowUpRight size={13} />
            </button>
          </div>
          <button className="nav-item" onClick={() => setHelp(true)}>
            <CircleHelp size={17} />
            <span>Help & resources</span>
            <ArrowUpRight size={13} />
          </button>
          <NavLink
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            to="/settings"
            aria-label="Settings"
          >
            <Settings2 size={17} />
            <span>Settings</span>
          </NavLink>
          <div className="sidebar-user">
            <button
              className="sidebar-profile"
              aria-label="Open account menu"
              aria-expanded={profile}
              onClick={() => {
                setProfile((v) => !v);
                setMobile(false);
              }}
            >
              <UserAvatar name={settings.name} />
              <span>
                <strong>{settings.name}</strong>
                <small>Personal account</small>
              </span>
              <ChevronDown size={13} />
            </button>
            <button
              className="icon-button collapse-control"
              aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              onClick={() => setCollapsed((v) => !v)}
            >
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              aria-controls="workspace-navigation"
              aria-expanded={mobile}
              onClick={() => setMobile(true)}
            >
              <Menu size={19} />
            </button>
            <House size={14} />
            <ChevronRight size={12} />
            <span>{section}</span>
            {location.pathname.split('/').length > 2 && (
              <>
                <ChevronRight size={12} />
                <strong>
                  {isEditor
                    ? 'Editor'
                    : location.pathname.includes('/new')
                      ? 'Create workflow'
                      : 'Details'}
                </strong>
              </>
            )}
          </div>
          <div className="topbar-actions">
            <span className="demo-pill">
              <span />
              Prototype mode
            </span>
            <button
              className="global-search"
              onClick={() => setSearch(true)}
              aria-label="Search workspace"
            >
              <Search size={15} />
              <span>Search anything...</span>
              <kbd>⌘ K</kbd>
            </button>
            <button
              className="icon-button theme-button"
              aria-label="Toggle color theme"
              onClick={toggleTheme}
            >
              {settings.theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <span className="topbar-divider" />
            <button
              className="icon-button notification-button"
              aria-label={`Notifications, ${pending.length} pending approvals`}
              aria-expanded={notifications}
              onClick={() => setNotifications((v) => !v)}
            >
              <Bell size={17} />
              {pending.length > 0 && <i />}
            </button>
            <button
              className="profile-trigger"
              aria-expanded={profile}
              aria-label="Open account menu"
              onClick={() => setProfile((v) => !v)}
            >
              <UserAvatar name={settings.name} size="sm" />
            </button>
          </div>
        </header>
        <main className={`page-content ${isEditor ? 'editor-page-content' : ''}`}>
          <Outlet />
        </main>
        <footer className="app-footer">
          <span>Thoughtfully automated.</span>
          <span>
            <span className="health-dot" /> AgentFlow frontend prototype{' '}
            <span className="footer-separator">·</span> v0.1.0
          </span>
        </footer>
      </div>
      {profile && (
        <>
          <button
            className="popover-dismiss"
            aria-label="Close account menu"
            onClick={() => setProfile(false)}
          />
          <div className="account-popover card">
            <div className="account-label">
              <strong>{settings.name}</strong>
              <small>{settings.email}</small>
            </div>
            <button
              onClick={() => {
                navigate('/settings');
                setProfile(false);
              }}
            >
              <Settings2 size={15} />
              Account settings
            </button>
            <button onClick={toggleTheme}>
              <Moon size={15} />
              Toggle light / dark mode
            </button>
            <hr />
            <button
              onClick={() => {
                signOut();
                navigate('/login');
              }}
            >
              <LogOut size={15} />
              Sign out of demo
            </button>
          </div>
        </>
      )}
      {notifications && (
        <>
          <button
            className="popover-dismiss"
            aria-label="Close notifications"
            onClick={() => setNotifications(false)}
          />
          <div className="notification-popover card">
            <div className="section-heading">
              <h2>Notifications</h2>
              <button
                className="icon-button"
                aria-label="Close notifications"
                onClick={() => setNotifications(false)}
              >
                <X size={15} />
              </button>
            </div>
            {pending.length ? (
              pending.map((a) => (
                <button
                  className="notification-item"
                  key={a.id}
                  onClick={() => {
                    navigate(`/approvals/${a.id}`);
                    setNotifications(false);
                  }}
                >
                  <span className="notification-icon">
                    <ShieldCheck size={18} />
                  </span>
                  <span>
                    <strong>{a.title}</strong>
                    <small>{a.workflowName} needs your review.</small>
                  </span>
                  <ChevronRight size={14} />
                </button>
              ))
            ) : (
              <p className="no-notifications">You're all caught up.</p>
            )}
            <div className="notification-note">Demo workspace notifications</div>
          </div>
        </>
      )}
      <Modal open={search} onClose={() => setSearch(false)} title="Search your workspace">
        <SearchInput
          value={term}
          onChange={setTerm}
          placeholder="Find workflows, pages, and actions…"
        />
        <div className="command-results">
          <div className="eyebrow">Jump to</div>
          {[
            ...navigation.map((n) => ({ label: n.label, path: n.path, icon: n.icon })),
            { label: 'Create a workflow', path: '/workflows/new', icon: Plus },
            ...workflows.map((w) => ({
              label: w.name,
              path: `/workflows/${w.id}/edit`,
              icon: Workflow,
            })),
          ]
            .filter((n) => n.label.toLowerCase().includes(term.toLowerCase()))
            .map((n) => (
              <button key={n.path} onClick={() => go(n.path)}>
                <n.icon size={16} />
                {n.label}
                <ChevronRight size={13} />
              </button>
            ))}
        </div>
        <div className="command-note">
          <Command size={12} /> K to open · Esc to close
        </div>
      </Modal>
      <Modal open={help} onClose={() => setHelp(false)} title="Welcome to AgentFlow">
        <div className="help-body">
          <BookOpen size={30} />
          <h3>Your automation playground</h3>
          <p className="muted">
            Create a workflow with one of the supported demo prompts, edit its graph, then run it to
            inspect every step. Invoice workflows pause at a human approval so you can review and
            resume them.
          </p>
          <div className="prototype-note">
            This frontend uses local browser storage and deterministic simulations. Connections, AI
            generation, and workflow runs are demonstrations.
          </div>
          <Button
            variant="primary"
            onClick={() => {
              setHelp(false);
              navigate('/workflows/new');
            }}
          >
            Create your first workflow <ArrowUpRight size={14} />
          </Button>
        </div>
      </Modal>
    </div>
  );
}
