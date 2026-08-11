# BoThesis connector pipeline

This package owns source extraction and the validated hand-off to indexing. It
does not open a Qdrant connection or generate embeddings; those remain behind
the `QdrantPayloadSink` boundary in `pipeline.py`.

## Run contract

1. Build a `BaseSourceConnector`. Wrap synchronous Confluence/Jira crawlers in
   `CheckpointedSourceConnectorAdapter`.
2. Build a `QdrantPayloadContext` with the authenticated tenant, connector, and
   optional scope identifiers.
3. Implement `QdrantPayloadSink.write()` to embed and upsert records, and
   `delete_document()` to soft-delete using **tenant + connector + document**.
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
means no reader, not public access. Confluence pages without page restrictions
remain scoped to their space, and Jira issues remain scoped to their project.

## File support

The built-in processor handles UTF text, JSON, HTML, XML, DOCX, PPTX, and XLSX
with file/text/archive size limits. PDF extraction is loaded lazily and requires
the optional `pypdf` package (or an injected `.pdf` extractor). Confluence and
Jira require `atlassian-python-api`; Confluence HTML extraction also requires
`beautifulsoup4`. Missing optional packages fail with an explicit runtime
message only when that source or format is used.
