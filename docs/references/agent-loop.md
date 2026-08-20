---
sidebar_position: 3
title: "BoThesis Agent Architecture"
description: "Canonical LLM loop, protocol items, streaming events, tools, grounding, and runtime boundaries"
---

# BoThesis Agent Architecture

This document is implementation context for the BoThesis conversational agent.
Keep it aligned with the code when changing agent behavior.

## Purpose and boundaries

BoThesis is an enterprise knowledge and analytics assistant. The agent answers
from the current conversation when sufficient, retrieves enterprise knowledge
only when needed, preserves source lineage for citations, and enforces the
authenticated tenant and reader scope before evidence reaches the model.

The agent package orchestrates model decisions and tools. Connector extraction,
document persistence, vector storage, and retrieval implementation remain in
their own packages.

```text
Web chat UI
  │ SSE RuntimeEvent
  ▼
FastAPI /api/v1/agent/chat
  │ AgentContext: authenticated tenant, user, reader IDs, documents, history
  ▼
Agent → ConversationSession → TurnRequest
  │                         │
  │                         ├─ SamplingRequest → provider transport
  │                         └─ ToolExecutor → permission-scoped tool
  ▼
RuntimeEvent stream: commentary, tool activity, citations, completion/failure
```

## Primary modules

| Module | Responsibility |
| --- | --- |
| `agent.py` | Public streaming façade. Validates a user message and authenticated scope; converts unhandled agent failures into `turn.failed`. |
| `conversation_session.py` | Holds shared model, tool, memory, config, and tracing dependencies. Creates one fresh `TurnRequest` per user message. |
| `turn_request.py` | Owns the complete user-turn loop: sample, decide, execute tools, append observations, and complete. |
| `sampling_request.py` | Owns retries for one logical model request. A retry replays the same immutable request; it is not a tool-loop iteration. |
| `step_context.py` | Captures the immutable snapshot for one sampling request. |
| `turn_input.py` | Holds canonical conversation history and renders it to OpenAI Responses or OpenRouter Chat Completions wire formats. |
| `response_stream.py` | Converts native provider streams into canonical provider events, canonical output items, internal live deltas, and `ModelStreamCompleted`. |
| `protocol/` | Provider-neutral, strictly validated contracts: content, items, requests/responses, tools, semantic events, and sampling output. |
| `tools/` | Tool declarations, registry, execution, validation, limits, evidence projection, and tool runtime events. |
| `citation.py` | Converts citation markers in assistant text into visible text plus safe citation events. |
| `conversation_compression.py` | Bounds history and constructs initial `TurnInput`; it does not make routing decisions. |
| `prompts/` | File-backed prompt roles: `agent_base`, `capability_base`, and `conversation_compression`. |

## One user turn: dynamic LLM loop

One user message creates one `TurnRequest`. A turn contains one or more
`SamplingRequest`s. There are no mandatory planning, query-rewriting,
retrieval, review, or synthesis stages. The model decides whether to answer or
call a declared tool after each observation.

```text
user message + AgentContext
          │
          ▼
ConversationMemory.prepare()
          │  agent_base + bounded history + access-checked documents
          ▼
TurnInput
          │
          ├─────────────────────────────────────────────────────┐
          │                                                     │
          ▼                                                     │
capture_step_context()                                          │
          │                                                     │
          ▼                                                     │
run_sampling_request()                                          │
          │  provider stream → canonical events/items           │
          ▼                                                     │
SamplingRequestOutput                                           │
          │                                                     │
    ┌─────┴──────────────┐                                      │
    │ no function calls  │ function calls                       │
    ▼                    ▼                                      │
final answer       ToolExecutor.execute()                        │
    │                    │ validate → execute → evidence        │
    │                    ▼                                      │
    │            FunctionCallOutputItem(s) ─────────────────────┘
    ▼
RunCompleted
```

### Turn state and limits

`ConversationRun` is mutable state for exactly one user turn. It records model
iterations, tool rounds, tool-call count, durations, discovered evidence, used
evidence IDs, and executed tool signatures.

`AgentConfig` provides circuit breakers. The loop limits model turns, tool
rounds, total tool calls, tool execution time, tool-output context size,
history size, user-message size, and provider retry count. These are safety
limits only; they do not prescribe the agent’s workflow.

### Sampling requests

`StepContext` is captured once per sampling request. It contains:

- authenticated `AgentContext`;
- `ModelInfo` (`openai` or `openrouter`, plus model name);
- immutable `TurnInput` history;
- the currently allowed `FunctionTool` declarations;
- typed `AgentConfig` values; and
- the sampling/turn number.

`run_sampling_request()` builds one `ResponseRequest` from this snapshot. On
transient transport failure it retries the exact same snapshot. Tool output is
added only after the sampling settles, so it always starts a new sampling
request rather than modifying a retry.

`SamplingRequestOutput` is the small semantic output used by `TurnRequest` to
make the next decision:

- `needs_follow_up`: the response contains one or more function calls;
- `last_agent_message`: non-empty assistant output text, when present.

