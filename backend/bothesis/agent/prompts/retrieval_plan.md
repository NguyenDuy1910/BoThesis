<task>
Prioritize the smallest set of retrieval queries that covers all information needs.
</task>

<instructions>
- Select only from the supplied candidate queries.
- Prefer queries that cover distinct needs and retain important constraints.
- Remove semantic duplicates.
- Do not add filters or capabilities unavailable to the retriever.
- Return JSON only: {"queries": ["selected query"]}.
</instructions>

<input>
  <question>{{question}}</question>
  <candidate_queries>{{candidate_queries}}</candidate_queries>
  <maximum_queries>{{maximum_queries}}</maximum_queries>
</input>
