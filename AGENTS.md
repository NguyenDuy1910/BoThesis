# BoThesis Agent Rules

## Project intent

BoThesis is an enterprise knowledge.

It connects to trusted enterprise sources, ingests and indexes knowledge, retrieves permission-filtered evidence, answers with grounded citations, and supports governed business analytics.

Keep implementations simple, explicit, typed, and aligned with the existing architecture.

---

## Source of truth

Before making any meaningful code change, inspect:

```text
/Users/nguyenduy/Documents/utex/BoThesis/backend/docs_design
```

This directory is the architectural source of truth for the project.

It includes design decisions for:

```text
OpenAPI contract
Database / DBML
Conversation and LLM agent loop
Authentication contract
RBAC / authorization
```

Always use the current documents in `docs_design` to understand the intended behavior before changing the implementation.

Do not design a competing architecture when the source of truth already defines one.

---

## Required workflow

For every implementation task:

```text
docs_design
    ↓
understand affected flow
    ↓
trace current implementation
    ↓
implement/change code
    ↓
verify affected flow
    ↓
update docs_design
```

Before editing code:

1. Read the relevant files in `backend/docs_design`.
2. Trace the existing implementation and affected callers.
3. Identify which documented contract or design owns the behavior.
4. Implement using that design.

After editing code:

1. Verify the changed behavior.
2. Determine whether the implementation changed any API, schema, lifecycle, architecture, auth, RBAC, agent flow, or important design decision.
3. Update the corresponding file(s) in `backend/docs_design`.
4. Ensure documentation and implementation describe the same final system.

Never leave:

```text
code != docs_design
```

after completing a task.

---

## Contract-first rule

For HTTP/API work:

```text
OpenAPI contract
    ↓
API boundary
    ↓
Application service
    ↓
Domain / persistence / infrastructure
```

The API contract is the source of truth for public behavior.

When implementing a new or changed endpoint:

* follow the existing OpenAPI contract;
* use resource-oriented REST APIs;
* keep request/response DTOs typed;
* keep routers thin;
* do not expose infrastructure implementation details;
* update the OpenAPI design document when the contract intentionally changes.

Do not preserve a legacy API merely because old services were built around it.

Refactor the implementation toward the canonical contract.

---

## Database rule

Use the DBML/database design in `docs_design` as the source of truth for persisted domain concepts and relationships.

Before changing:

```text
table
column
relationship
identifier
lifecycle state
tenant/workspace ownership
RBAC persistence
```

check the DB design first.

If the implementation requires a legitimate database design change:

```text
update DB design
+
migration/model
+
affected service code
```

as one coherent change.

Do not silently introduce a database structure that is absent from the documented design.

---

## Authentication and RBAC

Follow the authentication and RBAC contracts in `docs_design`.

Keep these concepts separate:

```text
Authentication
→ who the caller is

Workspace permission / RBAC
→ what capability the caller has

Resource ACL
→ which resource the caller may access

Platform permission
→ cross-workspace platform capability
```

Do not hard-code role names into business authorization.

Prefer stable permissions and documented authorization policies.

Authorization must be enforced before enterprise data reaches retrieval, the agent, or BI execution.

If auth or authorization behavior changes, update the corresponding `docs_design` contract.

---

## Agent / conversation flow

The documented conversation/LLM loop is the source of truth for agent orchestration.

Preserve the existing intelligent agent loop.

Do not turn the agent into a rigid workflow unless explicitly requested.

Keep:

```text
tool selection
retrieval
context building
citation grounding
agent reasoning loop
response streaming
```

aligned with the documented conversation architecture.

Temporal or other workflow infrastructure must not leak into the public agent contract unless explicitly designed there.

---

## Enterprise knowledge boundaries

Preserve:

```text
workspace / tenant boundary
permissions
source lineage
citations
audit information
resource lifecycle
```

Never return enterprise knowledge through retrieval or the agent without applying the required authorization filtering.

Factual enterprise answers that require grounding must preserve citation/source evidence.

Connector-specific behavior must remain isolated from core retrieval and agent orchestration.

---

## Service ownership

Before creating a new service/module, determine whether an existing component already owns the behavior.

Prefer:

```text
one canonical resource/lifecycle service
```

over services based on caller or screen.

Good:

```text
CollectionService
DocumentService
ItemIngestionService
ConnectionService
SourceService
```

Avoid:

```text
AdminCollectionService
AgentCollectionService
PageService
ApiService
```

Do not introduce parallel implementations of the same domain operation.

Reuse and consolidate existing flows where possible.

---

## Infrastructure boundaries

Keep infrastructure details behind their owning boundary.

Examples:

```text
connector provider code
→ connector adapters

durable binary content
→ storage

index/search implementation
→ document_index

authorization-aware retrieval
→ knowledge

cross-capability orchestration
→ services

Temporal
→ services.workflow

HTTP/FastAPI
→ backend/api
```

Do not expose infrastructure/vendor names through domain-facing APIs unless they are genuinely part of the domain.

---

## Lifecycle and deletion

Persisted business resources must not be physically deleted unless the documented design explicitly says otherwise.

Use the project's lifecycle/tombstone model, such as:

```text
status
deleted_at
```

Normal reads must exclude tombstoned resources where appropriate.

Deletion API semantics may still use HTTP `DELETE`; persistence implementation remains internal.

---

## Configuration and secrets

Parse environment configuration at the application/composition boundary.

Inject typed configuration into services.

Do not:

```text
read environment variables throughout domain services
create infrastructure clients ad hoc inside business logic
store secrets in source code
```

Use environment variables or the configured secret-management mechanism.

---

## Testing and verification

Tests belong under:

```text
/Users/duynguyen/Documents/vikki-bank-code/ai-team/BoThesis/tests
```

Reuse existing tests where possible.

Do not leave temporary test/debug files in application directories.

For each change, run the smallest verification that proves the affected flow works.

Examples:

```text
API change
→ API-level test + contract verification

retrieval change
→ permission filtering + citation verification

connector change
→ extraction + normalization + lineage verification

agent change
→ relevant conversation/tool flow

database change
→ affected persistence/service tests
```

---

## Documentation synchronization

Documentation maintenance is part of implementation, not a separate optional task.

After every meaningful change, check whether any file under:

```text
backend/docs_design
```

is affected.

Update it when changes affect:

```text
API contract
database model
authentication
RBAC
agent/conversation flow
resource lifecycle
service ownership
important architecture decisions
```

Keep documentation concise and architectural.

Do not document temporary implementation details unless they affect future design decisions.

At the end of each task, report:

```text
Code changed
Docs changed
Contract/design decisions changed
Tests/verification performed
Remaining decisions, if any
```

The final state must satisfy:

```text
docs_design
    ==
implemented architecture
    ==
runtime behavior
```

---

## General principle

When uncertain:

```text
read docs_design first
→ follow the existing source of truth
→ make the smallest coherent change
→ remove obsolete code when replaced
→ verify the affected path
→ update docs_design to match the final implementation
```

Do not create a new architectural direction silently.
