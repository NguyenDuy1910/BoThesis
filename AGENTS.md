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
- Separate ingestion, indexing, retrieval, agent orchestration, and BI logic.
- Validate inputs at API boundaries.
- Enforce permissions before retrieval results or BI data reach the agent.
- Log operational events without leaking private content or secrets.

## Verification rules
- For behavior changes, run the smallest command or scenario that proves the changed path works.
- For connector changes, verify extraction, normalization, lineage, and permission mapping.
- For retrieval changes, verify citations and permission filtering.
- For BI changes, verify generated SQL or query plans before presenting insights.
