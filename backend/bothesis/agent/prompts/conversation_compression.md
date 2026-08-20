<conversation_compression_instructions>
  <purpose>Compress the supplied conversation for future BoThesis agent context.</purpose>
  <preserve>
    Preserve user goals, important facts, user corrections, constraints,
    unresolved questions, important decisions, relevant entities, meaningful
    tool findings, and evidence or source references when required.
  </preserve>
  <remove>
    Remove conversational filler, repeated wording, redundant intermediate
    commentary, and obsolete details that no longer affect the task.
  </remove>
  <never>
    Never invent facts, resolve unanswered questions, convert uncertainty into
    certainty, or change user intent.
  </never>
  <output>Return compact context for a future model, not a user-facing summary.</output>
</conversation_compression_instructions>
