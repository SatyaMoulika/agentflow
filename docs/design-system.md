# AgentFlow design system

## Foundations

The interface uses a quiet neutral workspace, indigo primary actions, compact typography, and category colors that help distinguish workflow operations. The dashboard's soft lilac introduction is the largest color surface; execution and editor views prioritize readable data.

Semantic tokens are defined in `src/index.css` and switched through `data-theme` on the root element.

| Token                 | Purpose                                  | Light default |
| --------------------- | ---------------------------------------- | ------------- |
| `--bg`                | Workspace background                     | `#f8fafc`     |
| `--surface`           | Cards, panels, dialogs                   | `#ffffff`     |
| `--surface-secondary` | Secondary controls and code surroundings | `#f1f5f9`     |
| `--text`              | Main text                                | `#172036`     |
| `--muted`             | Supporting text                          | `#738095`     |
| `--border`            | Panel and control borders                | `#e6eaf0`     |
| `--primary`           | Primary actions and active controls      | `#6366f1`     |
| `--primary-soft`      | Selected and supporting accent surfaces  | `#eef0ff`     |
| `--success`           | Successful state                         | `#16a34a`     |
| `--warning`           | Pending decision and warnings            | `#d97706`     |
| `--danger`            | Errors and destructive decisions         | `#dc2626`     |

Dark mode overrides the same tokens. Status badges use both text and color. Node category colors live in the shared registry: indigo triggers, violet AI, amber logic, blue tools, teal human review, slate endpoints.

Inter is the UI font and JetBrains Mono displays identifiers, JSON, logs, and code-like values. System fallbacks keep the interface usable if hosted fonts are unavailable. Titles are 24–28px, section headings 14–18px, primary page body 12–14px, and compact table/metadata 10–12px. Larger screen management forms use more spacious controls.

## Layout

- Expanded navigation is 226px; collapsed navigation is 75px.
- Header is 65px, reducing to 58px on mobile.
- Desktop content uses 32px horizontal padding; mobile uses 17px.
- Panels use 10–12px radii and subtle borders/shadows.
- Four dashboard metrics become two columns on mobile. Analytics and editor side panels reflow at smaller breakpoints.
- Tables scroll within their containers; long IDs and code remain inspectable.

## Shared primitives

`src/components/ui/index.tsx` contains:

- `Button`: primary, secondary, ghost, danger; small/default sizes; disabled/loading states; Radix Slot composition.
- `Badge`: consistent status text, colored surfaces, and dot indicators.
- `PageHeader`, `EmptyState`, `ErrorState`, and `LoadingSkeleton`.
- `Modal` and `ConfirmDialog`: Radix Dialog provides focus management, Escape handling, accessible titles, and modal layering.
- `SearchInput`, `JsonViewer` with copy, `UserAvatar`, and accessible live-region `Toasts`.

These follow shadcn's local component ownership pattern: Radix primitives, class-variance-authority, and merged utility classes. There is no remote component runtime. `components.json` records the source conventions.

Business components stay within their pages or `components/workflow`: node cards/configuration, trace timeline, log viewer, approval cards, and integration cards. They consume the same semantic tokens and status vocabulary.

## Interaction rules

1. Every primary action produces a local state change, navigates, opens a review step, or clearly explains a prototype limitation.
2. Unsaved editor changes remain local until saved; navigation and refresh warn before discarding.
3. AI edits require review and Apply. A fingerprint prevents stale proposals from overwriting newer edits.
4. Approval and rejection require explicit confirmation and allow a decision note.
5. Connections reject cycles, invalid handles, duplicate destinations, and trigger inputs immediately; full validation gives node-level messages.
6. Loading, empty searches, missing records, validation errors, failures, successful saves, and unavailable output have readable states.
7. Simulations and demo integrations are identified in the UI. Provider identifiers and preferences are configuration data, not live capability claims.

## Accessibility and motion

Native buttons/inputs/labels, focus-visible outlines, accessible dialog titles, ARIA descriptions for icon controls, semantic tables, selected tab state, toast live regions, keyboard shortcuts, and status text support keyboard and assistive-technology use. The mobile drawer handles Escape and traps Tab while open. Running states use small status indicators.

Transitions are brief (generally 150–250ms). CSS disables animation and transition when reduced motion is requested; MotionConfig also respects that preference. The workflow graph has labeled node controls and a keyboard-visible node inspector, although complex canvas editing remains most useful on a desktop.
