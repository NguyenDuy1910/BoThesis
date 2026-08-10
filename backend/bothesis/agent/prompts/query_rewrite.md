<task>
Rewrite the user query into one standalone enterprise knowledge search query.
</task>

<instructions>
- Resolve references only from the supplied conversation.
- Preserve names, identifiers, dates, acronyms, quoted text, and technical terms.
- Keep the meaning and requested scope unchanged.
- Do not answer the question or add facts.
- Return JSON only: {"query": "standalone query"}.
</instructions>

<input>
  <conversation>{{conversation}}</conversation>
  <query>{{query}}</query>
</input>