## Canonical protocol

`bothesis.agent.protocol` is the provider-neutral boundary. Protocol models
are immutable Pydantic models with unknown fields rejected. Provider-specific
concepts must not leak into orchestration code.

### Content parts

`ContentPart` is the typed content inside a `MessageItem`.

| Family | Variants | Meaning |
| --- | --- | --- |
| Input | `InputText`, `InputImage`, `InputFile` | User or supplied document content sent to a model. |
| Output | `OutputText`, `Refusal` | Model-produced content. `OutputText.annotations` remains opaque because provider annotation formats differ. |

### Items: persistent semantic conversation units

`Item` is the canonical unit stored in a model request/response history. Items
are ordered and can be replayed on the next sampling request.

| Item | Producer | Purpose |
| --- | --- | --- |
| `MessageItem` | User, model, or runtime | A role-based message carrying content parts. |
| `ReasoningItem` | Provider adapter | Public reasoning summary plus opaque continuation data. Raw chain-of-thought is never modeled or streamed to the client. |
| `FunctionCallItem` | Model | A requested tool invocation. Arguments remain the original JSON string for faithful provider replay; `parsed_arguments()` validates it as an object before execution. |
| `FunctionCallOutputItem` | Tool runtime | The observation paired with a function call by `call_id`. It is appended to the next model input. |
| `ExtensionItem` | Provider adapter | Escape hatch for an unrecognized provider item type. It preserves provider fields for replay without making them common orchestration concepts. |

`pair_function_calls()` correlates calls and outputs through `call_id`. Do not
replace a function call with its output: both are needed in history and are
required by provider tool-calling protocols.

### Request and response envelopes

`ResponseRequest` contains canonical input items, optional instructions,
tool declarations, tool choice, generation settings, and opaque
`provider_options`. It is rendered by provider adapters rather than being sent
directly on the wire.

`Response` contains ordered output items, status, usage, incomplete/failure
details, and opaque metadata. Its `output_text`, `function_calls`, and
`output_annotations` properties are derived views, not separate sources of
truth.

### TurnInput rendering

`TurnInput` distinguishes fresh `UserInput` from already canonical
`ResponseItem`. Its `items` property normalizes both into ordered `Item`s.

- OpenAI Responses receives `instructions` as a top-level request field and
  receives protocol items as Responses input items.
- OpenRouter receives `instructions` as the first system message, then
  provider-compatible user, assistant, and tool messages.
- Assistant reasoning, tool calls, and assistant message output are grouped
  correctly for OpenRouter. Tool outputs use the corresponding `call_id`.

Do not build provider message dictionaries in turn-loop or tool code. Change
rendering only in `turn_input.py` or provider adapters.

## Event design

Events have two intentionally separate levels.

```text
native OpenAI/OpenRouter chunk
        │
        ▼
ProviderStreamEvent       internal normalized provider lifecycle
        │
        ▼
StreamResponse             canonical Item assembly + internal live signals
        │
        ▼
TurnRequest / ToolExecutor / CitationRenderer
        │
        ▼
RuntimeEvent               public application/SSE contract
```

### ProviderStreamEvent

`ProviderStreamEvent` is an internal union modeled after OpenResponses. It is
used between adapters and `StreamResponse`; it is never sent to the browser.

It includes response lifecycle events, completed output items, text deltas,
function-argument deltas, and public reasoning-summary deltas:

- `response.created`, `response.in_progress`, `response.completed`,
  `response.incomplete`, `response.failed`;
- `response.output_item.added`, `response.output_item.done`;
- `response.output_text.delta`, `response.output_text.done`;
- `response.function_call_arguments.delta`,
  `response.function_call_arguments.done`; and
- `response.reasoning_summary_text.delta`,
  `response.reasoning_summary_text.done`.

Provider adapters normalize OpenAI Responses and OpenRouter stream shapes into
this union. `StreamResponse` collects completed items into a `Response` and
emits `ModelStreamCompleted` once the provider stream settles.

`ProviderReasoningSummaryDelta` is an internal-only signal. It may be recorded
in tracing but never enters the public event union or SSE stream.

### RuntimeEvent

`RuntimeEvent` is the public application stream. `ResponseStreamEvent` is a
backwards-compatible alias for it. FastAPI serializes each runtime event as an
SSE `data:` JSON frame.

| Event | Emitted by | Client meaning |
| --- | --- | --- |
| `assistant.commentary.delta` | `TurnRequest` | Optional, intentional user-facing progress. It is never raw model output. |
| `assistant.message.delta` | `TurnRequest` via `CitationRenderer` | A visible fragment of the final assistant answer. |
| `assistant.message.done` | `TurnRequest` | The final assistant answer is complete. |
| `tool.started` | `ToolExecutor` | A requested tool activity has begun or has been accepted for projection. Arguments are excluded from JSON output. |
| `tool.completed` | `ToolExecutor` | A tool outcome with status, duration, result count, and safe activity metadata. |
| `citation.available` | `ToolExecutor` or document registration | Safe metadata for evidence discovered in this turn. No full evidence content is exposed. |
| `citation` | `CitationRenderer` | The streamed answer used a known evidence ID. |
| `document.progress` | Document preparation flow | An attachment preparation/indexing status update. |
| `turn.completed` | `TurnRequest` | Terminal success with timing and tool-count metrics. |
| `turn.failed` | `Agent` | Terminal, safe failure message. |

