---
name: database-designer-skill
description: Design data storage strategy, schema/collection models, and database technology choices based on architecture/backend artifacts. Use when selecting SQL vs NoSQL and defining data structures, indexes, and lifecycle policies.
---

# Database Designer Skill

## Purpose
Produce data design artifacts that define the database technology choice and schema/collection models aligned with backend logic and architecture. Provide recommendations and alternatives with pros/cons.

## Inputs (authoritative order)
1. `docs/architecture.packet.json`
2. `docs/architecture.handoff.data.md`
3. `docs/backend.design.packet.json` (if available)
4. `docs/story-map.json` and `docs/prd.packet.json` (fallback)

If required inputs are missing, ask targeted questions and proceed with clearly labeled TBDs.

## Output Files (write under `docs/`)
- `docs/data.schema.packet.json` (authoritative)
- `docs/data.schema.md` (derived summary)

## Required Decisions
- **Database type**: SQL vs NoSQL (justify using access patterns and NFRs).
- **Platform choice**: e.g., Postgres/Supabase vs Firestore (include pros/cons).
- **Schema design**: tables/collections, indexes, constraints, migrations.
- **Data lifecycle**: retention, archival, deletion, backups.

## No-Guessing Policy (Always Use)
Ask clarifying questions whenever requirements, access patterns, or constraints could change the schema or platform choice. Do not guess. Provide up to 3 options with pros/cons and ask the user to choose. Repeat until the data plan is fully specified.
Example format:
1) **Question**: (precise decision)
2) **Options**:
   - Option A: pros/cons
   - Option B: pros/cons
3) **Ask**: "Which option should I proceed with?"

## Sync Rules
- Align data model with backend API contracts and business logic boundaries.
- Record data mismatches or missing access patterns for the Design Synchronizer.
- Preserve traceability to story IDs and FR/NFR IDs.
