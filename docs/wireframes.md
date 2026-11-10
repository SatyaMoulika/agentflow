# Low-fidelity wireframes

These wireframes establish information hierarchy and navigation. The implemented interface applies the shared tokens and responsive rules described in `design-system.md`.

## Global shell

```text
┌──────────────────────┬────────────────────────────────────────────────────┐
│ agentflow.           │ Workspace / Page      Search  Theme  Bell  Account │
│ My workspace         ├────────────────────────────────────────────────────┤
│                      │ Title / description                 Primary action│
│ Overview             │                                                    │
│ Workflows            │                                                    │
│ Executions           │                  PAGE CONTENT                      │
│ Integrations         │                                                    │
│ Approvals [count]    │                                                    │
│                      │                                                    │
│ Create with AI       │                                                    │
│ Help / Settings      ├────────────────────────────────────────────────────┤
│ User / Collapse      │ Prototype version                                  │
└──────────────────────┴────────────────────────────────────────────────────┘
```

Tablet: icon sidebar. Mobile: menu button opens a navigation drawer; cards stack and tables scroll horizontally.

## Login

```text
┌───────────────────────────────┬────────────────────────────────┐
│ Brand                         │ Welcome                        │
│                               │ Demo sign-in explanation       │
│ Design intelligent workflows. │ Email                          │
│ Observe every decision.       │ Demo password                  │
│                               │ Remember email / Help          │
│ Trigger → AI → Human approval │ [Sign in]                      │
│                               │ [Continue with demo workspace] │
│ Product statement             │ Prototype / password note      │
└───────────────────────────────┴────────────────────────────────┘
```

Mobile: the decorative story panel is hidden and sign-in fills the available width.

## Dashboard

```text
Welcome back                                             [+ Create workflow]
┌──────────────────────────────────────────────────────────────────────────┐
│ Describe → Build → Automate                 Connected workflow illustration│
│ [Build with AI]                                                         │
└──────────────────────────────────────────────────────────────────────────┘
Workspace overview                                            [Date range]
┌─────────────────┬─────────────────┬─────────────────┬────────────────────┐
│ Workflows       │ Executions      │ Success rate    │ Average duration   │
└─────────────────┴─────────────────┴─────────────────┴────────────────────┘
┌───────────────────────────────────────────┬──────────────────────────────┐
│ Execution activity             [24h/7/30] │ Outcome donut                │
│ Success + failure area chart              │ Counts + status links        │
└───────────────────────────────────────────┴──────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────────┐
│ Recent executions                                        [View all]      │
│ Workflow · ID · Status · Started · Duration · Inspect                     │
└──────────────────────────────────────────────────────────────────────────┘
[Build with AI] [Blank canvas] [Integrations] [Failed runs]
```

## Workflows and creation

```text
Workflows                               [Generate with AI] [Create workflow]
[Search]                     [Status] [Sort] [Grid/List]
┌─────────────────────┬─────────────────────┬─────────────────────────────┐
│ Icon / Status / Menu│ Icon / Status / Menu│ Icon / Status / Menu        │
│ Name + description │ Name + description │ Name + description          │
│ Nodes / Last run   │ Nodes / Last run   │ Nodes / Last run            │
│ Updated / Success  │ Updated / Success  │ Updated / Success           │
│ [Open editor] [Run]│ [Open editor] [Run]│ [Open editor] [Run]          │
└─────────────────────┴─────────────────────┴─────────────────────────────┘

Create workflow
┌────────────────────────────────────────────┬─────────────────────────────┐
│ What would you like to automate?           │ Start from scratch          │
│ [Natural-language prompt]                 │ [Build from scratch]        │
│                         [Generate]         │ Prompt writing guidance     │
├────────────────────────────────────────────┤                             │
│ Suggested goals / Generation progress     │                             │
│ Preview: title, steps, actual branches    │                             │
│ Integrations / configuration notes        │                             │
│ [Edit] [Regenerate] [Create workflow]      │                             │
└────────────────────────────────────────────┴─────────────────────────────┘
```

