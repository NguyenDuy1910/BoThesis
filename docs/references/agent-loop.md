---
sidebar_position: 3
title: "BoThesis Agent Architecture"
description: "OpenResponses as the canonical language of the agent: items, events, reducer, provider adapters, conversation loop, tools, grounding"
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

## OpenResponses is the protocol

The agent speaks [Open Responses](https://www.openresponses.org) (version
`2026-04-24`), an open, vendor-neutral specification for LLM APIs. It is the
canonical language of the agent, not one of several dialects:

- there is no BoThesis event model, and no translation step into or out of one;
- a provider's native protocol exists only inside its transport adapter;
- anything above the transport layer works with the same canonical models.

Every supported provider serves `POST /responses` in OpenResponses format:
OpenAI, whose Responses API the specification was derived from, and OpenRouter,
whose endpoint is documented as *"using OpenResponses API format"* and whose
request, item, and streaming-event schemas are field-identical. So there is one
projection for all of them, not one per provider:

```text
OpenAI  POST /responses          OpenRouter  POST /responses
        │                                          │
        └──────────────┬───────────────────────────┘
                       ▼
        transports/responses_adapter.py   (the whole normalization layer)
                       │
                       ▼
                 OpenResponses
                       │
             reducer.py (Response state)
                       │
             conversation_loop.py
```

Only one function in the process resolves a provider,
`transports.response_stream()`. There is no `if provider == …` anywhere else,
and no per-provider stream reconstruction.

## Primary modules

| Module | Responsibility |
| --- | --- |
| `protocol/` | The OpenResponses data contracts and nothing else: content parts, items, request/response envelopes, tools, and the streaming event union. Immutable Pydantic models that reject unknown fields. Never imports a provider SDK. |
| `transports/openai.py`, `transports/openrouter.py` | Thin async boundaries over each provider's native API — base URL, credentials, attribution headers, and whatever extra APIs that provider offers. No normalization. Both expose the same `stream_response()`. |
| `transports/responses_adapter.py` | The one adapter: renders a `ResponseRequest` into the native `/responses` request and projects native events onto canonical events, one native event at a time. |
| `reducer.py` | `ResponseReducer` — the only component that reconstructs a `Response` from its event stream. |
| `citation_stream.py` | `CitationProjection` — rewrites the canonical stream so internal citation markers become annotations. Canonical in, canonical out. |
| `sampling.py` | `sample()` — retries one sampling request when the transport failed with nothing emitted. |
| `conversation_loop.py` | `ConversationLoop` — orchestrates one user turn as a chain of responses. |
| `tools/` | Tool declarations, registry, execution policy, validation, limits, and evidence projection. |
| `citation.py` | Streaming-safe removal of `[[cite:ID]]` markers from model text. |
| `conversation_compression.py` | Bounds history and builds the initial canonical items and instructions. Makes no routing decisions. |
| `agent.py` | Public streaming façade. Validates the request, wraps the transport in its adapter, assigns stream-wide `sequence_number`s, and converts unhandled failures into `response.failed`. |
| `prompts/` | File-backed prompt roles: `agent_base`, `capability_base`, `conversation_compression`. |

## One user turn

One user message is one turn. A turn contains one or more sampling requests.
There are no mandatory planning, query-rewriting, retrieval, review, or
synthesis stages: after each observation the model decides whether to answer or
call a declared tool.

```text
user message + AgentContext
          │
          ▼
ConversationMemory.prepare()  →  PreparedConversation(items, instructions)
          │
          ├──────────────────────────────────────────────────────────┐
          ▼                                                          │
ResponseRequest(input=items, previous_response_id=…)                  │
          │                                                          │
          ▼                                                          │
sample()  →  adapter  →  CitationProjection  →  ResponseReducer       │
          │      (every event forwarded to the client immediately)    │
          ▼                                                          │
Response (settled by response.completed / .incomplete / .failed)      │
          │                                                          │
    ┌─────┴──────────────┐                                           │
    │ no function calls  │ function calls                            │
    ▼                    ▼                                           │
final_answer_text   ToolExecutor.execute()                            │
                         │ validate → execute → evidence             │
                         ▼                                           │
                  FunctionCallOutputItem(s) ────────────────────────┘
```

Each response's `output` is appended verbatim to the next request's `input`,
followed by the tool observations. Each response records the previous one in
`previous_response_id`, so a client can follow the chain.

### Turn state and limits

`ConversationRun` is mutable state for exactly one turn: model iterations, tool
rounds, tool-call count, durations, discovered evidence, used evidence IDs, and
executed tool signatures.

