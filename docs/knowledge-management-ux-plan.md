# BoThesis Knowledge Management UX/UI Implementation Plan

## Scope and product boundary

This plan improves the existing Next.js administration experience at `/admin/*`, centered on enterprise Knowledge Base management. It preserves the current API boundary in `web/src/modules/admin/api.ts`, the tenant/user request headers, connector adapter isolation, collection-level access enforcement, ingestion behavior, source lineage, audit events, and soft-delete lifecycle behavior.

In the current domain model, a **Knowledge Base** is a root `Item` with `item_type=collection`. Connector connections authenticate a provider, plugin bindings attach an external content scope to a Knowledge Base, schedules belong to bindings, sync runs describe ingestion activity, documents are child `Item` records, and collection access grants govern the visible subtree. The UI should use the product term “Knowledge Base” while retaining those backend concepts and contracts.

## Current audit: concrete issues to resolve

| Priority | Current issue | Product impact | Implementation response |
| --- | --- | --- | --- |
| P0 | Navigation exposes backend nouns (`Ingestion`, `Items`, `Spaces`) but no first-class Knowledge Base destination. | Admins cannot see the main governed-knowledge object or understand how connections, content, access, and sync relate. | Reframe navigation around Knowledge Bases, Sources, Documents, Access, Activity, and Settings while keeping current routes valid. |
| P0 | Connector setup creates connection instances, but Knowledge Base selection, content scope, access choice, schedule, and review are not one coherent workflow. | A connected provider does not produce a clear path to safe, searchable content. | Add a five-step KB setup wizard and a persistent live summary; use existing connection, binding, item, access, and schedule contracts where available. |
| P0 | The collection model and collection-access APIs exist, but the admin frontend does not present collections as manageable Knowledge Bases. | Permissions, lineage, readiness, and document scope are fragmented or invisible. | Add KB list and overview surfaces that combine collection, binding, sync, document, and access evidence. |
| P0 | Readiness is inferred from separate item and sync statuses. | Users may assume content is chat-ready before indexing and ACL filtering complete. | Show an explicit lifecycle and only label content “Available to chat” when indexing and access prerequisites are satisfied. |
| P1 | Sources, bindings, schedules, and sync runs are shown in separate technical views with limited cross-linking. | Recovery from partial failures requires mental joins across pages. | Add source lineage, active scope, schedule, latest run, affected-document count, retry, and review links in KB context. |
| P1 | Current setup copy is connector-centric and primarily shaped around Confluence/file upload. | Other provider cards imply availability without a consistent setup state model. | Keep real backend capability checks; use shared setup stages and explicitly mark unsupported providers as unavailable instead of faking a workflow. |
| P1 | Access configuration is split across Roles, ACL Policies, Access Requests, Users, and Groups. | Admins cannot easily distinguish platform capability from KB audience. | Introduce a Knowledge Base access surface for mirror-source versus custom audience, then link to organization-wide roles and requests. |
| P1 | “Delete” UI language obscures the existing soft-delete/tombstone behavior. | The action sounds irreversible and under-explains lineage retention. | Use “Remove” for knowledge content and state that indexed records remain governed by lifecycle policy. Preserve backend delete endpoints and tombstones. |
| P2 | The current palette uses teal as the active accent and some components use oversized 16px radii and pill filters. | The administration experience is visually inconsistent with the requested premium enterprise direction. | Move the shared light theme to cobalt, use the cool-gray sidebar, 8–10px controls/cards, low-shadow surfaces, and compact segmented/tab patterns. Keep semantic green only for success. |
| P2 | Some dense controls and icon buttons are 32–36px tall. | Narrow pointer targets increase touch and tablet friction. | Make primary workflow controls at least 40px and compact icon controls at least 36px, with 44px targets on coarse pointers. |
| P2 | Responsive behavior mostly collapses navigation but does not adapt multi-pane KB setup or dense tables. | Tablet users get horizontal density instead of task-focused reflow. | Collapse the live summary below the step content, stack toolbars, preserve table scroll, and switch document rows to essential columns at narrower breakpoints. |

### Patterns to consolidate

