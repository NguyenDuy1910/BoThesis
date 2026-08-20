# BoThesis Document Storage

PostgreSQL remains the source of truth for document metadata, ownership,
lineage, message links, and canonical chunks. S3-compatible object storage is
the primary raw-binary store; `document_blobs` is a bounded fallback. Qdrant is
replaceable derived state and is never the authority for document content.

Chat uploads create uploader-private `documents` rows before bytes are sent.
`upload_status`, `content_sha256`, `upload_idempotency_key`, and `uploaded_at`
make upload retries and content readiness explicit. Provider-specific reusable
references remain under `documents.metadata.provider_cache` and must carry the
source fingerprint they were created from.

Messages refer to files only through `message_documents`. User-supplied
documents use `attachment`; documents cited by an assistant use `reference`.
No parallel file or attachment entity is introduced.

Deletion is soft-only and recoverable. Documents transition
`active -> hidden -> deleted`; the hidden state denies reads while PostgreSQL
chunks and fallback blobs, provider-cache entries, and Qdrant points receive
tombstones. S3 objects, PostgreSQL bytes, provider references, metadata, and
lineage remain retained. A failed tombstone operation remains hidden and can be
retried. The application contains no physical purge path.

`tenant_memberships`, `document_chunks`, `message_documents`,
`user_principal_tokens`, and `document_blobs` carry `deleted_at`. Authorization,
document processing, message linking, and retrieval queries exclude rows where
that timestamp is set. Reusing a stable key reactivates the retained row instead
of deleting and recreating it.
