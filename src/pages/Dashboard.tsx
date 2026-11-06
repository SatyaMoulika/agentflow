import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Braces,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileText,
  GitBranch,
  Mail,
  Plus,
  ShieldCheck,
  Sparkles,
  Workflow,
  Zap,
  type LucideIcon,
} from 'lucide-react';
import { format, startOfDay, subDays } from 'date-fns';
import { Badge, Button, EmptyState } from '../components/ui';
import { mockApi, calculateMetrics } from '../services/api';
import { useAppStore } from '../stores/useAppStore';
import { formatDuration, relativeTime } from '../lib/utils';
import { createBlankWorkflow } from '../services/generation';
import './dashboard.css';
const workflowIcons: Record<string, LucideIcon> = {
  invoice: FileText,
  email: Mail,
  support: Braces,
  document: FileText,
  lead: Zap,
  report: Activity,
};
const workflowColors = ['violet', 'blue', 'teal', 'amber'];
function MiniTrend({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(...values, 1);
  const points = values
    .map((v, i) => `${(i * 72) / Math.max(values.length - 1, 1)},${32 - (v / max) * 27}`)
    .join(' ');
  return (
    <svg className="metric-trend" viewBox="0 0 72 36" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  trend,
  values,
  color,
}: {
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  trend?: string;
  values: number[];
  color: string;
}) {
  return (
    <div className="card metric-card">
      <div className="metric-top">
        <span>{label}</span>
        <Icon size={16} />
      </div>
      <div className="metric-value-line">
        <strong>{value}</strong>
        <MiniTrend values={values} color={color} />
      </div>
      <div className="metric-detail">
        {trend && (
          <span className="metric-positive">
            <ArrowUpRight size={11} />
            {trend}
          </span>
        )}
        <span>{detail}</span>
      </div>
    </div>
  );
}
export default function Dashboard() {
  const navigate = useNavigate();
  const workflows = useAppStore((s) => s.workflows);
  const executions = useAppStore((s) => s.executions);
  const settings = useAppStore((s) => s.settings);
  const approvals = useAppStore((s) => s.approvals);
  const [period, setPeriod] = useState('7');
  const [dateMenu, setDateMenu] = useState(false);
  const [now] = useState(() => new Date());
  const { data: loaded, isPending } = useQuery({
    queryKey: ['dashboard', workflows, executions],
    queryFn: () => mockApi.getDashboard(workflows, executions),
  });
  const metrics = loaded || calculateMetrics(workflows, executions);
  const pending = approvals.filter((a) => a.status === 'pending').length;
  const chartData = useMemo(() => {
    if (period === '1') {
      return Array.from({ length: 12 }, (_, i) => {
        const start = now.getTime() - 24 * 3600000 + i * 2 * 3600000;
        const slice = executions.filter(
          (e) => +new Date(e.startedAt) >= start && +new Date(e.startedAt) < start + 2 * 3600000,
        );
        return {
          label: format(new Date(start), 'HH:mm'),
          success: slice.filter((e) => e.status === 'succeeded').length,
          failed: slice.filter((e) => e.status === 'failed').length,
        };
      });
    }
    const days = Number(period);
    return Array.from({ length: days }, (_, i) => {
      const date = startOfDay(subDays(now, days - i - 1));
      const slice = executions.filter(
        (e) => format(new Date(e.startedAt), 'yyyy-MM-dd') === format(date, 'yyyy-MM-dd'),
      );
      return {
        label: format(date, 'MMM d'),
        success: slice.filter((e) => e.status === 'succeeded').length,
        failed: slice.filter((e) => e.status === 'failed').length,
      };
    });
  }, [period, executions, now]);
  const breakdown = [
    { name: 'Successful', value: metrics.succeeded, color: '#7e83ee' },
    { name: 'Failed', value: metrics.failed, color: '#f194a1' },
    { name: 'Running', value: metrics.running, color: '#7bb7f1' },
    { name: 'Awaiting approval', value: metrics.waiting, color: '#efc372' },
    {
      name: 'Cancelled',
      value: executions.filter((e) => e.status === 'cancelled').length,
      color: '#c7cdd9',
    },
  ].filter((s) => s.value > 0);
  const recent = [...executions]
    .sort((a, b) => +new Date(b.startedAt) - +new Date(a.startedAt))
    .slice(0, 5);
  const activityTrend = chartData.map((day) => day.success + day.failed);
  const successTrend = chartData.map((day) =>
    day.success + day.failed ? (day.success / (day.success + day.failed)) * 100 : 0,
  );
  const workflowTrend = chartData.map(
    (_, i) =>
      workflows.filter((w) => +new Date(w.createdAt) <= +subDays(now, chartData.length - i - 1))
        .length,
  );
  const durationsTrend = chartData.map((_, i) => {
    const since = +subDays(now, chartData.length - i);
    const until = +subDays(now, chartData.length - i - 1);
    const runs = executions.filter(
      (e) =>
        +new Date(e.startedAt) >= since &&
        +new Date(e.startedAt) < until &&
        ['succeeded', 'failed'].includes(e.status),
    );
    return runs.length ? runs.reduce((sum, e) => sum + e.duration, 0) / runs.length : 0;
  });
  const successfulPercent = metrics.totalExecutions
    ? Math.round((metrics.succeeded / metrics.totalExecutions) * 100)
    : 0;
  return (
    <div className="dashboard">
      <div className="dashboard-heading">
        <div>
          <div className="greeting-eyebrow">
            <span /> YOUR WORKSPACE, AT A GLANCE
          </div>
          <h1>
            Welcome back, {settings.name.split(' ')[0]} <span className="wave">✳</span>
          </h1>
          <p>Big ideas. Smooth workflows. Here’s what’s happening today.</p>
        </div>
        <Button variant="primary" onClick={() => navigate('/workflows/new')}>
          <Plus size={16} />
          Create workflow
        </Button>
      </div>
      <section className="ai-banner">
        <div className="ai-banner-content">
          <span className="ai-banner-tag">
            <Sparkles size={12} /> FROM IDEA TO AUTOMATION
          </span>
          <h2>
            You describe it.
            <br />
            Your workflow takes shape.
          </h2>
          <p>
            Bring your next idea to life with AI. Build, connect,
            <br className="desktop-br" /> and automate in a few simple words.
          </p>
          <Button onClick={() => navigate('/workflows/new')}>
            Build with AI <ArrowRight size={14} />
          </Button>
          <span className="ai-banner-demo">Try a guided demo</span>
        </div>
        <div className="hero-flow" aria-hidden="true">
          <svg className="hero-flow-lines" viewBox="0 0 560 240" preserveAspectRatio="none">
            <path d="M55 130H145Q163 130 163 110V72Q163 54 185 54H228" />
            <path d="M347 54H373Q395 54 395 78V130Q395 145 418 145H465" />
            <path d="M286 89V172Q286 191 309 191H369" />
            <circle cx="164" cy="99" r="3" />
            <circle cx="395" cy="105" r="3" />
          </svg>
          <div className="hero-node trigger">
            <span className="hero-node-icon">
              <Zap size={17} />
            </span>
            <div>
              <small>TRIGGER</small>
              <strong>When it happens</strong>
            </div>
            <span className="hero-node-check">
              <Check size={11} />
            </span>
          </div>
          <div className="hero-node intelligence">
            <span className="hero-node-icon">
              <Sparkles size={20} />
            </span>
            <div>
              <small>AI ACTION</small>
              <strong>A little intelligence</strong>
            </div>
            <span className="hero-node-check">
              <Check size={11} />
            </span>
          </div>
          <div className="hero-node done">
            <span className="hero-node-icon">
              <CheckCircle2 size={17} />
            </span>
            <div>
              <small>OUTCOME</small>
              <strong>Consider it done.</strong>
            </div>
          </div>
          <div className="hero-node human">
            <span className="hero-node-icon">
              <ShieldCheck size={17} />
            </span>
            <div>
              <small>HUMAN IN THE LOOP</small>
              <strong>You’re in control</strong>
            </div>
          </div>
          <span className="hero-spark spark-one">✧</span>
          <span className="hero-spark spark-two">✧</span>
        </div>
      </section>
      <div className="dashboard-section-row">
        <h2>Workspace overview</h2>
        <div className="date-dropdown">
          <button onClick={() => setDateMenu((v) => !v)}>
            <Clock3 size={12} />
            {period === '1' ? 'Last 24 hours' : `Last ${period} days`}
            <ChevronDown size={12} />
          </button>
          {dateMenu && (
            <div className="date-dropdown-menu card">
              {[
                ['1', 'Last 24 hours'],
                ['7', 'Last 7 days'],
                ['30', 'Last 30 days'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => {
                    setPeriod(value);
                    setDateMenu(false);
                  }}
                >
                  {label}
                  {period === value && <Check size={12} />}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="metrics-grid" aria-busy={isPending}>
        <MetricCard
          icon={Workflow}
          label="Total workflows"
          value={String(metrics.totalWorkflows).padStart(2, '0')}
          detail={`${metrics.activeWorkflows} active workflows`}
          values={workflowTrend}
          color="#9998ed"
        />
        <MetricCard
          icon={Activity}
          label="Total executions"
          value={metrics.totalExecutions.toLocaleString()}
          detail="Across your workspace"
          values={activityTrend}
          color="#7eacdf"
        />
        <MetricCard
          icon={CheckCircle2}
          label="Success rate"
          value={`${metrics.successRate.toFixed(1)}%`}
          detail="of completed runs"
          values={successTrend}
          color="#76b49a"
        />
        <MetricCard
          icon={Clock3}
          label="Avg. execution time"
          value={formatDuration(Math.round(metrics.averageDuration))}
          detail="Completed executions"
          values={durationsTrend}
          color="#d2b17b"
        />
      </div>
      <div className="analytics-grid">
        <section className="card activity-card">
          <div className="analytics-card-heading">
            <div>
              <h2>Execution activity</h2>
              <p>A little progress, every day.</p>
            </div>
            <div className="period-toggle" aria-label="Chart period">
              {[
                ['1', '24h'],
                ['7', '7 days'],
                ['30', '30 days'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setPeriod(value)}
                  aria-pressed={period === value}
                  className={period === value ? 'active' : ''}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          <div className="chart-legend">
            <span>
              <i style={{ background: '#8589ef' }} />
              Successful
            </span>
            <span>
              <i style={{ background: '#f194a1' }} />
              Failed
            </span>
          </div>
          <div className="activity-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData} margin={{ top: 15, right: 10, bottom: 0, left: -27 }}>
                <defs>
                  <linearGradient id="successArea" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#9395f6" stopOpacity={0.25} />
                    <stop offset="100%" stopColor="#9395f6" stopOpacity={0.015} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="var(--chart-grid)" vertical={false} strokeDasharray="3 3" />
                <XAxis
                  dataKey="label"
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 9, fill: 'var(--muted)' }}
                  minTickGap={25}
                  dy={8}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 9, fill: 'var(--muted)' }}
                />
                <Tooltip
                  contentStyle={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 8,
                    fontSize: 11,
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="success"
                  name="Successful"
                  stroke="#8589ef"
                  strokeWidth={2.3}
                  fill="url(#successArea)"
                />
                <Area
                  type="monotone"
                  dataKey="failed"
                  name="Failed"
                  stroke="#eda2aa"
                  strokeWidth={1.5}
                  fill="transparent"
                  strokeDasharray="4 4"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-caption">
            <span>
              <span className="health-dot" />
              All execution counts reflect your demo history
            </span>
            <Link to="/executions">
              View analytics <ArrowUpRight size={12} />
            </Link>
          </div>
        </section>
        <section className="card status-card">
          <div className="analytics-card-heading">
            <div>
              <h2>Execution breakdown</h2>
              <p>Every outcome, accounted for.</p>
            </div>
            <Activity size={15} className="muted" />
          </div>
          <div className="donut-container">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={breakdown}
                  dataKey="value"
                  innerRadius={67}
                  outerRadius={83}
                  paddingAngle={3}
                  stroke="none"
                  startAngle={90}
                  endAngle={-270}
                  cornerRadius={3}
                >
                  {breakdown.map((item) => (
                    <Cell key={item.name} fill={item.color} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div className="donut-center">
              <strong>
                {successfulPercent}
                <span>%</span>
              </strong>
              <small>successful runs</small>
            </div>
          </div>
          <div className="status-breakdown-list">
            {breakdown.map((item) => (
              <button
                key={item.name}
                onClick={() =>
                  navigate(
                    `/executions?status=${item.name === 'Successful' ? 'succeeded' : item.name === 'Awaiting approval' ? 'waiting_approval' : item.name.toLowerCase()}`,
                  )
                }
              >
                <span>
                  <i style={{ background: item.color }} />
                  {item.name}
                </span>
                <strong>
                  {item.value}
                  <small>{Math.round((item.value / metrics.totalExecutions) * 100)}%</small>
                </strong>
              </button>
            ))}
          </div>
        </section>
      </div>
      <section className="card recent-executions">
        <div className="section-heading">
          <div className="recent-title">
            <h2>Recent executions</h2>
            <span className="live-label">
              <span />
              Live demo history
            </span>
          </div>
          <Link className="small-link" to="/executions">
            View all executions <ArrowRight size={13} />
          </Link>
        </div>
        {recent.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Workflow</th>
                  <th>Execution ID</th>
                  <th>Status</th>
                  <th>Started</th>
                  <th>Duration</th>
                  <th aria-label="View execution" />
                </tr>
              </thead>
              <tbody>
                {recent.map((execution, index) => {
                  const workflow = workflows.find((w) => w.id === execution.workflowId);
                  const Icon = workflowIcons[workflow?.icon || ''] || Workflow;
                  return (
                    <tr key={execution.id}>
                      <td>
                        <Link className="recent-workflow" to={`/executions/${execution.id}`}>
                          <span className={`workflow-symbol ${workflowColors[index % 4]}`}>
                            <Icon size={15} />
                          </span>
                          <span>{execution.workflowName}</span>
                        </Link>
                      </td>
                      <td>
                        <code className="execution-id">{execution.id}</code>
                      </td>
                      <td>
                        <Badge status={execution.status} />
                      </td>
                      <td className="muted">{relativeTime(execution.startedAt)}</td>
                      <td className="duration-cell">{formatDuration(execution.duration)}</td>
                      <td>
                        <Link
                          className="icon-button"
                          to={`/executions/${execution.id}`}
                          aria-label={`Inspect ${execution.workflowName}`}
                        >
                          <ArrowUpRight size={15} />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="Your automation journey starts here."
            description="Create a workflow and run it to see every step come to life."
            action={
              <Button variant="primary" onClick={() => navigate('/workflows/new')}>
                Create your first workflow
              </Button>
            }
          />
        )}
      </section>
      <div className="dashboard-section-row quick-heading">
        <h2>A good place to start</h2>
        <span>Less busywork. More possibilities.</span>
      </div>
      <div className="quick-actions">
        <button className="card quick-card" onClick={() => navigate('/workflows/new')}>
          <span className="quick-icon violet">
            <Sparkles size={19} />
          </span>
          <div>
            <strong>Build with AI</strong>
            <p>An idea is all you need.</p>
          </div>
          <ArrowUpRight size={16} />
        </button>
        <button
          className="card quick-card"
          onClick={() => {
            const workflow = createBlankWorkflow();
            useAppStore.getState().saveWorkflow(workflow);
            navigate(`/workflows/${workflow.id}/edit`);
          }}
        >
          <span className="quick-icon blue">
            <GitBranch size={19} />
          </span>
          <div>
            <strong>Start from scratch</strong>
            <p>Your canvas. Your way.</p>
          </div>
          <ArrowUpRight size={16} />
        </button>
        <button className="card quick-card" onClick={() => navigate('/integrations')}>
          <span className="quick-icon teal">
            <Zap size={19} />
          </span>
          <div>
            <strong>Connect your tools</strong>
            <p>Bring it all together.</p>
          </div>
          <ArrowUpRight size={16} />
        </button>
        <button className="card quick-card" onClick={() => navigate('/executions?status=failed')}>
          <span className="quick-icon amber">
            <ArrowDownRight size={19} />
          </span>
          <div>
            <strong>Review failed runs</strong>
            <p>{metrics.failed} executions to inspect.</p>
          </div>
          <ArrowUpRight size={16} />
        </button>
      </div>
      {pending > 0 && (
        <div className="approval-nudge">
          <ShieldCheck size={14} />
          <span>
            {pending} workflow {pending === 1 ? 'is' : 'are'} waiting for your decision.
          </span>
          <Link to="/approvals">
            Review approvals <ArrowRight size={12} />
          </Link>
        </div>
      )}
    </div>
  );
}