- Use `Button`, `Badge`, `Card`, `DataTable`, `PageHeader`, `FormField`, `Sheet`, `Tabs`, `EmptyState`, `ErrorState`, `LoadingState`, and `Skeleton` rather than new local equivalents.
- Move primary, focus, selected, sidebar, border, processing, warning, and error colors into the single token source in `globals.css`.
- Use one status mapping for connection, lifecycle, document, and sync badges; never use green for selection or primary actions.
- Use one compact page frame and one toolbar pattern across Knowledge Bases, Sources, Documents, Access, and Activity.
- Use Lucide icons already in the repository and connector logos from `ConnectorLogo`; do not create imitation brand marks.

## Information architecture

### Primary administration navigation

1. **Overview** — tenant health, search readiness, attention items, recent activity.
2. **Knowledge**
   - **Knowledge Bases** — governed collections, readiness, source, document count, audience, latest sync.
   - **Sources & Integrations** — connector gallery and authenticated connection instances.
   - **Documents** — browse all governed documents with KB, source lineage, processing, and access status.
   - **Sync Activity** — scheduled/manual runs, progress, partial failures, and retry.
3. **Access**
   - **People & Groups** — existing users and groups.
   - **Access Requests** — review and decision flow.
   - **Roles & Policies** — platform capabilities and low-level ACL policy inspection.
4. **System**
   - **Workspace Settings** — current tenant space profile.
   - **Audit Log** — append-only administration history.

Existing URLs remain addressable. New labels may point to current endpoints where the domain is equivalent; route aliases should be additive.

### Knowledge Base local navigation

- **Overview** — lifecycle, readiness, issue summary, lineage, access summary, schedule.
- **Documents** — searchable hierarchy/list, processing details, metadata, retry/remove.
- **Sources** — bound integrations, content scopes, test connection, last checkpoint.
- **Access** — permission model, effective audience, inherited/overridden visibility.
- **Sync** — schedule, run now, history, partial failures, retry.
- **Settings** — name, description/metadata, pause, lifecycle removal.

## Role matrix

| Capability | Tenant Admin | Knowledge Admin | Knowledge Editor | Member | Security Admin |
| --- | --- | --- | --- | --- | --- |
| View tenant overview and all KB health | Full | Full | Assigned KBs | Permitted KBs only | Security evidence only |
| Create and configure Knowledge Bases | Full | Full | No | No | No |
| Add/test/remove source connections | Full | Full | No | No | Review only |
| Select source scope and bind to KB | Full | Full | Assigned KBs if granted | No | Review only |
| Upload and manage local documents | Full | Full | Assigned KBs | No | Review only |
| Re-index/retry document processing | Full | Full | Assigned KBs | No | Review only |
| Configure sync schedules / run now | Full | Full | Assigned KBs if granted | No | Review only |
| Choose mirror-source permissions | Full | Full | No | No | Approve/review |
| Define custom KB audience | Full | Full | No | No | Full |
| Manage users, groups, roles, access requests | Full | No | No | Request only | Full |
| View audit events | Full | KB-scoped | Own actions | No | Full |
| Use chat against ready content | Permitted | Permitted | Permitted | Permitted | Permitted |

The UI must hide or disable actions using effective server-provided permissions when those capabilities become available. Until then, current server enforcement remains authoritative and 403 responses use the permission-denied state; the frontend must not invent permissive fallbacks.

## Use-case flows

### 1. Connect an integration

1. Open **Sources & Integrations** and browse/search the connector gallery.
2. Select a provider card with one of: Connected, Setup required, Available, Disabled, or Unavailable.
3. Enter credential or OAuth details; secrets are sent through the existing credential boundary and never echoed.
4. Select or confirm the workspace/account when supported by the provider.
5. Run **Test connection**. Keep the form state on failure and show actionable recovery next to the failed stage.
6. Save the connection instance only after a valid result, or keep it as the existing draft/error state when the backend does so.
7. Offer **Create Knowledge Base** or **Add to existing Knowledge Base** as the next task.

### 2. Create a Knowledge Base

