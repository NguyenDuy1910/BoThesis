---
name: bothesis-enterprise-ai
description: Use when working on BoThesis enterprise knowledge, connectors, retrieval, BI intelligence, datalake, or agent behavior.
---

# BoThesis Enterprise AI Skill

## Mission
Help build BoThesis as a simple, secure enterprise knowledge and BI assistant.

## Core prompt
You are working on BoThesis. Keep changes minimal, grounded, and maintainable. Preserve enterprise controls: tenant isolation, permissions, source lineage, auditability, citations, and governed BI semantics. Do not redesign folders unless the user asks.

## Source support
BoThesis should support knowledge from:
- Confluence
- Jira
- Slack
- PDF
- Google Drive
- Databases
- Datalake/lakehouse assets

## Required checks
Before changing behavior, identify the affected path:
1. Connector ingestion
2. Document normalization/indexing
3. Retrieval and grounding
4. Agent orchestration
5. BI/semantic layer
6. Datalake/catalog/lineage
7. Auth, permission, or audit

Then make the smallest correct change and verify that path.

## Enterprise rules
- Enforce permissions before retrieval or BI data reaches the agent.
- Keep connector-specific logic inside the connector.
- Keep citations and source lineage attached to indexed content.
- Validate generated SQL before using it for BI insights.
- Never store secrets in source code.
- Never present ungrounded enterprise facts as verified answers.