`AgentConfig` provides circuit breakers only — model turns, tool rounds, total
tool calls, tool execution time, tool-output context size, history size,
user-message size, and provider retry count. They are safety limits, not a
prescribed workflow.

### Sampling requests and retries

A `ResponseRequest` is built once per sampling request and is immutable, so a
retry replays exactly the same request. `sample()` retries only while nothing
has reached the caller: once any canonical event has been forwarded, the client
has observed part of that response and the request is no longer retryable.

Tool output is appended only after a response settles, so it always starts a new
sampling request rather than modifying a retry.

## Items

`Item` is the atomic unit of context, mirroring the specification's `ItemField`.

| Item | Producer | Purpose |
| --- | --- | --- |
| `MessageItem` | User, model, or runtime | A role-based message carrying content parts. `phase` labels an assistant message as `commentary` or `final_answer`. |
| `ReasoningItem` | Provider adapter | `content` (raw reasoning), `summary` (public summary), and `encrypted_content` (the opaque continuation blob). Only summary and encrypted content are replayed. |
| `FunctionCallItem` | Model | A requested tool invocation. `arguments` stays the provider's JSON string for faithful replay; `parsed_arguments()` validates it as an object before execution. |
| `FunctionCallOutputItem` | Tool runtime | The observation paired with a call by `call_id`. Always `completed`: a tool failure is reported inside `output`. |
| `CompactionItem` | Provider | Conversation state a provider compacted into an opaque blob. |
| `ExtensionItem` | Provider adapter | Escape hatch for an item type the protocol does not model (hosted tools, for example). Preserves every provider field for replay. |

A function call and its output are both history: never replace one with the
other.

### Item and response state machines

Items are `in_progress` → `completed`, or `incomplete` when the model was
interrupted partway through — in which case the item must be last and the
response is `incomplete` too. There is no `failed` or `skipped` item status.

Responses run `queued` → `in_progress` → `completed` | `incomplete` | `failed`.

### Assistant `phase`

The specification requires `phase` to be preserved and resent on follow-up
requests; omitting it degrades model quality. When a provider supplies it, it is
kept verbatim. When a provider omits it, `ResponseReducer` resolves it as the
response settles — the moment the information exists: a response that requested
tools carries `commentary`, a response that requested none carries the
`final_answer`. `Response.final_answer_text` falls back to every assistant
message when nothing declares a phase, so a provider predating the field still
yields a usable answer.

## Streaming events

The public SSE stream is the specification's event union, unmodified:

- lifecycle: `response.created`, `response.queued`, `response.in_progress`,
  `response.completed`, `response.incomplete`, `response.failed`, `error`;
- items: `response.output_item.added`, `response.output_item.done`;
- content: `response.content_part.added`, `response.content_part.done`;
- text: `response.output_text.delta`, `response.output_text.done`,
  `response.output_text.annotation.added`;
- refusals: `response.refusal.delta`, `response.refusal.done`;
- reasoning: `response.reasoning.delta`, `response.reasoning.done`,
  `response.reasoning_summary_part.added/.done`,
  `response.reasoning_summary_text.delta/.done`;
- function calls: `response.function_call_arguments.delta`,
  `response.function_call_arguments.done`.

The prescribed order for one text item is:

```text
response.output_item.added
  → response.content_part.added
    → response.output_text.delta …
    → response.output_text.done
  → response.content_part.done
→ response.output_item.done
```

`sequence_number` increases monotonically across the whole SSE stream, which
carries every response of the turn. `Agent.run` is the single writer.

No item-level event carries a response id, because the specification defines
none: the response being mutated is the one opened by the most recent
`response.created`, and `previous_response_id` chains a turn's responses. The
web client tracks exactly that.

## Response reconstruction

`ResponseReducer` folds events into a `Response` using only the specified
addressing fields — `item_id`, `output_index`, `content_index`,
`summary_index` — never a provider-specific assumption. `apply()` returns the
event it was given, except that a terminal event's `response` is replaced with
the fully reconstructed one. Consumers therefore see a settled response
containing every item, part, annotation and argument observed on the stream.

## Streaming is incremental

Every meaningful delta is forwarded the moment its provider event arrives:

```python
async for provider_event in stream:
    for event in adapter.project(provider_event):
        yield event
```

Nothing accumulates deltas until the provider finishes. The one bounded
exception is a citation marker split across deltas: `CitationRenderer` holds
back only the partial-marker suffix, never the text before it.

Both providers emit per-item lifecycle events natively, so nothing has to be
inferred or deferred: the adapter forwards each `output_item.added`,
`content_part.added`, delta, and `done` event as it arrives.

## Custom extensions