1. **Source** — choose an existing tested integration or connect a new one.
2. **Content scope** — search a hierarchical provider tree, select include/exclude nodes, and show selected and estimated counts.
3. **Access** — default to Mirror source permissions; alternatively choose Custom Knowledge Base audience.
4. **Sync** — manual, daily, or custom schedule; choose timezone and paused/enabled state.
5. **Review** — confirm name, source, scope, estimated documents, access enforcement, and schedule.
6. Create the collection, binding, access grants, and schedule through existing endpoints; then trigger the initial sync with `trigger_type=initial`.
7. Land on the KB overview with Connected → Discovering → Processing → Search-ready progress.

The live summary remains visible throughout desktop setup and moves below the active step on tablet.

### 3. Upload a local document

1. Start from a KB’s Documents tab or File Upload connector.
2. Confirm/select the target KB before choosing files.
3. Validate supported type and size before upload; identify rejected files individually.
4. Assign optional metadata and access inheritance/override before processing.
5. Show queued, uploading, uploaded, processing, searchable, and failed states per file.
6. On failure, preserve the file row and show retry/removal. On success, link to the document detail and its source lineage.

### 4. Configure permissions

1. Choose **Mirror source permissions** (default) or **Custom Knowledge Base audience**.
2. For mirrored access, explain which provider permissions are synchronized and that access is enforced before retrieval.
3. For custom access, search and assign users/groups with Viewer or Editor role.
4. Show inherited access on documents; allow an authorized security workflow to override visibility, with a clear warning and audit note.
5. Review the effective audience, denied principals, and unresolved mappings before saving.

### 5. Schedule and monitor sync

1. Choose Manual only, Daily, or Custom; custom maps to the existing cron/timezone contract.
2. Enable or pause the schedule without removing its history.
3. Use **Run now** to create a manual sync run; prevent duplicate submissions while a run is pending/running.
4. Show discovered, processed, written, removed, failed, duration, and trigger type in history.
5. For partial failure, keep successful documents available when safe, identify affected documents, and offer Review failures / Retry.

### 6. Operate content

1. Browse/search documents by KB, source, type, processing status, and update time.
2. Open a document to see hierarchy, metadata, source URL, origin/version, processing evidence, KB access, and chat readiness.
3. Re-index failed documents or start a source resync for upstream changes.
4. **Remove** creates the existing lifecycle tombstone; normal reads exclude it while lineage/audit evidence remains.
5. Provide bulk retry/removal only when server contracts support equivalent permission and audit guarantees.

### 7. Enforce chat readiness

1. A KB is exposed in chat selection only when it is active, has an effective permitted audience, and contains at least one ready/indexed document.
2. A document is retrievable only after its processing status is ready, vector indexing is complete, and ACL filtering has authorized the request.
3. Processing or failed content remains visible to authorized admins but is labelled unavailable to chat.
4. The chat connector selector continues to show only server-returned permitted connections/collections; no client-side fallback widens access.

## Screen inventory and component scope

| Screen | Primary job | Main reusable components | Contract source |
| --- | --- | --- | --- |
| Admin overview | See tenant knowledge health and urgent issues | `PageHeader`, evidence strip, `DataTable`, `Badge`, `EmptyState` | `/admin/overview` |
| Knowledge Base list | Find/create KBs and assess readiness | toolbar, segmented filters, `DataTable`, readiness badge | `/admin/items?item_type=collection` plus bindings/runs |
| Knowledge Base setup | Create a governed, synchronized collection | `Dialog`/`Sheet`, stepper, form fields, tree selector, live summary | items, connections, bindings, access, schedules, sync |
| Knowledge Base overview | Understand lifecycle, lineage, access, and chat readiness | lifecycle rail, progress, status summary, tabs, issue list | item detail, bindings, sync runs, collection access |
| Sources & Integrations | Discover and manage provider connections | connector gallery/card/logo/status, setup sheet | datasource capability and connection endpoints |
| Documents | Browse and operate governed content | toolbar, filters, `DataTable`, status, actions | `/admin/items?item_type=document` |
| Document detail | Inspect processing, lineage, access, metadata | detail sheet/page, definition lists, status history | `/admin/items/{id}` |
| Access | Set and inspect KB audience | access-model selector, user/group picker, effective-access list | collection access endpoints |
| Sync activity | Monitor/retry ingestion | progress, status filters, `DataTable`, error detail | ingestion job endpoints |
| Audit/settings | Review evidence and tenant settings | `DataTable`, filters, existing space editor | audit/space endpoints |

