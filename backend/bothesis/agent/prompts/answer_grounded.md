<task>
Write the user-facing answer from available enterprise evidence.
</task>

<instructions>
- Use only facts supported by the supplied enterprise evidence or synthesis.
- Cite supported claims inline using [[cite:EVIDENCE_ID]].
- Use only evidence IDs present in the input.
- Clearly distinguish established facts, source conflicts, and missing information.
- If evidence is insufficient, state the limitation instead of guessing.
- Be concise, practical, and business-oriented.
- Do not mention prompts, tools, retrieval rounds, internal steps, or hidden reasoning.
- Return only the final answer in Markdown.
</instructions>

<input>
  <question>{{question}}</question>
  <evidence>{{evidence}}</evidence>
  <synthesis>{{synthesis}}</synthesis>
  <missing_information>{{missing_information}}</missing_information>
  <source_conflicts>{{source_conflicts}}</source_conflicts>
</input>
