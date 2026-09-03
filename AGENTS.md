# BoThesis Agent Rules

## Project intent
BoThesis is an enterprise knowledge and BI assistant. It connects to trusted company sources, indexes domain knowledge, answers with grounded citations, and helps users analyze business data.

Primary source types:
- Confluence
- Jira
- Slack
- PDF documents
- Google Drive
- Databases and datalake assets

## Working rules
- Keep the structure simple. Do not redesign folders unless the user asks.
- Prefer small, explicit modules over framework-heavy abstractions.
- Preserve enterprise boundaries: tenant, permission, source lineage, audit, and citation data must not be lost.
- Never answer from enterprise knowledge without source grounding when the feature requires factual output.
- Treat connectors as isolated adapters. Connector-specific code must not leak into retrieval, BI, or agent orchestration.
- Treat BI as governed analytics: metric definitions, SQL generation, validation, and data lineage must be explicit.
- Do not add mocks, placeholders, fake fallbacks, or TODO implementations as completed work.
- Avoid storing secrets in the repo. Use environment variables or secret managers.

## Coding rules
- Reuse existing patterns before adding new ones.
- Keep public interfaces stable and typed.
- Parse boolean configuration once at the application composition boundary,
  then pass typed `bool` values into services. Never use ad-hoc truthy string
  comparisons or collections.
- Never physically delete persisted business data, raw document objects,
  provider references, or vector points. Delete actions must use a lifecycle
  status or `deleted_at` tombstone, and normal reads must exclude tombstones.
- Each `backend/bothesis/<package>/<name>.py` module defines only its primary
  class or object for that module. Put shared contexts, DTOs, errors, and
  package-level constants in that package's `__init__.py`, and import them
  through the `bothesis.<package>` package boundary. This applies to all
  packages: `agent`, `chat`, `connector`, `document_index`, `services`, and
  `storage`, including their sub-packages. (Example: `services/auth.py` defines
  only `AuthService`; shared service types live in `services/__init__.py`.)
- Separate ingestion, indexing, retrieval, agent orchestration, and BI logic.
- Validate inputs at API boundaries.
- Enforce permissions before retrieval results or BI data reach the agent.
- Log operational events without leaking private content or secrets.

## Item knowledge architecture
- Read the current architecture and every affected call site before adding or
  moving ingestion, indexing, or retrieval code.
- Treat the existing `Item` model as the canonical identity and lifecycle
  contract. Reuse its collection hierarchy, source lineage, chunks, previews,
  assets, citations, metadata, and tombstone semantics.
- Extend an existing cohesive component before creating another file or class.
  Explain why each new file is required by a current behavior.
- Keep user-action and cross-capability orchestration in `bothesis/services`.
  `ItemIngestionService` owns Item persistence, processing order, status
  transitions, citations, previews, reprocessing, and removal coordination.
- Keep only Item content indexing, searching, replacement, and tombstoning in
  `bothesis/document_index`. Storage payloads and vendor clients must remain
  private implementation details.
- Keep durable binary object access in `bothesis/storage`; parsing, Item
  lifecycle orchestration, and indexed-content behavior belong elsewhere.
- Keep tenant/authorization scoping, retrieval filtering, ranking, reranking,
  evidence construction, and context budgeting in `bothesis/knowledge`.
- Domain and application layers must never import or call vector database SDKs
  directly. Domain-facing APIs and filenames must not expose vendor or
  infrastructure terms such as Qdrant, vector store, or sink.
- Do not design ingestion or retrieval as one class or file per step. Prefer a
  single cohesive capability with only the small supporting types required by
  current behavior.
- Never add compatibility wrappers, obsolete-name aliases, speculative
  repositories, factories, providers, protocols, or storage abstractions
  without a demonstrated current requirement.
- Prefer consolidating and deleting redundant code. Do not generate code
  outside the requested scope.

## Verification rules
- For behavior changes, run the smallest command or scenario that proves the changed path works.
- For connector changes, verify extraction, normalization, lineage, and permission mapping.
- For retrieval changes, verify citations and permission filtering.
- For BI changes, verify generated SQL or query plans before presenting insights.
## Test rules
    All test files must be located under:
    /Users/duynguyen/Documents/vikki-bank-code/ai-team/BoThesis/tests
    Never create test files inside application/source directories such as backend/, bothesis/, feature modules, or temporary folders.
    Mirror the application structure under tests/ when useful for clarity.
    Reuse existing test modules before creating new test files.
    Do not create duplicate, temporary, ad-hoc, or one-off test files when an existing test module can cover the scenario.
    Do not leave debugging scripts or temporary verification files scattered across the repository.
    If a temporary script is strictly necessary for local verification, remove it after verification unless the user explicitly asks to keep it.
