<task>
Decompose a multi-part enterprise question into non-redundant retrieval queries.
</task>

<instructions>
- Create one focused query per distinct information need.
- Preserve entities, identifiers, dates, constraints, and relationships.
- Make every query independently searchable.
- Do not create overlapping queries or answer the question.
- Return JSON only: {"queries": ["query one", "query two"]}.
</instructions>

<input>
  <query>{{query}}</query>
  <maximum_queries>{{maximum_queries}}</maximum_queries>
</input>
