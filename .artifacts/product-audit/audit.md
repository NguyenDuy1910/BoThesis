# BoThesis product UI audit

Reviewed: chat workspace, navigation, auth states, administration routes, datasource/document routes, workflow states, shared form/table/dialog primitives, responsive behavior, and light/dark themes.

## Design direction

“Governed clarity”: deep navy for primary interaction, restrained teal for trust and status, neutral slate surfaces, compact Hanken Grotesk typography, DM Mono for operational metadata, and a thin evidence/status rail as the recurring product signature.

The redesign preserves the conversation-first shell, semantic answer/citation model, existing route structure, backend contracts, and local conversation behavior. It removes fake or non-functional controls, the unrelated image logo, nested placeholder cards, and unavailable conversation actions.

## Journey health

| Step | Product journey | Health after redesign |
| --- | --- | --- |
| 1 | Enter through sign-in or registration | Healthy UI; identity capability is honestly marked unavailable and no credentials are collected. |
| 2 | Start or resume a knowledge conversation | Healthy; direct hierarchy, compact prompts, permission/evidence expectations, responsive composer. |
| 3 | Inspect assistant progress and evidence | Healthy; existing semantic activity and citations are preserved with quieter hierarchy. |
| 4 | Move between chat, workflows, and administration | Healthy; direct destinations replace hidden and disabled navigation. |
| 5 | Discover administration areas | Healthy UI; route-specific states explain the missing backend contract. |
| 6 | Configure datasources, documents, access, or audit controls | Backend blocked; no fake lifecycle metrics, records, or actions were introduced. |
| 7 | Author or execute workflows | Backend blocked; the visible route now explains authoring and execution dependencies. |

## System changes

- Unified light/dark semantic tokens, typography, spacing, focus, hover, pressed, disabled, semantic, and loading states.
- Refined Button, IconButton, Badge, Input, Textarea, Select, Dropdown, Dialog, Tabs, DataTable, Pagination, Toast, Empty/Error/Loading states, headers, skeletons, and resizing behavior.
- Added reusable `ProductMark` and `UnavailableState` primitives.
- Added keyboard sorting/resizing/row activation, dialog focus trapping, tab arrow navigation, mixed checkbox state, live alerts, skip navigation, reduced motion, safe-area handling, and mobile overlay behavior.
- Removed disabled Projects/Plugins navigation, the More indirection, unavailable Share/Pin/Archive actions, and the non-functional credential form.

## Evidence

- Before captures: `before/`
- After captures: `after/`
- Side-by-side visual review: `comparisons/contact-sheet.png`
- Verified at desktop 1440×1000 and mobile 390×844, including intentionally designed dark states.

## Verification

- TypeScript: pass
- Existing frontend tests: 34/34 pass
- Production build: pass
- Playwright interaction smoke: 4/4 pass (mobile chat navigation, mobile admin navigation, theme cycling, auth return path)
- Final Vercel Web Interface Guidelines static review: no remaining `transition-all`, blocked paste, non-semantic click container, missing image dimensions, or three-dot ellipsis findings in `web/src`.
