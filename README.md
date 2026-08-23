# BoThesis

BoThesis is an enterprise knowledge and BI assistant. It retrieves information
from permission-scoped company sources, answers with citations, and streams
agent activity and final responses to a web chat interface.

## Architecture

```text
HTTP → FastAPI (`backend/main.py`) → services
                                  ↓
PostgreSQL ── durable identity, Item, connector, ACL, and chat state
R2 / S3 ──── original document bytes
Docling ──── document understanding and canonical chunks
Qdrant ───── contextual embeddings, retrieval payload, and ACL projection
Knowledge ── permission filtering, retrieval, reranking, and evidence
Agent ────── reasoning and grounded answers with citations

Agent, model, retrieval, and tool traces ───────→ Langfuse (optional)
```

Simple questions use the direct-answer path. Complex or tool-dependent requests
can create a small plan, execute independent steps concurrently, refine one weak
step once, and then stream the final answer.

## Project structure

```text
backend/
├── main.py                         FastAPI application and API routes
└── bothesis/
    ├── agent/                      Models, prompts, tools, and LLM transports
    ├── chat/                       Agent loop, state, SSE, and citations
    ├── connector/                  Source adapters and ingestion pipeline
    ├── document_index/             Qdrant vector-store integration
    ├── knowledge/                  Permission-aware semantic retrieval
    ├── access/ and auth/           Access-control boundaries
    └── observability.py            Langfuse tracing
web/
└── src/
    ├── app/                        Next.js routes
    ├── modules/chat/               Stream parser and chat activity UI
    └── modules/admin/              Administration UI
tests/                              Backend agent and API tests
benchmark/                          Benchmark utilities
deployment/                         Deployment assets
docs/                               Project documentation
```

## Quick start

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Docker,
Node.js, npm, and an OpenRouter API key.

Initialize PostgreSQL, Qdrant, local S3-compatible object storage, the database
schema, the raw-object bucket, and a development admin identity with one
command:

```bash
make init
```

This command intentionally rebuilds the early-development PostgreSQL schema and
the derived Qdrant collection. It does not preserve local data.

### Backend

```bash
cd backend
cp .env.example .env
uv sync
uv run python main.py
```

Edit `backend/.env` before starting. At minimum, configure:

```dotenv
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5-mini
OPENROUTER_API_KEY=...  # document embeddings
EMBEDDING_MODEL=openai/text-embedding-3-small
BOTHESIS_CONTEXTUALIZATION_ENABLED=false
BOTHESIS_CONTEXTUALIZATION_MODEL=
BOTHESIS_HYBRID_CANDIDATE_LIMIT=20
DATABASE_URL=postgresql+asyncpg://bothesis:bothesis@127.0.0.1:5432/bothesis
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=bothesis_v6
QDRANT_API_KEY=  # set a key only when authentication is enabled
BOTHESIS_OBJECT_STORAGE_PROVIDER=aws_s3
BOTHESIS_OBJECT_STORAGE_BUCKET=bothesis-raw
BOTHESIS_CONNECTOR_ENCRYPTION_KEY=  # URL-safe base64 for exactly 32 bytes
```

The v6 document index stores `contextual_text` in both the dense `content`
vector and Qdrant's native BM25 `content_bm25` sparse vector, then combines
both filtered candidate sets with reciprocal-rank fusion. Semantic chunk
context is optional; when disabled or unavailable, indexing falls back to the
document summary without changing canonical `chunk_text` evidence.

Qdrant is derived state. `make init` recreates the local collection; connector
checkpoints and deterministic per-Item point IDs make normal retries safe.

Raw object storage is mandatory. Chat uploads and provider-downloaded binary
files use AWS S3 or Cloudflare R2 through the same boto3 S3-compatible adapter.
The browser uploads bytes directly to its presigned URL; configure the bucket's
CORS policy to allow `PUT` from the WebUI origin with the `Content-Type` header.
Set `BOTHESIS_OBJECT_STORAGE_PROVIDER` to select the provider. AWS credentials
are resolved through boto3's standard credential chain. For local development,
`make init` configures MinIO and local credentials. In AWS, prefer a container
or instance role.

```dotenv
BOTHESIS_OBJECT_STORAGE_BUCKET=bothesis-documents
BOTHESIS_S3_BUCKET=bothesis-documents  # optional provider-specific override
BOTHESIS_S3_REGION=us-east-1
# Optional for local S3-compatible development endpoints only:
BOTHESIS_S3_ENDPOINT_URL=
BOTHESIS_S3_ADDRESSING_STYLE=auto
BOTHESIS_DOCUMENT_MAX_UPLOAD_BYTES=104857600
BOTHESIS_DOCUMENT_DIRECT_MAX_BYTES=20971520
```

