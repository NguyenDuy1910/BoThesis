<p align="center">
  <img src="web/public/bothesis-logo.png" alt="BoThesis" width="88" />
</p>

<h1 align="center">BoThesis</h1>

<p align="center">
  <strong>A grounded enterprise knowledge assistant for trusted, permission-aware answers.</strong>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="#development">Development</a>
</p>

BoThesis connects company knowledge to conversations without losing the things
that make enterprise answers trustworthy: tenant isolation, access control,
source lineage, and citations. It is an early-stage project designed around a
simple rule: the model reasons over evidence; it does not invent a source of
truth.

## What it provides

| Capability | How BoThesis approaches it |
| --- | --- |
| Grounded answers | Retrieves tenant-scoped evidence and returns citations back to canonical source Items. |
| Contextual hybrid retrieval | Uses contextual chunk text with dense embeddings and Qdrant BM25, fused for retrieval and filtered before evidence is exposed. |
| Governed ingestion | Ingests managed files and Confluence content through connector-owned normalization, ACL mapping, checkpoints, and retry-safe replacement. |
| Clear storage ownership | PostgreSQL holds business state; S3-compatible storage holds original bytes; Qdrant is a rebuildable retrieval projection. |
| Practical operations | Starts local PostgreSQL, Qdrant, and MinIO with one command and exposes readiness through `/health`. |

## Architecture

```text
HTTP / Web / Mobile
        │
        ▼
FastAPI · backend/main.py
        │
        ▼
Application services
        │
 ┌──────┼─────────────────────────┐
 ▼      ▼                         ▼
PostgreSQL   Connector + Docling   Document index
business     source understanding  contextualization + embeddings
state        ACL + chunks                    │
 │                                           ▼
 └─────────────── S3 / R2 ◀────────────── Qdrant
                 original bytes          retrieval projection
                                              │
                                              ▼
                                      Knowledge → evidence → agent
```

The HTTP boundary stays in `backend/main.py`. Route handlers resolve request
context, call a service, and return a response. Services own application flow;
connectors, storage adapters, Docling, Qdrant, and PostgreSQL stay behind that
boundary.

| System | Owns |
| --- | --- |
| PostgreSQL | identities, tenants, connectors, encrypted credentials, Items, ACL state, chat state, sync history, and audit records |
| S3 / Cloudflare R2 / MinIO | original document bytes |
| Docling | conversion, normalization, provenance, and chunking |
| Qdrant | searchable contextual chunks, vectors, and retrieval filter payload |
| `knowledge` | permission filtering, retrieval, reranking, and evidence |
| `agent` | tool-aware reasoning and cited answers |

Read the full design in [Architecture](docs/architecture.md) and
[Storage ownership and data model](docs/data.schema.md).

## Repository guide

```text
backend/
├── main.py                    FastAPI routes and HTTP dependencies
└── bothesis/
    ├── services/              Application use cases and transactions
    ├── connector/             Confluence/file adapters, Docling, sync pipeline
    ├── document_index/        Contextualization, embeddings, Qdrant projection
    ├── knowledge/             Retrieval, ACL filtering, evidence, reranking
    ├── agent/                 Conversation loop, tools, model transports
    ├── db/                    SQLAlchemy models and database engine
    └── tui/                   Terminal chat client
web/                           Next.js workspace for chat and administration
app/bothesis/                  Flutter client scaffold
deployment/                    Local PostgreSQL, Qdrant, and MinIO Compose stack
docs/                          Architecture, setup, operations, and reference docs
tests/                         Backend and integration tests
```

## Quick start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose
- Node.js 20+ and npm
- An OpenAI API key for chat and an OpenRouter API key for embeddings

### 1. Install and initialize local dependencies

```bash
git clone <your-fork-or-repository-url>
cd BoThesis

uv sync --project backend
npm --prefix web ci
make init
```

`make init` creates missing local environment files, starts PostgreSQL, Qdrant,
and MinIO, creates the raw-object bucket, rebuilds the local database schema,
seeds a development administrator, and recreates the derived Qdrant collection.

> **Local-development reset:** `make init` intentionally resets the PostgreSQL
> schema and Qdrant collection. Do not use it against an environment with data
> you need to retain.

### 2. Configure model access

Set the required provider keys in `backend/.env`:

```dotenv
OPENAI_API_KEY=...
OPENROUTER_API_KEY=...
```

The local dependency endpoints, object-storage settings, development identity,
and generated plugin-credential encryption key are configured by `make init`. See
[Configuration and operations](docs/operations.md) for every setting and for
S3 or Cloudflare R2 deployments.

### 3. Start the API and WebUI

In one terminal:

```bash
cd backend
uv run python main.py
```

In another:

```bash
npm --prefix web run dev
```

Open:

| Service | Address |
| --- | --- |
| WebUI | [http://127.0.0.1:3000](http://127.0.0.1:3000) |
| API | [http://127.0.0.1:8000](http://127.0.0.1:8000) |
| OpenAPI | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| Health | [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) |
| Qdrant dashboard | [http://127.0.0.1:6333/dashboard](http://127.0.0.1:6333/dashboard) |
| MinIO console | [http://127.0.0.1:9001](http://127.0.0.1:9001) |

## Documentation

| Guide | Use it for |
| --- | --- |
| [Documentation index](docs/README.md) | Finding the right guide by responsibility. |
| [Getting started](docs/getting-started.md) | Local setup, reset behavior, and development identity. |
| [Architecture](docs/architecture.md) | Package ownership, request flow, and infrastructure boundaries. |
| [Connectors and indexing](docs/connectors-and-indexing.md) | Connector scopes, Docling, contextual hybrid retrieval, ACL projection, and retries. |
| [Operations and configuration](docs/operations.md) | Environment variables, health checks, object storage, observability, and troubleshooting. |
| [Data schema](docs/data.schema.md) | Canonical `Item` model and durable storage ownership. |
| [Agent architecture](docs/references/agent-loop.md) | OpenResponses stream, tools, response lifecycle, and citation projection. |

The interactive API contract is generated by FastAPI at `/docs`; it is the
authoritative reference for request and response schemas.

## Development

Useful local targets:

```bash
make help        # list all targets
make services    # start PostgreSQL, Qdrant, and MinIO
make status      # inspect dependency state and API health
make db-init     # reset only the local PostgreSQL schema
make db-seed     # seed the development administrator
make db-reset    # reset PostgreSQL and seed the development administrator
make qdrant-init # recreate only the derived Qdrant collection
```

Run the verification suite from the repository root:

```bash
uv run --project backend pytest -q tests
npm --prefix web test
npm --prefix web run typecheck
npm --prefix web run build
```

The terminal client is available after the API is running:

```bash
cd backend
uv run python -m bothesis.tui
```

## Security and deployment notes

- Never commit `.env` files, provider credentials, encryption keys, or signed
  object URLs.
- `BOTHESIS_ALLOW_INSECURE_DEV_IDENTITY=true` is strictly for local development.
  Production must inject authenticated identity from trusted middleware.
- Connector credentials are encrypted at rest; retrieval authorization is based
  on Item ACLs, not on the connector's provider credential.
- S3/R2 object storage is mandatory for raw bytes. PostgreSQL does not store
  document blobs; Qdrant does not hold canonical business state.

For deployment and operational detail, start with
[Operations and configuration](docs/operations.md).

## Project status

BoThesis is in active early development. The schema is initialized directly
from the current ORM models and is intentionally optimized for the present
architecture rather than backwards compatibility. Expect APIs and connectors to
evolve; preserve the core invariants of tenant isolation, ACL enforcement,
source lineage, and grounded citations when extending the project.
