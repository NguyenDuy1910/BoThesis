<task>
Create new search queries only for material evidence that is still missing.
</task>

<instructions>
  <refinement_policy>
  - Address only gaps explicitly listed in `missing_evidence` and relevant to the original question.
  - Compare against `previous_queries`; do not repeat, lightly rephrase, or broadly expand an earlier search.
  - Preserve exact entities, identifiers, dates, conditions, relationships, and constraints required by each gap.
  - Make each new query concise, independently searchable, and non-overlapping with the other new queries.
  - Return an empty list when no distinct search is likely to close a material gap. Never exceed `maximum_queries`.
  - Do not answer, add facts, or invent source filters.
  </refinement_policy>

  <output_contract>
  Return exactly one valid JSON object: `{"queries":["new focused query"]}`. Return no Markdown fence or commentary.
  </output_contract>
</instructions>

<input>
  <question>{{question}}</question>
  <missing_evidence>{{missing_evidence}}</missing_evidence>
  <previous_queries>{{previous_queries}}</previous_queries>
  <maximum_queries>{{maximum_queries}}</maximum_queries>
</input>
