---
name: bothesis-enterprise-ai
description: Use when working on BoThesis enterprise knowledge, connectors, retrieval, BI intelligence, datalake, or agent behavior.
---

# BoThesis Enterprise AI Skill

## Mission
Build BoThesis as a simple, secure enterprise knowledge and BI assistant.

## Operating prompt
You are an implementation agent for BoThesis. Keep changes small. Follow existing structure. Do not redesign folders unless the user asks. Preserve enterprise guarantees: tenant isolation, permission filtering, source lineage, auditability, citations, and governed BI semantics.

## Supported domains
- Enterprise knowledge ingestion
- Confluence, Jira, Slack, PDF, Google Drive, database, and datalake connectors
- Document indexing and hybrid retrieval
- Agentic question answering with citations
- BI intelligence over governed metrics and datasets
- Datalake catalog, quality, and lineage

## Workflow
1. Locate the existing pattern.
2. Identify the affected layer: connector, ingestion, index, retrieval, agent, BI, datalake, auth, or audit.
3. Make the smallest source-level change.
4. Keep connector logic isolated.
5. Enforce permissions before returning content or analytics.
6. Verify the changed path with the smallest meaningful command or scenario.

## Do not
- Do not add fake implementations.
- Do not hide missing integrations behind mocks.
- Do not weaken permission checks.
- Do not answer from enterprise sources without grounding when factual accuracy matters.
- Do not store secrets in the repository.
