# BoThesis Storage Ownership

PostgreSQL stores durable business and application state: identities, tenant
memberships, configured connector instances, encrypted connector credentials,
sync checkpoints and history, canonical source Items, ACLs, chat state, and
audit records.

The canonical source model is one `items` table. `item_type` distinguishes
collections, semantic documents, and opaque files. `parent_item_id` represents
source containment; each child remains independently persisted. Binary Items
store only `storage_key`, MIME type, size, and SHA-256 metadata in PostgreSQL.

S3-compatible object storage is mandatory for original file bytes. Presigned
URLs are generated at runtime and are never persisted. PostgreSQL has no blob
or raw-byte fallback.

Docling reads originals from object storage and produces normalized content and
retry-safe chunks. Chunks flow directly through contextualization and embedding
into Qdrant. PostgreSQL does not persist chunks. Qdrant points use deterministic
IDs derived from the canonical Item identity and chunk index, and carry bounded
lineage plus allowed and denied principal-token projections.

Connector scopes advance `sync_checkpoint` only after a complete successful
run. `sync_runs` is operational history, not an index versioning mechanism.
There is no generation or blue/green scope state.

`message_items` associates messages with canonical Items through `attachment`,
`reference`, or `output` relations. Runtime deletion is tombstone-only: Items,
message links, ACL records, and Qdrant points remain recoverable and normal
reads exclude their tombstones. Original object bytes are retained.

The project is in initial development. `make init` rebuilds the initial schema
directly from the ORM and recreates the derived Qdrant collection; there is no
migration or legacy compatibility layer.
