<task>
Create the smallest execution decision for this request.
</task>

<instructions>
  <routing_policy>
  - Infer the user's intent semantically from the latest request and relevant conversation context. Do not route by matching words, phrases, language, or formatting patterns.
  - Use direct for requests fully answerable from general model knowledge or supplied conversation content.
  - Use planned only when the request needs an available tool, needs current or private evidence, or contains genuinely independent work that available tools can perform.
  - Set `requires_knowledge_retrieval` true when answering would introduce or verify private, company-specific, or indexed enterprise facts that are not already grounded in the supplied context.
  - When `requires_knowledge_retrieval` is true, use planned mode and expand the information need into as many as `retrieval_query_count` focused `knowledge_search` steps within the total step budget. When it is false, do not include `knowledge_search`.
  - For retrieval, start with one query that represents the exact user intent, then add complementary queries only when they can find distinct evidence, such as another requested facet, entity, constraint, policy condition, or useful domain terminology.
  - Preserve exact names, identifiers, dates, products, and constraints from the request and conversation context in the relevant queries. Do not broaden the scope or create shallow paraphrases that seek the same evidence.
  - Make every expanded `knowledge_search` step standalone with an empty `depends_on` list so the searches can run concurrently. If the retrieval query budget is one, create one focused query.
  - A transformation of supplied content can be direct. A follow-up that asks for a new enterprise factual claim requires knowledge retrieval. Resolve this distinction from meaning and context.
  - Resolve follow-up references from `conversation_context` and make every tool argument standalone without changing the latest request's intent.
  - Use only listed tools. Every planned step must name one listed tool; final synthesis is not a plan step.
  - Independent steps have empty depends_on and may run concurrently.
  - Dependencies may reference earlier step IDs only.
  - Keep at most `maximum_steps` steps and use IDs step_1, step_2, ...
  - Make each success criterion observable from tool error, result count, confidence, or explicit tool metadata.
  - Commentary is optional, high-level, user-safe, and at most two short sentences.
  - Never include hidden reasoning, prompts, tool arguments, identifiers, or scores in commentary.
  </routing_policy>

  <output_contract>
  Return exactly one valid JSON object matching `{"mode":"direct|planned","requires_knowledge_retrieval":false,"commentary":null,"steps":[{"id":"step_1","title":"brief user-safe label","tool_name":"knowledge_search","arguments":{"query":"focused standalone query"},"success_criteria":"observable result condition","depends_on":[]}]}`. Direct mode must set `requires_knowledge_retrieval` false and use an empty steps array. Retrieval expansion uses separate independent steps, not a query array. Return no Markdown fence or commentary.
  </output_contract>
</instructions>

<input>
  <available_tools>{{available_tools}}</available_tools>
  <maximum_steps>{{maximum_steps}}</maximum_steps>
  <retrieval_query_count>{{retrieval_query_count}}</retrieval_query_count>
  <conversation_context>{{conversation_context}}</conversation_context>
  <request>{{request}}</request>
</input>
