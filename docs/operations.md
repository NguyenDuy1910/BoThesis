# Operations and configuration

This guide describes operational settings for a local environment and the
boundaries that must be configured explicitly in deployment. Start with
[Getting started](getting-started.md) for local bootstrap.

## Environment files

| File | Purpose |
| --- | --- |
| `backend/.env.example` | Complete backend configuration template. Copy values into ignored `backend/.env`. |
| `web/.env.example` | Public WebUI configuration template. Local setup creates ignored `web/.env.local`. |
| `deployment/compose.yml` | Local PostgreSQL, Qdrant, MinIO, and Temporal topology. Optional Compose overrides go in ignored `deployment/.env`. |

Do not commit credentials, encryption keys, signed object URLs, or deployment
environment files.

## Required model configuration

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini

OPENROUTER_API_KEY=...
OPEN_ROUTER_BASE_URL=https://openrouter.ai/api/v1
BOTHESIS_DOCLING_MODEL=qwen/qwen3-vl-30b-a3b-instruct
EMBEDDING_MODEL=openai/text-embedding-3-small
```

OpenAI serves the chat path. OpenRouter serves embedding requests and Docling's
remote vision pipeline for PDF and image ingestion. PDF/image pages are sent to
`BOTHESIS_DOCLING_MODEL`, which returns grounded text and table blocks with page
coordinates for citation provenance. No Docling layout, OCR, table, or tokenizer
model is loaded locally. Health reports each dependency separately so a missing
key is visible as an unhealthy required service instead of a silent fallback.

## Document index configuration

```dotenv
QDRANT_URL=http://127.0.0.1:6333
QDRANT_COLLECTION=bothesis
QDRANT_API_KEY=
QDRANT_PREFER_GRPC=false

BOTHESIS_CONTEXTUALIZATION_ENABLED=false
BOTHESIS_CONTEXTUALIZATION_MODEL=
BOTHESIS_HYBRID_CANDIDATE_LIMIT=20
```

The local Qdrant collection has one dense vector named `content` and one sparse
BM25 vector named `content_bm25`. It is derived state and can be recreated with
`make qdrant-init`.

## Object storage

Raw document storage is mandatory. Configure one S3-compatible provider:

```dotenv
BOTHESIS_OBJECT_STORAGE_PROVIDER=aws_s3
BOTHESIS_OBJECT_STORAGE_BUCKET=bothesis
BOTHESIS_S3_REGION=us-east-1
BOTHESIS_S3_ENDPOINT_URL=http://127.0.0.1:9000
BOTHESIS_S3_ADDRESSING_STYLE=path
```

AWS S3 uses boto3's standard credential chain. Cloudflare R2 uses its
S3-compatible endpoint and API-token access key pair:

```dotenv
BOTHESIS_OBJECT_STORAGE_PROVIDER=cloudflare_r2
BOTHESIS_R2_BUCKET=...
BOTHESIS_R2_ACCOUNT_ID=...
BOTHESIS_R2_ACCESS_KEY_ID=...
BOTHESIS_R2_SECRET_ACCESS_KEY=...
```

Never persist a presigned URL. Store the Item's `storage_key` and generate a
short-lived upload or download URL only at runtime. When using MinIO, the S3
access key and secret in `backend/.env` must match the MinIO root credentials
used by Compose; a `SignatureDoesNotMatch` response means they do not match.

Image and PDF ingestion may also write versioned WebP objects below the owning
Item's `previews/` prefix. These are derived presentation assets; the raw object
remains authoritative. Bound rendering with `BOTHESIS_PREVIEW_MAX_SOURCE_BYTES`,
`BOTHESIS_PREVIEW_MAX_PAGES`, `BOTHESIS_PREVIEW_MAX_DIMENSION`, and
`BOTHESIS_PREVIEW_WEBP_QUALITY`. Preview URLs are signed at read time and use
`BOTHESIS_PREVIEW_URL_SECONDS`.

## Conversation artifacts and the sandbox

Documents the assistant drafts or revises are edited inside a disposable Docker
container, never on the API host. The API talks to the local Docker daemon
through the standard `DOCKER_HOST` / socket; build the image once with
`make sandbox-image` (part of `make init`).

```dotenv
BOTHESIS_SANDBOX_IMAGE=bothesis-sandbox:local
BOTHESIS_SANDBOX_TIMEOUT_SECONDS=30
BOTHESIS_SANDBOX_MEMORY_BYTES=268435456
BOTHESIS_SANDBOX_CPUS=1
BOTHESIS_SANDBOX_PIDS_LIMIT=64
BOTHESIS_SANDBOX_MAX_OUTPUT_BYTES=20971520

BOTHESIS_ARTIFACT_MAX_CONTENT_BYTES=2097152
BOTHESIS_ARTIFACT_CONTEXT_CHARACTERS=20000
BOTHESIS_ARTIFACT_RESULT_CHARACTERS=8000
BOTHESIS_ARTIFACT_DOWNLOAD_URL_SECONDS=300
```

Every container runs as an unprivileged user with networking disabled, memory
and swap capped, CPU and pid limits, all capabilities dropped,
`no-new-privileges`, a read-only root filesystem, and no environment beyond
Python hygiene: no application, database, or cloud credential reaches it. The
workspace goes in and comes out as a tar stream, so nothing is bind-mounted.
Keep `BOTHESIS_TOOL_TIMEOUT_SECONDS` above `BOTHESIS_SANDBOX_TIMEOUT_SECONDS`
so an operation can report its own outcome. Revisions are stored under
`tenants/<tenant>/items/<artifact>/revisions/<n>/` in object storage; the
`artifact_revisions` table records them.

Templates are the documents of any Collection whose metadata has
`template_library: true` (the collection creation dialog offers this flag).

## Identity and credentials

```dotenv
# Exactly 32 URL-safe base64-decoded bytes; generate once and retain securely.
BOTHESIS_INTEGRATION_ENCRYPTION_KEY=...

# Local development only. Never enable this in deployment.
BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY=true
```

Integration credentials are encrypted before they are written to
`integration_credentials`. They are not Item metadata, Qdrant payload, frontend
configuration, or audit-log content.

## Health and observability

`GET /health` reports API, Qdrant, OpenAI chat, OpenRouter embeddings, and
optional Langfuse availability. It reports `healthy`, `degraded`, or
`unhealthy` without exposing credentials.

Langfuse tracing is optional:

```dotenv
LANGFUSE_SECRET_KEY=...
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
OTEL_SERVICE_NAME=bothesis-api
```

Both Langfuse keys are required. Keep trace retention and access policies
appropriate for potentially sensitive prompts, outputs, and retrieved content.

## Verification

```bash
make status
uv run --project backend pytest -q tests
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

`make reset-all` is the complete local data reset. It clears application and
Temporal persistence, reapplies the current SQLAlchemy database design, seeds
the local administrator, and recreates the Qdrant collection while retaining
raw MinIO objects.

For the running API, use `http://127.0.0.1:8000/docs` as the authoritative
request and response reference.

## Common local failures

| Symptom | Check |
| --- | --- |
| `relation "users" does not exist` | Run `make db-init` and `make db-seed`; confirm `DATABASE_URL` points to local PostgreSQL. |
| `SignatureDoesNotMatch` during upload | Align `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` with MinIO's `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`, then restart the API. |
| `MissingGreenlet` while listing datasources | Ensure the API was restarted after the datasource service update; the list query eager-loads connector credentials. |
| Qdrant schema is incompatible | Run `make qdrant-init`; it recreates the local derived collection. |
| `/health` is degraded | Inspect the individual service entries for missing provider credentials or unreachable dependencies. |
