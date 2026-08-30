# Temporal runtime

BoThesis uses Temporal as the durable runtime for the single end-to-end
`IngestionWorkflow`. PostgreSQL stores connector and Item domain state; it does
not mirror Workflow executions or schedules.

## Local setup

The local Compose stack runs Temporal on `127.0.0.1:7233` and its UI on
`127.0.0.1:8080`. `make services` starts them and idempotently registers the
Keyword Search Attributes used by the admin visibility endpoints:

```bash
make services
```

Run the API and worker as separate processes:

```bash
cd backend
uv run python main.py
uv run python -m bothesis.workflow.worker
```

For Temporal Cloud, set `BOTHESIS_TEMPORAL_TARGET`,
`BOTHESIS_TEMPORAL_NAMESPACE`, `BOTHESIS_TEMPORAL_API_KEY`, and
`BOTHESIS_TEMPORAL_TLS=true`, and create the same Search Attributes in the
target namespace.

## Concurrency and retry behavior

Every ingestion source uses `ingestion:<source_id>` as its Workflow ID. Manual starts
fail on an open execution and return the existing run instead of starting a
second writer. Temporal Schedules default to `SKIP`, so a scheduled tick is
skipped while the previous scheduled execution is open. The Workflow ID also
protects scheduled-versus-manual races.

The ingestion Activity retries transient failures up to five attempts with
bounded exponential backoff and emits heartbeats every 30 seconds. Invalid
configuration, permission failures, and deterministic per-item validation
failures are non-retryable. Item IDs, vector point IDs, Qdrant upserts, soft
deletes, and checkpoint advancement are already retry-safe.

For very large sources, first add connector pagination and bounded batches
inside the existing pipeline. Add Continue-As-New only when measured Workflow
history approaches service limits; the current design records one Activity per
ingestion, so item count does not grow Workflow history. Child Workflows are
reserved for a future need to fan out independently scalable partitions.
