# Document and Content API Contract

Status: target contract. This document is part of the contract-first gate;
router, service, storage, frontend, and test changes wait until this model is
accepted.

## Domain finding

Current implementation already creates the canonical Document before bytes are
uploaded. `item_uploads` is a one-to-one internal record keyed by `item_id`; it
has no independent upload ID, durable expiration, multipart parts, uploaded-byte
counter, abort operation, or multiple-upload lifecycle. Presigned URL expiry is
temporary transport state. Repeating Document creation with the same
`Idempotency-Key` returns the same Document and can issue fresh instructions.

Therefore `DocumentUpload` is not a public resource. Final model is:

```text
Collection
    -> Document
        -> Content
            -> Ingestion (when purpose requires indexing)
```

## Final endpoint contract

| Method | Path | Purpose | Authorization | Idempotency |
| --- | --- | --- | --- | --- |
| POST | `/api/v1/collections/{collection_id}/documents` | Create Document; accept direct multipart content or reserve presigned content upload | authenticated user + Collection write access | required `Idempotency-Key` |
| GET | `/api/v1/documents` | List permission-filtered Documents | workspace permission + Collection ACL | n/a |
| POST | `/api/v1/documents/search` | Search permission-filtered indexed Documents | workspace permission + Collection ACL | n/a |
| GET | `/api/v1/documents/{document_id}` | Read canonical Document metadata | Collection read access | n/a |
| PUT | `/api/v1/documents/{document_id}/content` | Validate reserved object, bind it as Document content, and start Ingestion when required | Document/Collection write access | method is idempotent |
| DELETE | `/api/v1/documents/{document_id}` | Remove Document from normal use | Document/Collection delete access | method is idempotent |

No `PATCH /documents/{document_id}` is added: current product has no distinct
Document metadata-edit use case.

## Document creation

One endpoint accepts two transport representations.

Presigned reservation uses `application/json`:

```json
{
  "name": "annual-report.pdf",
  "content_type": "application/pdf",
  "size_bytes": 1024000,
  "purpose": "knowledge"
}
```

Direct upload uses `multipart/form-data`:

```text
file=<binary>
purpose=knowledge
```

`purpose` is `knowledge` or `conversation_attachment`. It is business intent,
not transport choice:

- `knowledge` starts a durable Ingestion after content becomes available.
- `conversation_attachment` keeps content available for scoped agent use and
  does not index it eagerly.

Both representations call one Document creation use-case. Direct upload stores
and validates bytes within the request. JSON creation returns temporary upload
instructions associated with the Document.

Response is `DocumentCreateResult`:

```json
{
  "document": {
    "id": "document-uuid",
    "collection_id": "collection-uuid",
    "name": "annual-report.pdf",
    "content_type": "application/pdf",
    "size_bytes": 1024000,
    "purpose": "knowledge",
    "status": "pending_content",
    "created_at": "2026-09-21T00:00:00Z",
    "updated_at": "2026-09-21T00:00:00Z"
  },
  "upload": {
    "url": "https://temporary-upload-target.example",
    "method": "PUT",
    "headers": {"Content-Type": "application/pdf"},
    "expires_at": "2026-09-21T00:10:00Z"
  },
  "ingestion": null,
  "created": true
}
```

`created` is `false` when the same idempotency key replays an existing
Document; response shape stays unchanged.

For direct `knowledge` upload, `document.status` is `available`, `upload` is
null, and `ingestion` contains the created Ingestion. For
`conversation_attachment`, `ingestion` remains null regardless of transport.

## Content finalization

After direct object-storage upload, client calls:

```text
PUT /api/v1/documents/{document_id}/content
```

No storage key, bucket, provider, ETag, workflow ID, or upload ID is accepted.
Server resolves the reserved storage location, checks object existence, size,
and content type, then makes content available. Repeating PUT after success
returns the same successful state.

Response is `DocumentContentResult` containing updated `document` and optional
`ingestion`. This endpoint does not upload raw bytes through API; direct raw
bytes use multipart Document creation.

## Lifecycle separation

`Document.status` describes canonical content availability only:

```text
pending_content | available | failed
```

These are public API states. Internal `items.status`, `items.index_status`, and
the private `item_uploads.status` may keep storage-oriented values; API mapping
belongs at the `backend/api` boundary and must not leak those values.

Deleted Documents are no longer returned to normal callers, so `deleted` is
not a readable public state. Search/index processing remains on the separate
`Ingestion` resource:

```text
pending | running | completed | failed | cancelled | timed_out
```

Document responses may expose `latest_ingestion_id`, but do not duplicate
Ingestion status as `index_status`, `processing`, or `ready`.

State transitions are intentionally narrow:

```text
create (JSON reservation) -> pending_content
create (multipart content) -> available
PUT /content (validated object) -> available
content validation failure -> failed
failed -> available           (retry after valid object is present)
available -> available       (idempotent finalization)
```

`available` does not imply searchable. A `knowledge` Document starts a
separate Ingestion; `conversation_attachment` does not start eager indexing.

## Idempotency

`Idempotency-Key` scope is authenticated actor + workspace + Document-creation
operation. Same key and same normalized request returns same Document. Pending
presigned flow may return refreshed temporary instructions. Reusing key with a
different Collection, name, content type, size, or purpose returns `409
IDEMPOTENCY_KEY_REUSED`. For multipart creation, the first file's normalized
metadata and content binding belong to that key; a different file under the
same key also returns `409` rather than mutating the existing Document.

## Status codes

| Operation | Success | Expected failures |
| --- | --- | --- |
| Create Document | `201` (new), `200` (idempotent replay) | `401`, `403`, `404`, `409`, `413`, `415`, `422`, `429` |
| Read Document | `200` | `401`, `403`, `404` |
| Finalize content | `200` | `401`, `403`, `404`, `409`, `422` |
| Delete Document | `204` | `401`, `403`, `404` |

DELETE response means Document is unavailable to normal callers. Tombstone
storage strategy remains internal.

## Before to after mapping

| Current/previous target | Decision | Final |
| --- | --- | --- |
| `POST /documents/uploads` | merge | `POST /collections/{collection_id}/documents` with JSON |
| `POST /document-uploads` | remove public Upload resource | `POST /collections/{collection_id}/documents` with JSON |
| `POST /document-uploads/{upload_id}/complete` | remove upload identity | `PUT /documents/{document_id}/content` |
| `POST /documents/{document_id}/complete` | rename/resource-orient | `PUT /documents/{document_id}/content` |
| `POST /collections/{collection_id}/documents/upload` | rename | `POST /collections/{collection_id}/documents` with multipart |
| `POST /documents/{document_id}/retry` | merge into Ingestion lifecycle | `POST /ingestions/{ingestion_id}/retry` |
| `GET /documents/{doc_id}` | rename identifier | `GET /documents/{document_id}` |
| `DELETE /documents/{doc_id}` | rename identifier | `DELETE /documents/{document_id}` |

## Implementation gate

Implementation must converge direct and presigned transports on one Document
creation pipeline, keep object storage inside `bothesis.storage`, keep
Document/content lifecycle in Item services, and keep indexing lifecycle in
`ItemIngestionService`. No compatibility upload routes or public `upload_id`
remain after callers migrate.
