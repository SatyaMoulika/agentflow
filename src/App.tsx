import { Component, useEffect, type ReactNode } from 'react';
import {
  createBrowserRouter,
  createRoutesFromElements,
  Navigate,
  Outlet,
  Route,
  RouterProvider,
  useLocation,
} from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Button, EmptyState } from './components/ui';
import { client } from './api/client';
import { useSession } from './api/session';
import { Pending } from './api/common';
import Shell from './api/Shell';
import AuthPage from './api/AuthPage';
import {
  Dashboard,
  WorkflowList,
  CreateWorkflow,
  RunList,
  RunView,
  Account,
  Integrations,
  Unavailable,
} from './api/pages';
import Editor from './api/Editor';
import RunWorkflow, { RunWorkflowList } from './api/RunWorkflow';
import { GmailCallback } from './api/GmailConnections';
import './api/workspace.css';
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 10000, retry: false, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
});
function Root() {
  const session = useSession();
  const location = useLocation();
  useEffect(() => {
    void client.initialize();
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => {
      let preference = 'system';
      try {
        preference = localStorage.getItem('agentflow-ui-theme') || 'system';
      } catch {
        /* Browser preferences are optional. */
      }
      document.documentElement.dataset.theme =
        preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
    };
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    queryClient.removeQueries({
      predicate: (query) =>
        query.queryKey[0] !== session.user?.id || query.queryKey[1] !== session.generation,
    });
  }, [session.user?.id, session.generation]);
  useEffect(() => {
    document.title = `AgentFlow · ${location.pathname.includes('executions') ? 'Executions' : 'Workspace'}`;
  }, [location.pathname]);
  return <Outlet />;
}
function Guard() {
  const session = useSession();
  const location = useLocation();
  return session.status === 'loading' ? (
    <Pending />
  ) : session.status === 'authenticated' ? (
    <Outlet />
  ) : (
    <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  );
}
class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <EmptyState
        title="This view could not be displayed"
        description="Your saved data remains on the server. Reload to reconnect."
        action={<Button onClick={() => window.location.reload()}>Reload</Button>}
      />
    ) : (
      this.props.children
    );
  }
}
const router = createBrowserRouter(
  createRoutesFromElements(
    <Route element={<Root />}>
      <Route path="/login" element={<AuthPage key="login" />} />
      <Route path="/register" element={<AuthPage key="register" registration />} />
      <Route element={<Guard />}>
        <Route element={<Shell />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="workflows" element={<WorkflowList />} />
          <Route path="workflows/new" element={<CreateWorkflow />} />
          <Route path="workflows/:workflowId" element={<Editor />} />
          <Route path="workflows/:workflowId/edit" element={<Editor />} />
          <Route path="workflows/:workflowId/run" element={<RunWorkflow />} />
          <Route path="run" element={<RunWorkflowList />} />
          <Route path="executions" element={<RunList />} />
          <Route path="executions/:executionId" element={<RunView />} />
          <Route path="settings" element={<Account />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="integrations/gmail/callback" element={<GmailCallback />} />
          <Route path="approvals/*" element={<Unavailable kind="Approvals" />} />
          <Route
            path="*"
            element={
              <EmptyState
                title="Page not found"
                description="Choose a workspace page from the navigation."
              />
            }
          />
        </Route>
      </Route>
    </Route>,
  ),
);
export default function App() {
  return (
    <Boundary>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </Boundary>
  );
}
