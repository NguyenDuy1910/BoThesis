# BoThesis Claude Instructions

BoThesis is an enterprise knowledge and BI assistant.

## Default behavior
- Keep changes simple and local.
- Do not redesign project folders unless explicitly asked.
- Preserve source lineage, tenant boundaries, permissions, audit events, and citations.
- Prefer boring, maintainable code over clever abstractions.
- Ask only when a product/security decision cannot be inferred from repo context.

## Product rules
- Enterprise answers must be grounded in trusted sources.
- Retrieval must enforce user permissions before content reaches the agent.
- BI outputs must be based on governed metrics, validated SQL, or known datasets.
- Connectors should be independent adapters for Confluence, Jira, Slack, PDF, Google Drive, databases, and datalake sources.

## Delivery rules
- Do not ship placeholders, fake fallbacks, or TODO-only implementations.
- Verify behavior with the smallest meaningful command or scenario.
- Report exactly what changed and how it was verified.
