<retrieval_reranking_instructions>
Rank the supplied access-permitted candidate chunks by their usefulness for
answering the query. Consider the document title, section path, retrieval
context, canonical chunk text, and retrieval score. Prefer direct, specific
evidence over general background. Do not add facts or identifiers.

Return exactly one JSON object with one key, "chunk_ids". Its value must be an
ordered array of at most {{result_limit}} candidate chunk IDs, strongest first.
Do not return Markdown or explanatory text.
</retrieval_reranking_instructions>

<query>{{query}}</query>
<candidates>{{candidates}}</candidates>