### New focused components

- `KnowledgeBasePage`: list/overview entry point using collection items.
- `KnowledgeBaseWizard`: five-step orchestration without duplicating form controls.
- `KnowledgeBaseSummary`: persistent source/scope/count/access/schedule review.
- `KnowledgeLifecycle`: Connected, Discovering, Processing, Search-ready state rail.
- `ContentScopeTree`: searchable hierarchical tri-state include/exclude selection.
- `AccessModelSelector`: mirror-source or custom-audience decision with enforcement copy.
- `SyncScheduleForm` and `SyncActivityList`: schedule configuration and run evidence.
- `ReadinessBadge`: distinct processing, warning, error, and ready semantics.

Shared DTOs should stay in `web/src/modules/knowledge-management/types.ts`; API composition belongs in its own module. Connector-specific fields remain within connector setup adapters.

## Required state coverage

| State | Required treatment |
| --- | --- |
| Empty | Explain what is absent, why it matters, and give one role-appropriate primary action. |
| Loading | Preserve page structure with skeletons; use `aria-busy` and avoid layout shift. |
| Processing | Show current lifecycle stage, processed/total count, percentage, and what remains unavailable. |
| Partial failure | Show successful versus affected counts, affected-document route, and scoped retry. |
| Permission denied | Explain that server-enforced access blocked the action; do not expose protected data or suggest bypasses. |
| Failed connection | Keep entered non-secret configuration, identify the failed test, and offer retest/edit. |
| Paused sync | Preserve last/next run evidence, show pause owner/time if available, and make Resume explicit. |
| Ready | Show Search-ready / Available to chat, last indexed time, active source lineage, and effective access model. |
| Disabled/unavailable connector | Explain tenant capability state; do not render a fake setup path. |
| Upload failure | Keep per-file status and error with Retry and Remove actions. |

## Visual and interaction system

- Primary `#3156D3`; hover `#2848B4`; pressed `#1F3A93`.
- Main text `#101828`; secondary text `#475467`; border `#E4E7EC`.
- Sidebar `#F7F8FC`; active navigation `#EAF0FF`; active indicator `#3156D3`.
- Processing `#3575E8`; warning `#D97706`; error `#C83D4B`; green is reserved for success only.
- Use 8–10px radii for cards, controls, tabs, and navigation. Reserve full pills for true tags/status only.
- Use borders and subtle tinted surfaces before shadows; connector cards receive only a restrained hover shadow.
- Body text stays 14–16px with 1.45–1.6 line height. Labels and metadata may be 12–13px where hierarchy is still clear.
- All interactive states include hover, active/pressed, focus-visible, loading, disabled, and selected treatments.
- Transitions are 150–220ms ease-out and are disabled by `prefers-reduced-motion`.

## Phased implementation checklist

### Phase 1 — foundation and navigation

- [ ] Replace teal primary/active tokens with the supplied cobalt system in the shared light theme.
- [ ] Standardize focus, pressed, selected, processing, warning, error, and success semantics.
- [ ] Refine sidebar surface, active tint/rail, grouping, labels, and tablet drawer behavior.
- [ ] Consolidate button, badge, tab, card, toolbar, and status classes; reduce oversized radii/pills.

### Phase 2 — Knowledge Base core

- [ ] Add the Knowledge Bases navigation route and collection-backed list.
- [ ] Add KB lifecycle/readiness mapping, progress, source lineage, access summary, and chat-ready cue.
- [ ] Add document browsing in KB context with retry and lifecycle-aware remove copy.
- [ ] Add empty/loading/error/permission-denied states for the KB route.

### Phase 3 — connection and creation flows

- [ ] Refine connector registry hierarchy and connection state labels.
- [ ] Add explicit authenticate/workspace/test/save stages where the real provider contract supports them.
- [ ] Add the five-step KB wizard with content scope selection and persistent summary.
- [ ] Trigger initial indexing only after review and successful creation.

