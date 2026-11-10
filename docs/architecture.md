# UI architecture

Phase 5D complete, 4 November 2026: command receipts, bounded pure retries, whole-workflow retry lineage and cooperative cancellation are implemented and wired to the frontend. API 18 operations/15 paths; migration head 0004. Backend 905 tests, frontend 120 tests pass. Next is Phase 6 background dispatch/recovery. See [execution command notes](learning-notes/execution-commands.md). Earlier snapshots below describe their historical increments.

Current status, 4 November 2026: initial frontend API integration was brought forward after backend Phase 5C. The active App uses src/api for real authentication, owned workflow editing/validation and execution history; earlier prototype modules described below remain unrouted reference code. GET /runs is implemented (16 operations/13 paths); migration head remains 0003. Backend 5D is next. See [frontend API notes](learning-notes/frontend-api.md) and the [startup walkthrough](real-backend-walkthrough.md). Browser visual QA remains outstanding.

## Modules and ownership

```text
src/
  main.tsx                    React entry point and global styles
  App.tsx                     Providers, lazy routes, mock auth guard, error boundary
  layouts/                    Persistent sidebar, header, search and notifications
  pages/                      Dashboard, editor, history, inspectors and management
  components/ui/              Shared accessible controls and feedback
  components/workflow/        Canvas node cards and node configuration forms
  types/                      Normalized workflow, execution, approval and settings types
  lib/node-registry.ts        Stable node IDs, metadata, defaults and schemas
  lib/graph.ts                Graph validation, connection guards and layout
  services/generation.ts      Deterministic generation boundary and blank workflow factory
  services/execution-engine.ts Simulation and event adapter
  services/api.ts             Typed dashboard adapter and pure metric calculation
  stores/useAppStore.ts       Workspace commands and persisted client state
  data/fixtures.ts            Central, internally linked demo workspace
```

Pages orchestrate presentation and store actions. Graph validation, generation, metrics, and simulation remain separate from JSX. Node definitions are shared by the library, editor, and monitor. Execution records retain a graph snapshot so later workflow edits do not alter historical runs.

## Providers and routes

`App` installs TanStack Query, a data router, reduced-motion configuration, and an error boundary. Routes are lazy loaded. Canvas and chart libraries receive separate production chunks. The root layout applies theme preferences and resumes in-progress simulations. The protected shell redirects signed-out users to `/login`; this guard is explicitly a demonstration.

| Route                         | Experience                                             |
| ----------------------------- | ------------------------------------------------------ |
| `/`                           | Redirect to dashboard after mock sign-in               |
| `/login`                      | Demo sign-in or one-click workspace access             |
| `/dashboard`                  | Metrics, analytics, recent runs and creation shortcuts |
| `/workflows`                  | Cards/list, search and management                      |
| `/workflows/new`              | Prompt, generation progress, preview, blank creation   |
| `/workflows/:workflowId`      | Workflow editor                                        |
| `/workflows/:workflowId/edit` | Workflow editor                                        |
| `/executions`                 | Filterable/paginated history and CSV export            |
| `/executions/:executionId`    | Simulation, read-only graph and inspector              |
| `/integrations`               | Simulated service connections                          |
| `/approvals`                  | Review queue and historical decisions                  |
| `/approvals/:approvalId`      | Context, consequences and confirmed decision           |
| `/settings`                   | Local workspace preferences                            |

Unknown and missing records have recoverable empty/error views. The editor uses data-router navigation blocking for links, programmatic navigation, and browser back/forward, plus `beforeunload` for refresh/close. A run saves its draft before navigating.

## State and persistence

Zustand owns workflows, execution records, approvals, settings, and demo connections. Its persisted subset excludes transient toast messages and passwords. The editor owns a separate draft, undo/redo history, selection, and saved fingerprint until Save commits the draft. Workflow statistics refresh from actual execution records whenever execution state changes.

TanStack Query owns asynchronous dashboard loading through the `AgentFlowApi` interface. Search, filters, tabs, and modal visibility remain component state. React Hook Form and Zod validate profile and demo sign-in inputs. Node configuration combines registry metadata with field/graph validation.

## Graph semantics

- One manual trigger starts a directed acyclic graph; triggers cannot receive inputs and End cannot have outputs.
- Each output handle connects to one next step. Conditions expose `true` / `false`; approval exposes `approved` / `rejected`.
- Nodes must be reachable and every branch must connect to its next step. Configuration errors prevent runs at both the editor and store entry point.
- The simulation follows chosen branches, forwards predecessor output as the next node's input, and marks untaken steps skipped.
- Approval pauses the simulation and creates a linked request. A confirmed decision records its note, resumes the worker, and follows the selected handle.
- A per-execution worker guard prevents duplicate workers. Cancellation is checked after asynchronous steps; cancelled runs cannot revive. Refresh rebuilds traversal from the graph, skips completed steps, and resumes incomplete work.
- Node processing durations are simulated compute time; approval wait time is excluded. Execution duration is the sum of its node durations.

The current graph supports sequential steps and exclusive branches. Merge brings a chosen branch back together; parallel execution, fan-out scheduling, loops, expression evaluation, and production retry orchestration are future backend responsibilities.

## FastAPI integration path

Keep the normalized TypeScript entities and stable registry identifiers (`manual`, `extract`, `condition`, `approval`, etc.) as the contract. Store actions are the UI command facade; substitute service implementations behind them so page structure and graph/inspector components remain intact.

1. Add a typed HTTP client and authoritative authentication/session handling.
2. Replace fixture listing and local save commands with workflow API operations. Preserve optimistic local state where useful; reconcile server IDs/version numbers and surface conflicts.
3. Replace `generateMockWorkflow` with an asynchronous generation endpoint returning the same workflow/preview metadata. Retain review-before-create and generation failure states.
4. Replace the simulator with a run endpoint and SSE/WebSocket subscription. Map backend node events into `Execution`, `NodeRun`, and `ExecutionEvent`; retain historical graph snapshots.
5. Send approvals to an authoritative decision endpoint with concurrency/version checks and hydrate the returned run state.
6. Fetch dashboard/history through TanStack Query rather than the local adapter. Add cursor-based pagination when the server data size requires it.
7. Move connections, secrets, retry policies, access controls, and redaction/retention enforcement to the backend. Never migrate keys to browser storage.

The frontend's validation is feedback, not authority. Backend validation, authorization, idempotency, race handling, and durable job execution are required before production use. Asynchronous server commands will require adapting action return handling while keeping the presentational components and domain model.
