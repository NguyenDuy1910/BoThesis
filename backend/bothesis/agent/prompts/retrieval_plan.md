<task>
Select the smallest candidate-query set that covers the material information needs.
</task>

<instructions>
  <selection_policy>
  - Select queries only from `candidate_queries`; copy selected strings exactly.
  - Cover each material part of the question while removing semantic duplicates.
  - Prefer focused candidates that retain important entities, identifiers, dates, comparisons, relationships, and constraints.
  - Select no more than `maximum_queries`. Return an empty list only when none of the candidates can retrieve relevant evidence.
  - Do not rewrite queries, answer the question, add facts, or assume unavailable retriever behavior.
  </selection_policy>

  <output_contract>
  Return exactly one valid JSON object: `{"queries":["selected query"]}`. Return no Markdown fence or commentary.
  </output_contract>
</instructions>

<input>
  <question>{{question}}</question>
  <candidate_queries>{{candidate_queries}}</candidate_queries>
  <maximum_queries>{{maximum_queries}}</maximum_queries>
</input>
