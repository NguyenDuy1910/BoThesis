# API Contract Migration Plan

This plan begins only after `api_contract.md`, `auth_contract.md`,
`document_contract.md`, `endpoint_inventory.md`, and target `openapi.yaml` are
accepted.

## Authentication contract migration

The auth contract is now resource-oriented and intentionally smaller than the
current router surface:

- `POST /auth/accounts` remains Account creation and may issue the first
  Session.
- `POST /auth/sessions` becomes the only public Session-creation route. Its
  discriminated request variants are `password`, `guest`, and `google`.
- `GET /auth/session` returns current server-resolved Session context.
- `PATCH /auth/session` changes active workspace on the current Session.
- `DELETE /auth/session` invalidates the current durable access Session.

Current `/auth/password`, `/auth/google`, and `/auth/guest-sessions` handlers
must become internal authentication strategies behind `SessionService`; they
must not remain public aliases. The existing POST `/auth/session` workspace
switch becomes `PATCH /auth/session` with an `active_workspace_id` state
update.

The current access-session table already provides durable lifecycle state,
guest-to-user parent/child lineage, expiry, and revocation status. The
implementation phase must expose that lifecycle through one service, add an
explicit invalidation operation for logout, and map internal `tenant_id` and
`active_tenant_id` to public `workspace_id` and `active_workspace_id` only at
the API boundary.

Authentication errors must map to the stable error envelope without account
enumeration. Password, Google, and guest requests may be unauthenticated;
workspace switching requires an existing bearer Session through
`PATCH /auth/session`. No password-reset or password-change resource is added
until a real product use case and persistence flow exist.

Local credential migration changes the public identifier from `username` to
canonical `email`. Existing `User.username` values remain profile metadata
until data migration is complete; the auth service must resolve password
credentials by normalized email and preserve generic failure messages.

## Architecture gaps blocking honest transport renames

### Durable Ingestion identity

Current Source ingestion state is read directly from Temporal visibility and
uses Temporal workflow ID as public identity. Renaming `workflow_id` to
`ingestion_id` at router boundary would preserve infrastructure coupling.

Required design:

- Add durable `Ingestion` resource owned by `ItemIngestionService`/ingestion
  lifecycle boundary.
- `Ingestion.id` is public UUID.
- `temporal_workflow_id` and `temporal_run_id` are private nullable execution
  references.
- Source-triggered and native-upload indexing create same Ingestion resource.
- Retry creates a new execution for same logical ingestion attempt chain or a
  new retry record, with explicit `retry_of_ingestion_id` lineage.
- API lookup always resolves `ingestion_id` before calling workflow adapter.
- Temporal visibility is operational input, not API persistence.

Minimum fields:

```text
id UUID
workspace_id/tenant_id UUID
source_id UUID nullable
document_id UUID nullable
connection_id UUID nullable
status enum
trigger_type enum
retry_of_ingestion_id UUID nullable
temporal_workflow_id string nullable
temporal_run_id string nullable
created_by_user_id UUID nullable
started_at / finished_at / created_at / updated_at
deleted_at nullable
```

### Document-first content lifecycle

Current implementation proves Upload is transport state, not an independent
domain resource:

- canonical Document `Item` is persisted before presigned or direct bytes;
- `ItemUpload` is one-to-one and keyed by `item_id`;
- no durable `upload_id`, upload expiry, multipart parts, abort, uploaded-byte
  counter, or multiple-upload lifecycle exists;
- presigned expiry is temporary storage-adapter output;
- completion already resolves by Document ID.

Required design:

- Do not add `ItemUpload.id` or expose an Upload resource.
- Make `POST /collections/{collection_id}/documents` the only Document creation
  operation for both JSON reservation and multipart upload.
- Keep `ItemUpload` as a private idempotency/content-availability ledger, or
  fold it into Document persistence only if current invariants remain intact.
- Replace upload completion with idempotent
  `PUT /documents/{document_id}/content`.
- Model Document content state as `pending_content|available|failed`; keep
  indexing state exclusively on durable Ingestion.
- Add explicit Document purpose (`knowledge|conversation_attachment`) so
  ingestion policy is business-driven, not inferred from transport endpoint.
- Preserve size/content-type validation and object metadata internally; never
  expose storage keys, provider IDs, buckets, or Temporal IDs.

### Collection read ownership

Current Collection reads are split between `KnowledgeViewService`,
`WorkspaceDocumentService`, and `ItemCatalogService`, with different permission
ceilings. Final API needs one Collection application service that:

- lists only Collections visible through workspace permission + Collection ACL;
- creates and updates through Collection lifecycle policy;
- supplies canonical Collection response DTOs;
- is reused by chat picker, knowledge home projection, artifact publish picker,
  upload destination picker, and admin UI;
- delegates projection-only recent document work to `KnowledgeViewService`.

### Permission vocabulary

Current permissions use codes such as `user.manage`, `item.manage`, and
`source.manage`. Target public contract uses resource-specific capabilities.
Migration must define one mapping and update seeded roles atomically. Never
accept both vocabularies indefinitely.

Proposed mapping:

| Current | Final |
| --- | --- |
| `tenant.read` | `iam.workspaces.read` |
| `tenant.manage` | `iam.workspaces.manage` |
| `user.manage` | `iam.users.manage` |
| `role.manage` | `iam.roles.manage` |
| `group.manage` | `iam.groups.manage` |
| `item.manage` | split into `knowledge.collections.*` and `knowledge.documents.*` lifecycle capabilities |
| `collection.read` | `knowledge.collections.read` |
| `collection.update` | `knowledge.collections.update` |
| `collection.delete` | `knowledge.collections.delete` |
| `collection.share` | `knowledge.access.manage` |
| `source.manage` | `sources.manage` and `connections.manage` |
| `audit.read` | `audit.read` |

Document capability set:

```text
knowledge.documents.read
knowledge.documents.search
knowledge.documents.create
knowledge.documents.write
knowledge.documents.delete
```

These capabilities do not replace Collection ACL checks. Document reads/search
require Collection `viewer` per returned Document; creation, content
finalization, and deletion require Collection `editor` (or owner).

Read capabilities must be explicit where read-only roles exist. Platform
permission codes may remain stable if already canonical.

## Implementation sequence

1. Add durable Ingestion identity with migrations and service contracts. Keep
   the existing one-to-one upload ledger private; add no public upload identity
   or route.
2. Introduce final API DTOs and response mappers in `backend/api`.
3. Consolidate Collection service ownership and ACL checks.
4. Register final routers under `/api/v1`; do not register legacy aliases.
5. Migrate authentication response and request terminology at API boundary.
6. Migrate frontend request clients and types in one pass.
7. Update existing tests under `tests/`; add focused contract assertions there.
8. Delete legacy router handlers, old DTO fields, old service methods, and stale
   frontend functions after repository-wide caller search.
9. Generate runtime OpenAPI and compare it structurally against target
   `backend/docs_design/openapi.yaml`.
10. Run backend tests, frontend tests/typecheck/lint, route-remnant searches,
    and manual OpenAPI inspection.

## Deletion gate

Legacy code is deleted only when all real callers map to final routes. No
deprecated aliases, compatibility wrappers, or dual request fields remain.
