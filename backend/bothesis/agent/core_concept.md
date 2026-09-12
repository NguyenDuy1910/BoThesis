# Agent runtime execution model

One user request is one `TurnContext`, not one model request. The agent may
sample the model repeatedly, execute tools, record observations, and build a
new context before every subsequent sample.

```text
durable ConversationService history + TurnInput
                    │
                    ▼
              ConversationState
                    │
TurnContext ────────┼──────────── Capability and resource registries
                    ▼
              ContextManager
                    │
                    ▼
               StepContext
                    │
                    ▼
                ModelInput
                    │
                    ▼
                   Prompt / LLM
                    │
          ┌─────────┴──────────┐
          ▼                    ▼
      tool calls            final answer
          │
          ▼
  ToolOrchestrator
          │
          ▼
     observations
          │
          └───────────────► ConversationState → next step
```

## Ownership

- `ConversationService` owns persisted user and final-assistant messages. Its
  ordered history is supplied when a new agent turn begins.
- `ConversationState` owns the one ordered sequence of provider-neutral items
  visible while that agent turn runs: selected history, current user input,
  model messages, function calls, and function outputs. `TurnContext` does not
  duplicate these items.
- `TurnContext` owns mutable, turn-scoped runtime state: resource surface,
  counters, durations, evidence, citation references, and executed-call
  signatures. It is never a model request.
- `StepContext` is immutable and describes runtime state for exactly one model
  step: resolved settings, selected resource references, and visible tool
  names. It does not contain prompt text or conversation items.
- `ModelInput` is the exact provider-neutral context materialized for that
  step: instructions, selected ordered items, tool schemas, and settings. It
  projects to the protocol `Prompt` consumed by the transport.
- `ContextManager` decides what the model sees now. It initializes and compacts
  `ConversationState`, selects resources, composes instructions, and builds
  `StepContext` and `ModelInput`. It never executes a tool or runs the loop.
- `ToolOrchestrator` validates and executes only calls that were exposed by the
  originating immutable `StepContext`; results become observations appended to
  `ConversationState`.

Tools and resources are progressive capabilities. Resource metadata is included
only when relevant, while content remains behind explicit read/materialize
tools. Tool visibility is resolved again before every step from the current
turn limits and the caller's allowed capability names.

`context.build` traces the selected runtime snapshot and the ordered state
considered for it. Every `model.sample` trace contains the exact materialized
`Prompt`, including instructions, input items, tool schemas, settings, and the
previous-response lineage. Comparing adjacent model traces therefore shows the
effective context before and after each observation.