## Workflow editor

```text
← Workflow name · Status · Version · Dirty        Undo Redo Validate Save Run
┌───────────────────┬─────────────────────────────────┬─────────────────────┐
│ NODE LIBRARY      │               Auto-layout       │ NODE CONFIGURATION  │
│ Search           │                                 │ Name / description  │
│ Triggers         │ Trigger → Extract → Condition   │ Type-specific fields│
│ AI               │                    ↙      ↘     │ Input/output config │
│ Logic            │               Approval → Store  │ Retry / timeout     │
│ Tools            │                                 │ Validation feedback │
│ Human            │ Zoom / Fit    Minimap           │                     │
├───────────────────┴─────────────────────────────────┴─────────────────────┤
│ Mock copilot: [Describe a change] [Propose]                                │
│ Proposed changes: description             Reject / Regenerate / Apply     │
└───────────────────────────────────────────────────────────────────────────┘
```

Tablet/mobile: collapsible node library and configuration drawer. Desktop retains three panels. Unsaved navigation opens a confirmation dialog.

## Execution history and monitor

```text
Executions                                                    [Export CSV]
[Total] [Success] [Duration] [In progress]
[Search] [Workflow] [Status] [Date] [Sort]
┌──────────────────────────────────────────────────────────────────────────┐
│ Workflow / ID · Status · Trigger · Started · Duration · Inspect / Retry  │
│ ...                                                                      │
│ Count                                                   Previous / Next │
└──────────────────────────────────────────────────────────────────────────┘

← Executions        Workflow / ID / Version / Status     Open workflow Cancel
[Duration] [Completed] [Tokens] [Trigger] [Trace ID]
[Awaiting approval → Review request]  (only while paused)
┌────────────────────────────────────────────┬─────────────────────────────┐
│ Workflow / Timeline / Logs tabs           │ Selected node               │
│                                           │ Overview | Input | Output   │
│ Graph colored by actual node status       │ LLM | Trace | Logs          │
│                                           │ JSON / metadata / prompts   │
│ Zoom / Fit / Status legend                │ Search + severity + copy    │
└────────────────────────────────────────────┴─────────────────────────────┘
```

## Integrations

```text
Integrations                                         [Connected count]
[Simulation explanation]
[Search]
All · Communication · Productivity · Developer tools · Storage · AI
┌─────────────────────┬─────────────────────┬─────────────────────────────┐
│ Logo / Status      │ Logo / Status      │ Logo / Status               │
│ Name / Description│ Name / Description│ Name / Description          │
│ [Connect/Configure]│ [Connect/Configure]│ [Connect/Configure]          │
└─────────────────────┴─────────────────────┴─────────────────────────────┘
Modal: connection name → demo auth method → test → save / disconnect
```

## Approvals

```text
Approvals                                              [Pending count]
Pending · Approved · Rejected · Expired · All                [Search]
┌──────────────────────────────────┬───────────────────────────────────────┐
│ Request / Workflow / Timestamp   │ Request / Workflow / Timestamp        │
│ Input summary / Risk            │ Input summary / Risk                  │
│ [Details] [Review]               │ [Details] [Review]                    │
└──────────────────────────────────┴───────────────────────────────────────┘

Request details
┌────────────────────────────────────────────┬─────────────────────────────┐
│ Request context / Execution link          │ Consequences of each choice │
│ Input JSON                                │ [Approve] [Reject]          │
│ Completed preceding steps                 │ Local simulation note       │
└────────────────────────────────────────────┴─────────────────────────────┘
Confirmation dialog: decision consequence + optional note + explicit confirm
```

## Settings

```text
Settings
┌─────────────────────┬───────────────────────────────────────────────────┐
│ Profile             │ Section title / description                       │
│ Appearance          │                                                   │
│ Agent configuration│ Validated fields or theme selection               │
│ Execution           │ Local preference explanations                     │
│ Observability       │                                                   │
│ Notifications       │ Unsaved state                   Discard / Save    │
└─────────────────────┴───────────────────────────────────────────────────┘
```
