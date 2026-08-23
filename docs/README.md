# BoThesis documentation

This directory contains the durable project documentation. Keep the root
[README](../README.md) focused on orientation and a working quick start; place
design decisions, operational procedures, and package-level detail here.

## Start here

| Document | Scope |
| --- | --- |
| [Getting started](getting-started.md) | Local dependencies, initialization, development identity, and reset behavior. |
| [Architecture](architecture.md) | HTTP boundary, package ownership, request flow, and infrastructure responsibilities. |
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