The specification requires implementer-specific types to be slug-prefixed and
permits optional fields on standard types when documented. BoThesis adds exactly
two things, both because OpenResponses does not cover the requirement:

| Extension | Why |
| --- | --- |
| `bothesis:document_citation` annotation | The specification defines only `url_citation`, which cannot carry enterprise document lineage (document id, page, section, access source). |

That is the entire extension surface. A reasoning item, in particular, needs no
BoThesis-specific field: `summary` plus `encrypted_content` are what every
provider uses to continue a reasoning session.

Before adding anything else, check whether an existing item, annotation, content
part, `ExtensionItem`, `ExtensionTool`, or `ResponseRequest.provider_options`
already covers it.

## Citations and enterprise grounding

Tools return `Evidence` internally, and tool output reaching the model contains
evidence IDs. The model cites with `[[cite:EVIDENCE_ID]]`.
`CitationProjection` then, on the canonical stream:

- strips markers from `response.output_text.delta`, forwarding cleaned text
  immediately;
- emits `response.output_text.annotation.added` with a
  `bothesis:document_citation` annotation at the character offset the marker
  occupied;
- rewrites `response.output_text.done`, `response.content_part.done` and the
  message in `response.output_item.done` to the cleaned text plus annotations,
  so a client reading only the settled response sees what a client following the
  deltas assembled.

An unknown or malformed marker stays visible text. The renderer never invents a
citation.

## Tools

`ToolRegistry` is the explicit allowlist. A `Tool` owns its `ToolDefinition`
(name, description, JSON Schema, activity label/category) and its own
`execute(arguments, ToolContext)`.

`ToolExecutor` owns generic runtime policy:

1. parse function-call JSON and validate it against the registered schema;
2. reject unknown tools, invalid arguments, duplicate exact calls, or calls
   beyond the configured limit as model observations;
3. execute independent valid calls concurrently while preserving model call
   order in the output items;
4. apply timeouts and convert execution failures into safe `ToolOutput`s;
5. register evidence and create bounded `FunctionCallOutputItem`s for the next
   sampling request.

`ToolContext` carries `AgentContext`; tools must use the authenticated tenant,
roles, reader IDs, and admin state, never a model-supplied identity.

`KnowledgeSearch` is the standard retrieval example. It requires a
`ScopedKnowledgeRetriever`, queries only access-permitted evidence, preserves
document and source lineage, bounds content, and returns evidence IDs the
citation projection can resolve.

## Prompt roles

| Prompt | Runtime role |
| --- | --- |
| `agent_base.md` | Primary conversational-agent instruction used by `ConversationMemory.prepare()`. Dynamic retrieval/tool/grounding guidance without prescribed stages. |
| `capability_base.md` | Base instruction for an isolated structured capability, if such an operation is introduced. Not the conversational agent prompt. |
| `conversation_compression.md` | Instruction for a specialized conversation-compression operation. |

`template_render.py` only loads files, renders declared variables, and rejects
missing or unexpected values. It must contain no routing, retrieval, fallback,
or workflow logic.

## Change rules

- Start from the specification. If OpenResponses represents a concept, use its
  representation; do not reshape it around an internal convenience.
- Keep `protocol/` free of behavior and free of provider imports.
- Add provider knowledge only inside a transport adapter. The conversation loop
  must never branch on a provider.
- Reconstruct response state only in `ResponseReducer`.
- Preserve canonical items across sampling requests, including reasoning
  continuation data and `phase`.
- Preserve `AgentContext` and `ToolContext` permission boundaries. Never let
  model-provided arguments choose tenant or user identity.
- Keep stream payloads safe to serialize: no raw documents, secrets, or
  unfiltered tool arguments.
- Emit evidence only after access checks, retaining enough lineage for
  citations.
- Keep tools isolated adapters. Generic execution policy belongs in
  `ToolExecutor`.
- Tests live under `tests/`, mirroring the package: `test_protocol.py`,
  `test_reducer.py`, `test_responses_adapter.py`, `test_conversation_loop.py`.
  `tests/native_responses.py` builds native provider events, and the adapter and
  loop suites run the same scripts for every provider.

## Key invariants

1. One `Agent.run` is one user turn; a turn may contain many sampling requests,
   chained by `previous_response_id`.
2. One `ResponseRequest` is immutable for one sampling request and all of its
   retries.
3. A function call and its output are both canonical history items, correlated
   by `call_id`.
4. The public SSE contract is the OpenResponses event union; there is no second
   event vocabulary.
5. `sequence_number` increases monotonically across the whole stream.
6. A response settles one sampling request, never the enclosing turn.
7. Every meaningful delta is forwarded immediately.
8. Permission filtering happens before evidence or analytics data reaches the
   model.
