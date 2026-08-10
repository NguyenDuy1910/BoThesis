<task>
Create the smallest set of non-redundant search queries needed for a multi-part enterprise question.
</task>

<instructions>
  <decomposition_policy>
  - Produce a separate query only when an information need requires different evidence. Keep dependent constraints and relationships together.
  - Preserve the question's language, entities, identifiers, dates, comparisons, conditions, and requested scope.
  - Make every query concise and independently searchable without relying on another generated query.
  - Do not create synonymous or lightly rephrased queries for the same evidence.
  - A single-need question must produce one query. Never exceed `maximum_queries`.
  - Do not answer, prioritize sources, add facts, or invent retriever filters.
  </decomposition_policy>

  <output_contract>
  Return exactly one valid JSON object: `{"queries":["query one","query two"]}`. Return no Markdown fence or commentary.
  </output_contract>
</instructions>

<input>
  <query>{{query}}</query>
  <maximum_queries>{{maximum_queries}}</maximum_queries>
</input>
