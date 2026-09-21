# Enterprise Agent documentation

This directory contains operational and architecture documentation. API design
ownership lives in [`backend/docs_design`](../backend/docs_design), so do not
create a second API contract here.

## Start here

| Document | Scope |
| --- | --- |
| [Getting started](getting-started.md) | Local dependencies, initialization, development identity, and reset behavior. |
| [Architecture](architecture.md) | HTTP boundary, package ownership, request flow, and infrastructure responsibilities. |
| [API contract](../backend/docs_design/api_contract.md) | Versioned routes, DTO rules, auth/session semantics, errors, and lifecycle contract. |
| [OpenAPI snapshot](../backend/docs_design/openapi.yaml) | Checked-in OpenAPI 3.1 contract generated from the FastAPI application. |
| [Database architecture](../backend/docs_design/database_architecture.md) | Tenant boundaries, identity/session separation, Item lineage, storage ownership, and ID/index policy. |
| [Connectors and indexing](connectors-and-indexing.md) | Source hierarchy, Docling processing, contextual hybrid indexing, deletion, ACLs, and checkpoint semantics. |
| [Operations and configuration](operations.md) | Environment configuration, object storage, health checks, observability, testing, and common local failures. |

## Reference material

| Document | Scope |
| --- | --- |
| [Data schema](data.schema.md) | Storage ownership and the canonical `items` data model. |
| [Schema packet](data.schema.packet.json) | Machine-readable companion to the storage architecture. |
| [Agent architecture](references/agent-loop.md) | OpenResponses protocol, streaming lifecycle, tools, and citation projection. |

## Documentation principles

- Code is authoritative for behavior; update the nearest relevant document in
  the same change when an interface or architectural boundary changes.
- Document ownership and operational decisions here, not in `main.py` or
  package implementation modules.
- Do not place credentials, signed URLs, tenant data, or production-only
  configuration values in documentation.