### Phase 4 — access, schedule, and operations

- [ ] Add mirror-source/custom-audience access selection and effective-audience summary.
- [ ] Add daily/custom/manual schedule controls and pause/resume state.
- [ ] Add sync activity progress, partial failure detail, retry, and affected-document path.
- [ ] Improve local upload targeting, validation, per-file progress, metadata/access, and recovery.

### Phase 5 — QA and hardening

- [ ] Typecheck and run existing frontend tests.
- [ ] Verify backend contracts are unchanged and destructive UI actions still use lifecycle/tombstone endpoints.
- [ ] Keyboard-check sidebar, dialogs/sheets, wizard steps, tree selection, filters, tables, and actions.
- [ ] Check contrast, focus visibility, reduced motion, loading announcements, and non-color status cues.
- [ ] Capture and inspect desktop and tablet states for Knowledge Bases, connector setup, upload, access, sync, failures, and readiness.
- [ ] Fix visible spacing, hierarchy, sidebar contrast, button consistency, state copy, and responsive overflow issues.

## Delivery acceptance criteria

- Knowledge Bases are a first-class, understandable object without renaming backend contracts.
- A user can trace source connection → bound scope → KB → document → index status → effective access → chat readiness.
- No screen indicates chat readiness before processing and permission prerequisites are met.
- All unavailable or unsupported flows are explicit; there are no mocks, fake fallbacks, placeholder success states, or hidden permission bypasses.
- Existing Admin endpoints, request headers, audit behavior, source lineage, and soft-delete semantics remain intact.
- The shared visual system is cobalt-led, responsive at desktop/tablet widths, keyboard operable, reduced-motion aware, and visually verified before handoff.

## Implementation status — 2026-08-25

Implemented in this pass:

- Cobalt semantic tokens, accessible status-text aliases, 8–10px geometry, denser admin spacing, solid surfaces, and restrained connector interactions.
- Task-oriented navigation with additive aliases for Knowledge Bases, Sources & Integrations, Documents, Sync Activity, People, Access Policies, and Workspace Settings.
- Collection-backed Knowledge Base list with readiness evidence, URL-backed search/status filters, explicit loading/error/empty states, and responsive metrics.
- Knowledge Base detail tabs for lifecycle, documents, sources, access, sync evidence, and tombstone-aware settings; chat remains disabled until at least one document is ready and indexed.
- Five-step creation sheet for Source → Scope → Access → Sync → Review, with persisted-scope hierarchy, custom user/group audience, cron scheduling, live summary, retry-safe partial orchestration, and an initial binding sync.
- Additive `POST /api/v1/admin/collections` boundary using `AdminItemService`, tenant permission enforcement, `ItemService`, and append-only audit recording.
- Connector Registry migrated from retired `/datasources` calls to current plugin capability/connection contracts. Connection validation and Knowledge Base binding sync are now separate concepts.
- Keyboard-safe tabs and sheets, background inerting for modal isolation, URL-backed tab state, actionable network errors, reduced-motion support, and AA contrast remediation.

Verified:

- Frontend typecheck passes.
- All 37 frontend tests pass.
- Changed Python files pass Ruff.
- Focused PostgreSQL collection creation test passes in an isolated schema.
- Desktop, tablet, mobile, and setup-sheet screenshots were rendered and inspected under `web/.artifacts/ui-audit/after/`.
- Before review score: 6.0/10. After review score: 8.7/10. Remaining score gap is primarily contract coverage, not visual consistency.

Deliberately not represented as complete:

- Target-collection file upload needs a backend upload contract that accepts and permission-checks the destination collection. The current upload API creates a personal upload collection, so the UI does not pretend those bytes land in the selected Knowledge Base.
- Provider-side scope discovery/search needs connector discovery endpoints. The wizard shows only scope persisted on the validated connection and accepts exact auditable provider identifiers; it does not invent a remote content tree.
- Pause/resume, affected-document drill-down for partial sync failure, and binding schedule editing need additional service operations.
- The existing local development PostgreSQL volume is behind the current ORM schema (`plugin_connections` and several newer columns are absent). QA preserved that data and exercised the designed failure states instead of running the destructive `make db-init` target.
