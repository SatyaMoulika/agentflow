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
