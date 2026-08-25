# Getting started

This guide prepares a local BoThesis environment for backend, WebUI, and
connector development.

## Prerequisites

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose
- Node.js 20 or newer with npm
- An OpenAI API key for chat and an OpenRouter API key for embeddings

The Flutter app under `app/bothesis/` is optional. It needs a current Flutter
SDK only when you are working on the mobile client.

## Initialize the local stack

From the repository root:

```bash
uv sync --project backend
npm --prefix web ci
make init
```

`make init` performs the complete local bootstrap:

1. Creates `backend/.env` and `web/.env.local` when missing.
2. Writes local dependency endpoints and the development identity.
3. Starts PostgreSQL, Qdrant, and MinIO.
4. Creates the configured MinIO bucket.
5. Rebuilds PostgreSQL from the current SQLAlchemy models.
6. Seeds a deterministic local administrator and membership.
7. Recreates the derived Qdrant collection with dense and BM25 vectors.

The command is deliberately destructive to local derived and database state.
It drops the PostgreSQL `public` schema and replaces the Qdrant collection.
Never run it against retained data.

## Configure providers

Add provider credentials to `backend/.env` before running a chat or embedding
workflow:

```dotenv
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
```

The remaining local settings are maintained by `make config`. For production
or a non-local object store, use [Operations and configuration](operations.md).

## Run the applications

Start the API:

```bash
cd backend
uv run python main.py
```

Start the WebUI in a separate terminal:

```bash
npm --prefix web run dev
```

The local WebUI uses the seeded identity from `web/.env.local`. The API accepts
it only while `BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY=true`; it is not an
authentication mechanism for deployment.

### Run the WebUI with review data only

For UX review without the backend or provider credentials, set this in
`web/.env.local` and restart the Next.js development server:

```dotenv
NEXT_PUBLIC_BOTHESIS_DATA_MODE=mock
```

Mock mode populates chat, citations, knowledge bases, connectors, documents,
sync history, people, access controls, and audit activity. Admin mutations
reset after a full page reload; demo chat history is kept in browser storage.
Set the value back to `api` to use the real backend; API mode still requires
the URL, tenant, and user values documented in `web/.env.example`.

## Local service endpoints

| Service | URL |
| --- | --- |
| WebUI | `http://127.0.0.1:3000` |
| FastAPI | `http://127.0.0.1:8000` |
| OpenAPI | `http://127.0.0.1:8000/docs` |
| Health | `http://127.0.0.1:8000/health` |
| Qdrant | `http://127.0.0.1:6333` |
| MinIO console | `http://127.0.0.1:9001` |

## Useful reset boundaries

```bash
make services     # dependencies only
make db-init      # PostgreSQL schema only; destructive
make db-seed      # deterministic admin identity only
make db-reset     # PostgreSQL schema plus deterministic admin identity
make qdrant-init  # Qdrant collection only; destructive
make status       # Compose status and API health
```

Use `make db-reset` after changing SQLAlchemy models. It starts missing local
services, rebuilds PostgreSQL from the current ORM metadata, and restores the
development administrator without recreating Qdrant.

For the ownership implications of these resets, see
[Architecture](architecture.md) and [Data schema](data.schema.md).
