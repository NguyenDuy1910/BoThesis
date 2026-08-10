<task>
Compress retrieved enterprise evidence into grounded facts with source references.
</task>

<instructions>
- Include only facts directly supported by the supplied evidence.
- Attach one or more exact evidence IDs to every fact.
- Preserve material disagreements as conflicts instead of resolving them by guessing.
- Record material unanswered parts as missing information.
- Return at most 12 concise facts; each claim should be one sentence.
- Do not write the user-facing answer and do not expose internal reasoning.
- Return JSON only with keys: facts, conflicts, missing.
- Each fact is an object with claim and evidence_ids.
</instructions>

<input>
  <question>{{question}}</question>
  <evidence>{{evidence}}</evidence>
</input>
