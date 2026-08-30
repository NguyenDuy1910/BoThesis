# BoThesis connector pipeline

This package owns source extraction, Docling conversion, normalized content,
source-aware chunking, provenance, ACL mapping, and checkpoint synchronization.
Contextualization, embedding, payload projection, and Qdrant operations belong
to `bothesis.document_index`.

## Canonical flow

Source adapters produce canonical items and semantic documents cross the index
boundary together with their connector-owned evidence chunks:

```text
raw source → Docling → DocumentItem + Chunk[]
                              ↓
                  ContextualChunk → embedding → Qdrant
```

The `bothesis.services.preview` service may derive bounded WebP presentation
assets from the same durable original during ingestion. Preview generation is
independent of Docling content extraction and never enters canonical chunks or
Qdrant payloads.

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

The canonical `Item` store remains the source of truth for `AccessPolicy`, raw
object references, and provider metadata. Qdrant never receives those complete
objects or raw binary storage details. Retrieval applies tenant, tombstone,
ACL, source, and hierarchy filters before evidence is returned.

## Uploads

Personal and collection-scoped uploads use the same Docling processor,
canonical chunks, contextualization, and flat Qdrant projection as scheduled
connectors. Collection uploads retain native upload lineage under their
destination Item and never create an Integration Connection, Integration
Credential, Ingestion Source, or External Resource. Indexed files remain
tenant- and collection-permission filtered.
