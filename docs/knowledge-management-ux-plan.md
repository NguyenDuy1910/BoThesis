# Knowledge management UX architecture

## Product model

A Knowledge Base is a durable collection. It exists independently from the
ways content enters it. Source connections, source bindings, imports, and
schedules remain separate governed records so adding a future ingestion method
does not change collection creation.

```text
Knowledge Base
├── Items
├── Source bindings
├── Activity
└── Collection settings and access

Source connection ──bind/import──▶ Knowledge Base
Schedule ──runs a source binding──▶ Knowledge Base
```

## Audit of the previous experience

| Severity | Finding | User impact | Resolution |
| --- | --- | --- | --- |
| Critical | Creation required `Source → Scope → Access → Sync → Review`. | Users could not create the collection they intended to organize until they also designed a pipeline. | Replaced with one focused dialog containing only name and optional description. |
| Major | The setup sheet mixed collection, connector, permissions, and automation state. | Ownership of each setting and the meaning of “Create” were unclear. | Source binding, access, imports, and schedules are independent follow-up flows. |
| Major | A wide sheet and live summary devoted most of the viewport to information that did not help initial creation. | Slow scanning, weak hierarchy, and excessive empty space. | Compact dialog, autofocus, inline validation, Enter submission, loading state, and duplicate-submit protection. |
| Major | The detail page led with an ingestion lifecycle rather than the collection’s content workspace. | A new empty collection looked incomplete or broken instead of ready. | The collection opens directly to Items with an actionable empty state. |
| Major | Schedule data appeared in creation, list columns, and a local Sync tab. | Automation was presented as a mandatory Knowledge Base property. | Added a workspace-level Schedules destination; detail Activity only links to it. |
| Moderate | The list emphasized readiness metrics and refresh cadence. | Collections were harder to scan by ownership and content. | The list now prioritizes name, description, items, sources, owner, and updated time. |
| Moderate | Upload and manual creation entry points implied capabilities not supported by collection-scoped backend contracts. | A UI could falsely suggest content landed in the selected collection. | Actions explicitly identify the missing contract and never create fake records. |

## Information architecture

- Knowledge
  - Knowledge Bases
  - All Items
- Data
  - Sources & Integrations
  - Sync Activity
- Automation
  - Schedules
  - Workflows
- Administration
  - People, Groups, Access Requests, Roles, and Access Policies
  - Workspace Settings
  - Audit Log

## Primary flows

### Create a Knowledge Base

1. Open **Knowledge Bases**.
2. Select **Create knowledge base**.
3. Enter a required name and optional description.
4. Submit with the button or Enter.
5. The server creates the collection and owner grant.
6. A success toast is announced and the new collection opens on **Items**.
7. The user can add content now, leave, or return later.

### Connect a source after creation

1. From the header, Add content menu, Items empty state, or Sources tab,
   select **Connect source**.
2. Choose an existing validated connection, or open **Connect a new source**.
3. New connector setup carries a safe return path back to the originating
   Knowledge Base.
4. The selected connection creates a source binding without a schedule.
5. The first import is requested separately and its result appears in Activity.

### Configure automation

1. Open **Schedules** independently from collection creation.
2. Choose an existing source binding. Its source and destination Knowledge Base
   are shown together.
3. Select daily, weekly, or a custom cron frequency and timezone.
4. Create or edit the schedule, pause/resume it, or run the binding now.
5. Last run, next run, and current execution status remain visible in the list.

## UI state model

| Surface | State | Treatment |
| --- | --- | --- |
| Create dialog | Pristine | Create disabled; name autofocus. |
| Create dialog | Invalid | Inline name error after blur or attempted submit; focus returns to name. |
| Create dialog | Submitting | Button spinner, `aria-busy`, close guarded, duplicate submit ignored. |
| Create dialog | Failed | Inline actionable API error; entered values retained. |
| Create dialog | Succeeded | Success toast, modal closes, new Knowledge Base opens. |
| List | Loading | Structure-preserving row skeletons. |
| List | Empty | Explains collections and offers creation. |
| List | No results | Filter-specific copy and Clear filters action. |
| List | Partial data error | Collections remain openable; missing counts/owners are disclosed. |
| Detail Items | Empty | “Add your first knowledge” with Upload, Create item, and Connect source actions. |
| Source binding | Submitting | Selected connection and form remain stable; duplicate binding submit blocked. |
| Source binding | Import request failed | Binding success is retained and reported separately from failed import start. |
| Schedules | Empty | Explains that source binding is a prerequisite, not Knowledge Base creation. |
| Destructive action | Confirming | Real confirmation dialog; archive uses the existing tombstone endpoint. |

## API and data-model compatibility

- `POST /api/v1/admin/collections` already accepted `title`, optional metadata,
  and no source or schedule. No creation-model migration was required.
- `PATCH /api/v1/admin/collections/{item_id}` is additive and updates the
  collection title and description while preserving unrelated metadata.
- `POST /api/v1/collections/{collection_id}/documents/upload` accepts one
  multipart file with an `Idempotency-Key`, enforces collection editor access,
  stores the raw object, and runs the document indexing pipeline without a
  connector or source binding.
- Collection list payloads now include metadata, access inheritance, and the
  creator user ID so description and owner filtering are grounded in server
  data.
- Source binding continues to use the existing Plugin Connection and Plugin
  Binding APIs. Schedule creation/update continues to use the schedule member
  on the existing binding update contract.
- Archive continues to call the existing Item delete boundary, which writes a
  lifecycle tombstone rather than physically deleting business data.

## Known backend dependencies

- Manual authored items need a collection-scoped create/index contract with
  explicit lineage and access inheritance. The UI does not simulate this.
- A source connection currently owns its provider scope. Per-binding remote
  scope discovery remains dependent on connector discovery endpoints.
- No tenant storage or ingestion quota model currently exists. Collection
  uploads enforce the configured per-file upload and processing limits.
