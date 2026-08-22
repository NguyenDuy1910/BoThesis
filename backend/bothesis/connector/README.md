# BoThesis connector pipeline

This package owns source extraction, normalized content handling, contextual
chunking, embedding hand-off, and permission-aware synchronization. Low-level
storage and Qdrant client operations remain in `bothesis.document_index`.

## Canonical flow

Source adapters produce canonical `AnyItem` values (`DocumentItem`,
`CollectionItem`, or `FileItem`). A semantic document follows this path:

```text
DocumentItem → ContentPart[] → Chunk → ContextualChunk → embedding → Qdrant
```

Standalone images use `DocumentItem(document_kind="image")`; they are indexed
from captions, OCR, or descriptions rather than binary payloads.

`ConnectorPipeline` consumes `ItemChange` values, bounds source fetches and
write batches, soft-deletes stale item points, and advances a checkpoint only
when the complete scope succeeds. Point IDs are deterministic, so retries are
safe.

## Qdrant projection

`QdrantChunkPayload` is a flat retrieval projection of `ContextualChunk`. It
contains chunk text, contextual embedding text, citation fields, provider and
external identity, flattened hierarchy (`parent_id`, `root_id`, and
`ancestor_ids`), tenant/tombstone governance, and resolved `reader_ids`.

The canonical `Item` store remains the source of truth for `AccessPolicy`,
`StorageObject`, and provider metadata. Qdrant never receives those complete
objects or raw binary storage details. Retrieval applies tenant, tombstone,
ACL, source, and hierarchy filters before evidence is returned.

## Uploads

Request-owned uploads reuse the same `ChunkingConfig`, contextual text builder,
and flat Qdrant payload as scheduled connectors. Direct-capable files can still
use the direct model path; indexed files remain permission-filtered and
source-grounded.
