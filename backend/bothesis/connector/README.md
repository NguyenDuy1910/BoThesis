# BoThesis connector pipeline

This package owns every reusable document-processing step: source extraction,
file parsing, deterministic chunking, direct-versus-retrieval routing, provider
reference caching, and the validated hand-off to embedding/vector storage.
Low-level S3/PostgreSQL byte storage and the Qdrant client remain in
`bothesis.document_index` as infrastructure implementations.

## One processing pattern

All inputs enter through the connector layer and preserve a normalized source,
lineage, and ACL before indexed content can reach retrieval:

1. Source adapters produce `SourceDocument` values.
2. File-like sources reuse `connector.file.processing.FileProcessor`.
3. Both scheduled connectors and request-owned uploads use the same
   `ChunkingConfig`, `split_text`, and `QdrantChunkPayload` contract.
4. `ConnectorPipeline` handles incremental source synchronization.
5. `DocumentPipeline` handles latency-sensitive Direct, Existing Index, and
   Index On Demand routing for uploads or other single-document callers.

Neither pipeline runs inside the agent loop. Connector-specific clients remain
inside their adapters, while embeddings, raw storage, and Qdrant are injected
through typed boundaries.

## Incremental connector contract

1. Build a `BaseSourceConnector`. Wrap synchronous source crawlers in
   `CheckpointedSourceConnectorAdapter`.
2. Build a `QdrantPayloadContext` with the authenticated tenant, connector, and
   optional scope identifiers.
3. Implement `QdrantPayloadSink.write()` to embed and upsert records, and
   `soft_delete_document()` to tombstone using **tenant + connector + document**.
4. Run `ConnectorPipeline.run_scope()` and persist its checkpoint only when
   `checkpoint_advanced` is true.

The runner bounds concurrent source fetches and Qdrant payload batch size. It
soft-deletes the previous document version before writing its deterministic
chunk IDs, which removes stale trailing chunks after a document becomes
shorter. Any failed document prevents checkpoint advancement, making a rerun
idempotent.

## Qdrant payload guarantees

`QdrantChunkPayload` validates the fields used by retrieval and governance:

- tenant, connector, scope, document, external version, and chunk identity;
- source URI, type, title, content, timestamps, file/raw-storage lineage;
- explicit ACL reader IDs, public flag, and deletion flag;
- filter fields including project, space, ticket type/status, document type,
  domain, hierarchy, parent, attachment, comment, and sheet identifiers.

Private documents may legitimately have an empty `access_control_list`; this
means no reader, not public access. Source adapters remain responsible for
mapping their native restrictions into the canonical ACL.

## File support

The built-in processor handles UTF text, JSON, HTML, XML, DOCX, PPTX, and XLSX
with file/text/archive size limits. PDF extraction is loaded lazily and requires
the optional `pypdf` package (or an injected `.pdf` extractor). Confluence
requires `atlassian-python-api`; its HTML extraction also requires
`beautifulsoup4`. Missing optional packages fail with an explicit runtime
message only when that source or format is used.

## On-demand document contract

`DocumentPipeline` accepts durable `Document` records after authorization. It
reuses the shared file parser and chunking policy, commits canonical PostgreSQL
chunks before embedding, and writes only validated `QdrantChunkPayload` data.
Images and supported small PDFs may take the Direct path without parsing;
retrieval paths remain permission-filtered and source-grounded.
