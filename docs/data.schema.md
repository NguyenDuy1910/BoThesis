# Enterprise Agent Storage Ownership

PostgreSQL stores durable business and application state: identities, tenant
memberships, Integration Connections, encrypted Integration Credentials,
Ingestion Sources and checkpoints, External Resource identity, canonical Items,
ACLs, chat state, and audit records.

Identity and session state stay separate. `users` stores durable human
identities; `auth_identities` maps `(issuer, subject)` from an external
provider to one User; `access_sessions` stores tenant context, guest/user
kind, expiry, revocation, token version, and transition lineage. Guest
sessions have no User row or role assignment. Public access resolves through
the tenant's `public_access_role_id`. Login creates a child User session,
supersedes the Guest session, and assigns its guest-created conversations to
the durable User while preserving `created_by_session_id`.

The canonical knowledge model is one `items` table. `item_type` distinguishes
Collections and Documents. `parent_item_id` represents canonical containment;
each child remains independently persisted. Binary-backed Items store only
`storage_key`, MIME type, size, and metadata in PostgreSQL.

An Item's `status` is its durable resource lifecycle. Documents also have an
`index_status` (`pending`, `processing`, `ready`, `failed`, or `unsupported`)
for the derived semantic projection. This lets an authorized agent read a
stored upload directly while its Qdrant representation is not yet ready.

Source configuration is separate: `integration_connections` owns reusable
connector configuration, `integration_credentials` owns encrypted secrets, and
`ingestion_sources` owns one checkpointed external scope and its destination
Collection. `external_resources` preserves
`(ingestion_source_id, external_id) -> item_id` plus provider versions, ETags,
URLs, update timestamps, and last-seen/tombstone state. Items do not depend on
any of these source-layer records.

Native uploads use `item_uploads` for idempotency and upload lifecycle. They do
not create Integration Connections, Ingestion Sources, or External Resources.
Collection uploads schedule the existing Item indexing pipeline in Temporal;
the workflow changes only `index_status` and derived citations/index points.

S3-compatible object storage is mandatory for original file bytes. Presigned
URLs are generated at runtime and are never persisted. PostgreSQL has no blob
or raw-byte fallback.

Docling reads originals from object storage and produces normalized content and
retry-safe chunks. Chunks flow directly through contextualization and embedding
into Qdrant. PostgreSQL does not persist chunks. Qdrant points use deterministic
IDs derived from the canonical Item identity and chunk index, and carry bounded
tenant, Collection, source, citation, and lifecycle lineage.

Ingestion Sources advance `checkpoint` only after a complete successful run.
Temporal owns schedule and execution history. There is no generation or
blue/green scope state in PostgreSQL.

`message_items` associates messages with canonical Items through `attachment`,
`reference`, or `output` relations. Runtime deletion is tombstone-only: Items,
message links, ACL records, and Qdrant points remain recoverable and normal
reads exclude their tombstones. Original object bytes are retained.

The ORM is the current schema definition. SQL migrations preserve durable data
when persisted source-layer names or constraints change. Recreating the derived
Qdrant collection is safe because PostgreSQL and object storage remain the
authoritative stores.
