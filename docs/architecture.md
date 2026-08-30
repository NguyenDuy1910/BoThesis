# Architecture

BoThesis is organized around explicit ownership boundaries. The goal is to
keep HTTP handling thin, make business flow testable in services, and prevent
connector or storage concerns from leaking into chat and retrieval behavior.

## Request boundary

```text
HTTP request
    ↓
backend/main.py
    ↓
service
    ↓
repository / infrastructure adapter
    ↓
PostgreSQL, S3-compatible storage, Qdrant, model provider, or connector API
```

`backend/main.py` is the FastAPI boundary. It defines routes, validates HTTP
input, resolves simple request identity, calls a service, and returns an HTTP
response. It does not own SQLAlchemy sessions, transactions, connector
orchestration, document transformation, or application decisions.

## Package ownership

| Package | Responsibility |
| --- | --- |
| `services` | Application use cases, authorization at service boundaries, transactions, and persistence coordination. |
| `connector` | Provider adapters, source hierarchy, source ACL normalization, Docling processing, chunks, citations, and scope checkpoints. |
| `document_index` | Contextual chunk construction, embedding, payload projection, and Qdrant writes. |
| `preview` | Derived knowledge-asset rendering, versioned preview manifests, and short-lived preview URLs. |
| `knowledge` | Tenant and ACL filtering, retrieval, reranking, and evidence construction. |
| `agent` | Conversation orchestration, model transports, tool execution, streaming, and cited answers. |
| `db` | SQLAlchemy schema and database engine composition. |
| `tui` | A terminal API client; it does not bypass the HTTP boundary. |

## Storage ownership

```text
PostgreSQL         durable application truth
S3 / R2 / MinIO    original raw bytes
Preview            derived WebP presentation assets
Docling            document conversion and chunking
Qdrant             derived searchable chunk projection
Knowledge          permission-aware retrieval semantics
Agent              reasoning over evidence
```

PostgreSQL stores metadata, relationships, state, and access decisions. It
does not store raw document bytes or canonical chunks. An `Item` is the
canonical knowledge identity. `external_resources` maps provider identity and
incremental-ingestion state to Items without making Items connector-aware.
Full storage and schema detail lives in [Data schema](data.schema.md).

## Ingestion and retrieval

```text
Connector or upload
    ↓
Item metadata + raw bytes in object storage
    ↓
├─ Preview → derived WebP assets + versioned manifest
└─ Docling → canonical Chunk[]
    ↓
ContextualChunk → embedding + BM25 payload → Qdrant
    ↓
tenant / tombstone / ACL filter → rerank → Evidence
    ↓
agent response with citations
```

The connector advances a scope checkpoint only after a successful complete
run. Chunk identifiers are deterministic and Qdrant replaces one Item's index
on update, so retries can be safe without a generation-based index model.
Preview failures do not replace or mutate the original object and do not enter
chunking or Qdrant. Preview page numbers align with citation pages; existing
normalized citation bounding boxes provide the region mapping used by viewers.

See [Connectors and indexing](connectors-and-indexing.md) for the concrete
ingestion contract and [Agent architecture](references/agent-loop.md) for the
streaming reasoning path.