For Cloudflare R2, create an R2 API token with S3 credentials and configure its
access key and secret through your deployment secret manager. R2 is configured
with its account endpoint, `auto` signing region, and path-style addresses by
the adapter; no Cloudflare SDK is used.

```dotenv
BOTHESIS_OBJECT_STORAGE_PROVIDER=cloudflare_r2
BOTHESIS_R2_BUCKET=bothesis-documents
BOTHESIS_R2_ACCOUNT_ID=your-cloudflare-account-id
BOTHESIS_R2_ACCESS_KEY_ID=...
BOTHESIS_R2_SECRET_ACCESS_KEY=...
# Optional: override the endpoint derived from the account ID.
BOTHESIS_R2_ENDPOINT_URL=
```

The API starts at `http://127.0.0.1:8000`.

### Initial database schema

The project is in initial development and has no migration compatibility
layer. The SQLAlchemy models define the complete intended schema directly.
Rebuild all local dependencies, schema, and seed data from the repository root:

```bash
make init
```

The individual targets remain available for diagnostics:

```bash
make services
make db-init
make db-seed
make qdrant-init
make status
```

`make db-init` drops and recreates the local `public` schema. `make qdrant-init`
recreates the configured derived collection. Raw binary content is never stored
in PostgreSQL; the `items` table stores only durable object metadata such as
`storage_key`, MIME type, size, and SHA-256.

- Health: `http://127.0.0.1:8000/health`
- OpenAPI: `http://127.0.0.1:8000/docs`
- Chat stream: `POST http://127.0.0.1:8000/api/v1/agent/chat`

### Terminal chat client

After `uv sync`, run the lightweight Textual client from `backend/`:

```bash
uv run python -m bothesis.tui
```

It talks only to the running API at `BOTHESIS_API_URL` (default
`http://127.0.0.1:8000`) and defaults to the local streaming-test user UUID
used by the WebUI. Set `BOTHESIS_USER_ID` (and optionally
`BOTHESIS_TENANT_ID`) to use a different development identity. Use Ctrl+Enter
to send a multiline message. `/clear` starts a new conversation, `/raw`
toggles the receive-order SSE log, and `/exit` or `/quit` closes the client.
An authenticated deployment can instead use `BOTHESIS_ACCESS_TOKEN` or the
matching command-line options.

### Frontend

In another terminal:

```bash
cd web
cp .env.example .env.local
npm ci
npm run dev
```

For local development only, enable UUID identity resolution in `backend/.env`:

Boolean environment settings use strict JSON boolean values.

```dotenv
BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY=true
```

Then set database-backed user and tenant UUIDs in `web/.env.local`:

```dotenv
NEXT_PUBLIC_BOTHESIS_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_BOTHESIS_TENANT_ID=00000000-0000-0000-0000-000000000001
NEXT_PUBLIC_BOTHESIS_USER_ID=00000000-0000-0000-0000-000000000002
```

Open `http://localhost:3000`.

## Langfuse tracing

Tracing is optional. Create or select a project in the
[Langfuse Cloud dashboard](https://cloud.langfuse.com), then add its credentials
to `backend/.env`:

```dotenv
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_TRACING_ENVIRONMENT=development
OTEL_SERVICE_NAME=bothesis-api
```

Both keys are required. Tracing stays disabled when neither is configured; a
partial configuration logs a warning and also leaves tracing disabled. For
self-hosted Langfuse, replace
`LANGFUSE_BASE_URL` with the approved instance URL. See the official
[Langfuse tracing setup](https://langfuse.com/docs/observability/get-started)
and [environment documentation](https://langfuse.com/docs/observability/features/environments).

BoThesis records agent runs, model generations, structured capabilities,
retrieval, tool execution, latency, and token usage. Traces can include user
requests, model responses, and retrieved enterprise content. Use an approved
project with suitable retention and access controls; never commit Langfuse keys.

## Tests

From the repository root:

```bash
uv run --project backend pytest -q tests
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

Connector tests are colocated with the connector package:

```bash
cd backend
uv run python -m pytest -q
```

## Security notes

- Tenant, user, role, lineage, permission, and citation data must remain intact
  through retrieval and agent execution.
- The frontend identity values are temporary development configuration, not a
  production authentication mechanism.
- Keep all API keys in local environment files or a secret manager. Do not
  commit `.env` files.
