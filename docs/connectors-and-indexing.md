# Connectors and indexing

The connector boundary turns external source data into canonical BoThesis
Items. It owns provider-specific behavior so retrieval and the agent operate on
one consistent source and evidence model.

## Current managed sources

| Source | Role |
| --- | --- |
| Managed files | Accepts uploaded files, stores original bytes in S3-compatible storage, and processes supported content through Docling. |
| Confluence | Discovers and normalizes page and attachment content, hierarchy, and source permissions. |

Additional providers belong behind the same connector protocol; provider types
must not leak into `knowledge` or `agent` behavior.

## Canonical hierarchy

Every source entity is an Item:

```text
CollectionItem
└── DocumentItem
    ├── DocumentItem
    └── FileItem
```

`parent_item_id` represents source containment. References between documents do
not modify that hierarchy. Binary-backed Items persist only object metadata and
a `storage_key`; they never store raw bytes in PostgreSQL.

## Indexing pipeline

```text
source change
    ↓
connector normalization + ACL mapping
    ↓
object storage, when raw bytes are required
    ↓
Docling conversion → provenance-aware Chunk[]
    ↓
structural context + optional semantic context
    ↓
dense embedding + Qdrant BM25 document
    ↓
deterministic Qdrant point replacement
```

`contextual_text` is the retrieval representation. Structural context is always
available. Optional semantic contextualization adds a short chunk-specific
description through the configured model and falls back safely to structural
context when unavailable. The original `chunk_text` remains the evidence text.

Qdrant executes dense and BM25 searches and combines candidates with native
reciprocal-rank fusion. The `knowledge` package applies tenant, source,
tombstone, and principal filters before reranking and evidence projection.

## Access control

Connector credentials and reader permissions serve different purposes:

```text
encrypted ConnectorCredential → lets BoThesis read a provider
Item allowed/denied principals → lets a user retrieve source evidence
```

Connectors normalize source ACLs into principal tokens. The Item ACL is
projected into Qdrant for pre-retrieval filtering and is defensively checked
again before evidence reaches the agent.

## Ingestion semantics

- An `integration_connections` row is reusable provider configuration and
  optional credentials, not canonical knowledge.
- An `ingestion_sources` row is one independently checkpointed external scope
  targeting a canonical Collection Item.
- An `external_resources` row preserves the unique
  `(ingestion_source_id, external_id) -> item_id` mapping plus provider version,
  ETag, source URL, and last-seen state.
- `checkpoint` advances only after the complete ingestion source succeeds.
- Temporal owns schedules and execution history; PostgreSQL retains only domain
  checkpoint and last-ingested/indexed state.
- Updated Items replace their deterministic Qdrant points. Deleted Items are
  tombstoned; normal reads exclude tombstones.

The connector package's implementation notes are kept alongside the code in
[`backend/bothesis/connector/README.md`](../backend/bothesis/connector/README.md).
