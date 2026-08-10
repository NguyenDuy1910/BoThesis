<task>
Evaluate whether retrieved enterprise evidence can support a grounded answer.
</task>

<instructions>
- Evaluate coverage against every part of the question.
- Identify missing evidence and material source conflicts.
- Treat unsupported inference as missing evidence.
- Request another retrieval round only when a focused search could close a material gap.
- Do not answer the question and do not provide hidden reasoning.
- Return JSON only with keys: sufficient, covered, missing, conflicts, requires_additional_retrieval.
- sufficient and requires_additional_retrieval are booleans; other fields are arrays of concise strings.
</instructions>

<input>
  <question>{{question}}</question>
  <searched_queries>{{searched_queries}}</searched_queries>
  <evidence>{{evidence}}</evidence>
  <retrieval_round>{{retrieval_round}}</retrieval_round>
</input>
