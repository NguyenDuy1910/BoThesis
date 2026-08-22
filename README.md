# BoThesis

BoThesis is an enterprise knowledge and BI assistant. It retrieves information
from permission-scoped company sources, answers with citations, and streams
agent activity and final responses to a web chat interface.

## Architecture

```text
Next.js chat UI
    ↓ Server-Sent Events (SSE)
FastAPI agent API
    ↓
Adaptive agent loop ──→ OpenRouter chat model
    ↓
Knowledge tools ──────→ OpenRouter embeddings ──→ Qdrant
    ↓
Grounded answer + citations

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

Prerequisites: Python 3.12+, [uv](https://docs.astral.sh/uv/), Node.js, npm,
an OpenRouter API key, and a reachable Qdrant collection.

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
DATABASE_URL=postgresql+asyncpg://bothesis:bothesis@127.0.0.1:5432/bothesis
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=bothesis
QDRANT_API_KEY=  # set a key only when authentication is enabled
```

Chat document uploads can use AWS S3 or Cloudflare R2 through the same boto3
S3-compatible adapter.
The browser uploads bytes directly to its presigned URL; configure the bucket's
CORS policy to allow `PUT` from the WebUI origin with the `Content-Type` header.
Without object storage, the API permits a PostgreSQL blob fallback up to 20 MiB.
Set `BOTHESIS_OBJECT_STORAGE_PROVIDER` to select the provider. AWS credentials
are resolved through boto3's standard credential chain. For local development,
use `aws configure`, `AWS_PROFILE`, or the normal `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` environment variables. In AWS, prefer a container or
instance role.

```dotenv
BOTHESIS_S3_BUCKET=bothesis-documents
BOTHESIS_S3_REGION=us-east-1
# Optional for local S3-compatible development endpoints only:
BOTHESIS_S3_ENDPOINT_URL=
BOTHESIS_S3_ADDRESSING_STYLE=auto
BOTHESIS_DOCUMENT_MAX_UPLOAD_BYTES=104857600
BOTHESIS_DOCUMENT_MAX_DATABASE_BLOB_BYTES=20971520
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

### Database migrations

BoThesis uses numbered SQL migrations in `backend/migrations/` rather than
Alembic. Start the local PostgreSQL service from the repository root:

```bash
docker compose -f deployment/compose.yml up -d postgres
```

For a completely fresh database, create the base tables once from the SQLAlchemy
models. Run this from `backend/` so the local `.env` file is loaded:

```bash
cd backend

uv run python - <<'PY'
import asyncio
from dotenv import load_dotenv
from bothesis.db.engine import get_engine
from bothesis.db.models import Base

load_dotenv()

async def main():
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()

asyncio.run(main())
PY

cd ..
```

Apply all numbered migrations in order:

```bash
set -e

for migration in backend/migrations/*.sql; do
  docker compose -f deployment/compose.yml exec -T postgres \
    sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    < "$migration"
done
```

If a migration reports that a core table such as `documents` or `tenants` does
not exist, run the fresh-database initialization above first, then rerun this
migration loop.

The migration scripts are idempotent and can be run again safely against the
same database.

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

For the single-tenant Phase 1 dataset only, development admins can query
legacy Qdrant points that do not carry the current database tenant UUID:

```dotenv
BOTHESIS_PHASE1_UNSCOPED_RETRIEVAL=true
```

This setting requires insecure development identity mode, remains disabled by
default, and must never be enabled in a shared or production environment.

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
