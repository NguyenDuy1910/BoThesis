<task>
Ask one concise clarification question needed before enterprise retrieval.
</task>

<instructions>
- Ask only for the missing scope, entity, identifier, date, or comparison target.
- Use supplied conversation context when it resolves the ambiguity.
- Do not search, answer, speculate, or mention internal processing.
- Return only the user-facing clarification question.
</instructions>

<input>
  <conversation>{{conversation}}</conversation>
  <query>{{query}}</query>
</input>
