# Operations and configuration

This guide describes operational settings for a local environment and the
boundaries that must be configured explicitly in deployment. Start with
[Getting started](getting-started.md) for local bootstrap.

## Environment files

| File | Purpose |
| --- | --- |
| `backend/.env.example` | Complete backend configuration template. Copy values into ignored `backend/.env`. |
| `web/.env.example` | Public WebUI configuration template. Local setup creates ignored `web/.env.local`. |
| `deployment/compose.yml` | Local PostgreSQL, Qdrant, and MinIO topology. Optional Compose overrides go in ignored `deployment/.env`. |

Do not commit credentials, encryption keys, signed object URLs, or deployment
environment files.

## Required model configuration

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini

OPENROUTER_API_KEY=...
OPEN_ROUTER_BASE_URL=https://openrouter.ai/api/v1
EMBEDDING_MODEL=openai/text-embedding-3-small
```

OpenAI serves the chat path. OpenRouter serves embedding requests. Health
reports each dependency separately so a missing key is visible as an unhealthy
required service instead of a silent fallback.

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

## Identity and credentials

```dotenv
# Exactly 32 URL-safe base64-decoded bytes; generate once and retain securely.
BOTHESIS_PLUGIN_ENCRYPTION_KEY=...

# Local development only. Never enable this in deployment.
BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY=true
```

Plugin provider credentials are encrypted before they are written to
`plugin_credentials`. They are not Item metadata, Qdrant payload, frontend
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
