# Agent runtime context

`TurnContext` is the mutable runtime state for one user-initiated turn. It
holds the user input, stable request environment, resources, accumulated
canonical items and observations, evidence, citations, settings, counters, and
timing. It is never sent to a model directly.

`StepContext` is an immutable, provider-neutral snapshot of exactly one model
sampling request:

```text
turn_id
step_index
settings
instructions
input_items
tools
```

The context manager selects bounded relevant conversation, the current user
input, applicable resource metadata, and a compacted set of recent tool
interactions from the mutable turn state. It renders those selections into the
snapshot's `instructions` and ordered `input_items`; it does not retain their
source decomposition in `StepContext`.

```text
UserTurn
  -> TurnContext
  -> ContextManager
  -> StepContext #1
  -> ModelAdapter
  -> ToolCall / observation
  -> update TurnContext
  -> StepContext #2
```

Tool routing, resource resolution, tracing, and model transports are runtime
capabilities owned by `SessionServices` and the agent loop. `StepContext`
contains only provider-neutral tool specifications; the runtime recreates the
router from that immutable visible tool surface when executing a model call.
The session likewise retains the selected resource scope keyed by the step
identity, rather than placing a resolver or mutable resource state in the
snapshot.

Every `context.build` and `model.sample` trace includes the full `StepContext`
snapshot. Comparing adjacent traces therefore shows the precise model-visible
context before and after a tool observation or compaction.
