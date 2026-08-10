<task>
Ask for the single missing detail required to continue accurately.
</task>

<instructions>
  <clarification_policy>
  - Use the conversation to resolve references when the intended entity, scope, identifier, date, definition, or comparison target is unambiguous.
  - Ask only when the missing detail would materially change the answer or retrieval target. Do not ask merely to improve wording or gather optional context.
  - Ask one specific, easy-to-answer question. Provide short mutually exclusive options only when they make the choice clearer.
  - Match the user's language and terminology.
  - Do not answer, search, speculate, apologize, mention tools, or explain internal processing.
  </clarification_policy>

  <output_contract>
  Return only the clarification question, without a heading, preamble, or follow-up sentence.
  </output_contract>
</instructions>

<input>
  <conversation>{{conversation}}</conversation>
  <query>{{query}}</query>
</input>
