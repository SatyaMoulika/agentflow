# Porcelain & Violet interface

AgentFlow's active API-backed React interface now uses a violet variation of the shared [ai-portfolio design system](https://github.com/SatyaMoulika/ai-portfolio/blob/main/src/design-system/tokens.ts): white porcelain surfaces, ink `#243447`, secondary text `#52677C`, violet `#7957BD`, Manrope typography and a restrained Lora accent on the sign-in heading. Pale lavender surfaces adapt the shared blue-tinted surface treatment for this project. Existing light/dark/system appearance settings remain supported; the dark palette uses corresponding lavender accents rather than forcing a light theme.

The change covers authentication, sidebar/header, overview, workflow cards, fields, tables, buttons, focus rings and the workflow canvas. `FlowIllustration` adapts the shared branching-agent motif into a static input/route/tools/output drawing on sign-in and the overview. It is decorative, not a live workflow or execution status. There is no motion toggle or pause-motion button, and no new looping decorative animation. Existing reduced-motion support remains in place.

No backend, authentication/session logic, API client, workflow definitions, execution handlers, integration configuration, business JSON keys or persisted data change. Existing loading/error/empty states and unavailable-capability notices remain. No fixtures or simulated executions are imported into active accounts, and no design-system dependency is added. Fonts retain system fallbacks when Google Fonts is unavailable.

## Verification

- All 156 frontend tests pass.
- `npm run lint` and `npm run build` pass.
- Headless Chromium checks exercised sign-in, overview, workflow list and the editor using browser-intercepted API fixtures. The fixture responses are used only by the external check script, not application code. No real account, database, broker or provider was contacted/mutated by those UI checks.
- Desktop, 320/390px authentication layouts, 390px overview/navigation and dark appearance were inspected. The editor retains its existing graph behaviour; appearance tokens are scoped to React Flow. Tables keep their internal horizontal scroll on small screens.
- Backend/integration suites were not run because no backend or protocol behaviour was changed.

Pull the merged branch and use the existing frontend setup (`npm ci`, then `npm run dev`) to see the theme. No migration, re-index, environment change or new credential is required.

## Guided workflow journey

The create screen starts with an explicit choice: an opt-in starter draft, a Groq-generated proposal, or a blank manual workflow. Starter drafts are created only after the user clicks Create; they are not account fixtures and do not execute automatically. The calculator starter needs no external provider. GitHub briefing requires a currently active, eligible repository issues/pulls connection selected from the owner's paginated connections; execution uses the existing bounded Tool Agent and Groq, with read-only and partial-collection disclosures.

The editor shows a journey indicator and a setup checklist. Common model/parser nodes expose instruction and input-key fields, with full JSON available for additional settings. Basic edits preserve other configuration keys. Workflow input metadata remains frontend guidance, not a backend-enforced input schema.

Both run entry points request server graph validation before submitting an execution, retaining the existing idempotency-key behavior. This check makes no provider call and does not prove provider availability, connection authorization or output quality; runtime checks remain authoritative. There is no new test mode, scheduler, webhook, write connector or approval mechanism. Existing agent tool checkpoints remain available.

The Integrations screen uses compact, two-column setup cards above a separate “Manage & revoke connections” section for HTTP/GitHub revocation and Gmail disconnection. Cards stack below 800px; the existing owner-scoped API calls, pagination and cache invalidation are retained.

## Execution results

Execution details now places the final result above the graph and event history. Stored model responses retain Markdown rendering with raw output available on demand. Structured results show exact field names and scalar values; nested values and complete JSON remain expandable. Only succeeded executions present output as a completed result.

Failures provide guidance for the backend's existing failure codes, identify the latest failed attempt for each step and link to its expanded details. Earlier failures superseded by a successful attempt are not shown as current failures. Paused agent steps open automatically so continuation is visible. Input and stored output remain available in an expandable section, and existing provider-call, checkpoint, cancellation and retry safeguards remain in place. Gmail reads now also suppress the unsupported full-workflow retry action.
