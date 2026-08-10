<task>
Generate focused retrieval queries only for evidence that is still missing.
</task>

<instructions>
- Address only the supplied missing evidence.
- Do not repeat or paraphrase a previous query.
- Preserve relevant names, identifiers, dates, and constraints from the question.
- Return no query when another search cannot reasonably close the gap.
- Do not answer the question.
- Return JSON only: {"queries": ["new focused query"]}.
</instructions>

<input>
  <question>{{question}}</question>
  <missing_evidence>{{missing_evidence}}</missing_evidence>
  <previous_queries>{{previous_queries}}</previous_queries>
  <maximum_queries>{{maximum_queries}}</maximum_queries>
</input>