### Commentary and final answer projection

Provider text remains internal while a sampling request is in progress because
the runtime cannot know whether that sampling will request a tool. If it does,
the text is an intermediate model artifact and is never sent to the client.
When a completed sampling has no tool calls, its accumulated text is projected
through the citation renderer as `assistant.message.delta` events, followed by
`assistant.message.done`. The client renders those events directly as the
final answer; it never infers a final sampling round or promotes commentary.

`assistant.commentary.delta` is reserved for deliberate, safe progress copy.
Tool lifecycle events remain the normal progress UI signal.

### Citation event rules

Tools return `Evidence` objects internally. The runtime registers each unique
evidence ID and emits `citation.available` using a safe `EvidenceReference`
(title, source, location, URI, relevance, and bounded snippet). Tool output is
then sent to the next sampling request as text containing evidence IDs.

The model cites evidence using `[[cite:EVIDENCE_ID]]`. `CitationRenderer`
buffers streaming text so a marker split across deltas remains valid. A known
marker becomes a `citation` event; an unknown or malformed marker remains
visible text. The renderer never invents citations.

## Tools and enterprise grounding

`ToolRegistry` is the explicit allowlist. A `Tool` owns its `ToolDefinition`
(model name, description, JSON Schema, public activity label/category) and its
own `execute(arguments, ToolContext)` implementation.

`ToolExecutor` owns generic tool runtime policy:

1. Parse function-call JSON and validate it against the registered schema.
2. Reject unknown tools, invalid arguments, duplicate exact calls, or calls
   beyond the configured limit as model observations.
3. Execute independent valid calls concurrently while preserving model call
   order in output items and UI events.
4. Apply timeouts and convert execution failures into safe `ToolOutput`s.
5. Register evidence, emit runtime events, and create bounded
   `FunctionCallOutputItem`s for the next model sampling.

`ToolContext` contains `AgentContext`; tools must use the authenticated tenant,
roles, reader IDs, and admin state rather than any model-supplied identity.

`KnowledgeSearch` is the standard retrieval example. It requires a
`ScopedKnowledgeRetriever`; an unscoped retriever must not provide model
context. It queries only access-permitted evidence, preserves document and
source lineage, bounds content/evidence, and returns evidence IDs usable by
the citation renderer.

## Prompt roles

Only three file-backed prompt roles exist:

| Prompt | Runtime role |
| --- | --- |
| `agent_base.md` | Primary conversational-agent instruction used by `ConversationMemory.prepare()`. It gives dynamic retrieval/tool/grounding guidance without requiring stages. |
| `capability_base.md` | Base instruction for an isolated structured capability, if such a model operation is introduced. It is not the conversational agent prompt. |
| `conversation_compression.md` | Instruction for a future specialized conversation-compression operation. It preserves useful future context without inventing facts. |

`template_render.py` only loads files, renders declared variables, and rejects
missing or unexpected values. It must not contain routing, retrieval, fallback,
or workflow logic.

## Change rules

- Preserve `AgentContext` and `ToolContext` permission boundaries. Never allow
  model-provided tool arguments to choose tenant or user identity.
- Preserve canonical items across sampling requests. Do not retain only text
  when a response contains reasoning continuation data or function calls.
- Add provider-specific fields through `ExtensionItem`, `ExtensionTool`, or
  `ResponseRequest.provider_options` unless a behavior is genuinely shared by
  all supported providers.
- Add browser-visible events only to `RuntimeEvent`; do not expose provider
  lifecycle events or raw reasoning.
- Keep runtime events safe to serialize. Do not include raw documents, secrets,
  unfiltered tool arguments, or private reasoning.
- Emit evidence only after access checks and retain enough lineage to support
  citations.
- Keep tools isolated adapters. Add generic execution policy to
  `ToolExecutor`, not individual tool implementations or `TurnRequest`.
- Prefer tests under `tests/`: protocol contracts in
  `tests/bothesis/agent/test_protocol.py`; runtime/API behavior in existing
  agent, chat, and retrieval test modules.

## Key invariants

1. One `TurnRequest` represents one user request; one turn may contain many
   sampling requests.
2. One `StepContext` is immutable for one sampling request and all of its
   retries.
3. A function call and its function-call output are both canonical history
   items and are correlated by `call_id`.
4. Provider stream events are internal; runtime events are the public SSE
   contract.
5. Raw chain-of-thought never reaches `RuntimeEvent` or the client.
6. Enterprise facts need available evidence and source lineage when grounding
   is required.
7. Permission filtering occurs before evidence or analytics data reaches the
   model.
8. A final answer is carried only by `assistant.message.*`; provider text and
   internal sampling rounds are never exposed to the client.
