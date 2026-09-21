# API Endpoint Inventory

Contract-first inventory. `Current` records pre-migration routes for audit;
those paths are intentionally retained as historical references. `Final`
follows `api_contract.md` and names current owning services.

| Method | Current path | Resource/purpose | Main callers | Service/use-case | Auth | Decision | Final path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| POST | `/agent/chat` | Grounded chat stream | chat shell | `ChatService.stream_turn` | caller context | keep, rename request fields | `/agent/chat` |
| GET | `/agent/collections` | Chat collection picker | chat/artifact clients | `WorkspaceDocumentService.list_collections` | collection filtering | merge | `/collections` |
| GET/POST | `/knowledge/collections` | mixed home + collection create | knowledge UI | `KnowledgeViewService`, `WorkspaceControlPlaneService` | workspace/ACL | split | GET `/knowledge/home`; GET/POST `/collections` |
| PUT | `/knowledge/collections/personal` | ensure personal collection | upload/chat UI | `WorkspaceDocumentService.ensure_personal_collection` | authenticated user | move | `/collections/personal` |
| GET | `/knowledge/collections/{collection_id}` | collection workspace projection | knowledge UI | `KnowledgeViewService.get_collection_workspace` | collection ACL | merge | `/collections/{collection_id}` |
| GET | `/knowledge/items/{item_id}` | item viewer | citation/document UI | `KnowledgeViewService.get_item` | knowledge read + ACL | rename projection to Document | `/knowledge/documents/{document_id}` |
| GET | `/knowledge/items/{item_id}/citations/{chunk_id}` | citation resolver | citation UI | `KnowledgeViewService.get_citation` | knowledge read + ACL | rename projection to Document | `/knowledge/documents/{document_id}/citations/{chunk_id}` |
| POST | `/collections/{collection_id}/documents/upload` | direct multipart upload | knowledge/control plane UI | `WorkspaceDocumentService.upload_to_collection` | collection write ACL | rename; merge with reservation | `/collections/{collection_id}/documents` (`multipart/form-data`) |
| POST | `/documents/uploads` | presigned Document reservation | chat upload UI | `WorkspaceDocumentService.start_upload` | caller + destination Collection | merge into Document creation | `/collections/{collection_id}/documents` (`application/json`) |
| POST | `/documents/{document_id}/complete` | validate presigned object | chat upload UI | `WorkspaceDocumentService.complete_upload` | caller + Document ownership | rename method; remove Upload resource | `PUT /documents/{document_id}/content` |
| POST | `/documents/{document_id}/retry` | document indexing retry | knowledge UI | `WorkspaceDocumentService.retry_indexing` | caller | merge | `/ingestions/{ingestion_id}/retry` |
| POST | `/documents/search` | semantic search | knowledge UI | `KnowledgeQueryService.search` | permission-filtered | keep | same |
| GET/DELETE | `/documents/{doc_id}` | document read/removal | chat/knowledge UI | `WorkspaceDocumentService` | caller + collection | rename ID | `/documents/{document_id}` |
| GET/POST/PATCH/DELETE | `/admin/collections*` | Collection CRUD/ACL | control plane UI | `WorkspaceControlPlaneService`, `ItemCatalogService` | workspace access | merge | `/collections*` |
| GET/POST/PATCH/DELETE | `/admin/items*` | mixed Item inventory/retry | control plane UI | `ItemCatalogService` | item manage | split/merge | `/collections`, `/documents`, `/ingestions` |
| GET | `/admin/overview` | workspace dashboard | control plane UI | `DashboardService.overview` | workspace read | move | `/workspaces/{workspace_id}/overview` |
| GET/PATCH | `/admin/spaces*` | workspace profile | control plane UI | `TenantService` | workspace read/manage | rename | `/workspaces*` |
| GET/POST/PATCH | `/admin/users*` | workspace users | control plane UI | `UserService` | user manage | move | `/users*` |
| GET/POST/PATCH/DELETE | `/admin/roles*` | workspace roles | control plane UI | `RoleService` | role manage | move; DELETE becomes PATCH status | `/roles*` |
| GET/POST/PATCH/DELETE | `/admin/groups*` | workspace groups | control plane UI | `GroupService` | group manage | move | `/groups*` |
| GET | `/admin/permissions` | permission catalog | control plane UI | `RoleService.list_permissions` | role manage | move | `/permissions` |
| GET/POST/PATCH | `/admin/approval-requests*` | governance requests | control plane UI + users | `ApprovalRequestService` | requester/reviewer | move | `/approval-requests*` |
| GET | `/admin/audit-logs` | workspace audit | control plane UI | `AuditService.list_events` | audit read | move | `/audit-logs` |
| GET | `/admin/platform/overview` | platform dashboard | platform control UI | `DashboardService.platform_overview` | platform permission | move | `/platform/overview` |
| GET | `/admin/platform/workspaces` | all workspaces | platform control UI | `DashboardService.list_platform_workspaces` | platform permission | move | `/platform/workspaces` |
| GET | `/admin/platform/users` | all users | platform control UI | `UserService.list_platform_users` | platform permission | move | `/platform/users` |
| GET | `/admin/platform/audit` | all audit | platform control UI | `AuditService.list_platform_events` | platform permission | rename/move | `/platform/audit-logs` |
| GET | `/admin/platform/health` | platform health | platform control UI | `HealthService` | platform permission | move | `/platform/health` |
| GET/POST/PATCH/DELETE | `/connections*` | connection resource | integrations UI | `IntegrationLifecycleService` | connection capabilities | keep, rename IDs | `/connections*` |
| GET/POST/PATCH/DELETE | `/sources*` | source/schedule resource | integrations UI | `IntegrationLifecycleService` | source capabilities | keep, remove action routes | `/sources*` |
| GET/POST | `/ingestions*` | ingestion runs | integrations UI | `IntegrationLifecycleService`, Temporal adapter | source manage | rename IDs | `/ingestions*` |
| POST | `/sources/{source_id}/ingestions` | start source ingestion | integrations UI | `IntegrationLifecycleService.ingest_source` | source manage | keep | same |
| POST | `/sources/{source_id}/schedule/pause` | schedule state command | integrations UI | Temporal schedule adapter | source manage | remove | PATCH schedule `enabled=false` |
| POST | `/sources/{source_id}/schedule/resume` | schedule state command | integrations UI | Temporal schedule adapter | source manage | remove | PATCH schedule `enabled=true` |
| POST | `/auth/guest-sessions` | provider-shaped guest Session creation | auth client | `AuthenticationService.create_guest_session` | public | merge into canonical Session operation | `/auth/sessions` (`method=guest`) |
| POST | `/auth/password` | provider-shaped password Session creation | auth client | `AuthenticationService.complete_password_login` | public/guest | merge into canonical Session operation | `/auth/sessions` (`method=password`) |
| POST | `/auth/google` | provider-shaped Google Session creation | auth client | `AuthenticationService.complete_google_login` | public/guest | merge into canonical Session operation | `/auth/sessions` (`method=google`) |
| POST | `/auth/accounts` | local Account creation plus first Session | auth client | `AuthenticationService.create_password_account` | public/guest | keep resource operation; rename response fields | `/auth/accounts` |
| POST | `/auth/session` | workspace switch encoded as Session replacement | workspace switcher | `AuthenticationService.create_session` | bearer | model as Session state update | `PATCH /auth/session` |
| GET | *(missing)* | current authenticated Session/context | auth client and app shell | access-session resolver | bearer | add explicit resource read | `/auth/session` |
| PATCH | *(missing)* | active workspace state update | workspace switcher | `AuthenticationService.create_session` | bearer | add explicit state transition | `/auth/session` |
| DELETE | *(missing)* | current Session invalidation/logout | auth client and app shell | access-session lifecycle | bearer | add explicit resource removal | `/auth/session` |
| GET | `/health` | liveness/readiness | deployment | `HealthService` | public | keep | `/health` |

## Legacy removal gates

Implementation phase finishes with zero public/frontend references to these
legacy paths or fields:

```text
/admin/collections
/agent/collections
/admin/items
/admin/spaces
/admin/platform
/knowledge/collections
/knowledge/items/{item_id}
/knowledge/items/{item_id}/citations/{chunk_id}
/documents/uploads
/document-uploads
/document-uploads/{upload_id}/complete
/documents/{document_id}/complete
/schedule/pause
/schedule/resume
/auth/guest-sessions
/auth/password
/auth/google
/auth/session (POST)
workflow_id
doc_id
integration_connection_id
requester_user_id
ChatRequest.user_id
ChatRequest.tenant_id
ChatRequest.roles
```

Auth-specific legacy symbols are also removed after migration:

```text
create_guest_session
complete_password_login
complete_google_login
createPasswordSession
createGuestSession
createGoogleSession
complete_password_login
complete_google_login
active_tenant_id (public DTO/client field)
tenants (public auth response field)
username as password-login identifier
```

Internal DB columns and Temporal adapter locals may retain implementation names
only when they never cross API DTO/client boundary.
