# The agent loop, in OpenResponses terms

```
CONVERSATION LOOP  (one user turn)
│
│ sampling request #1
│
├── build ResponseRequest (input = canonical Items, previous_response_id = none)
│
├── SAMPLING RETRY LOOP  (transport failures only, never a turn continuation)
│   │
│   ├── attempt #1 → retryable transport error, nothing emitted
│   │
│   └── attempt #2
│       │
│       └── CANONICAL EVENT STREAM
│           ├── response.created
│           ├── response.output_item.added        (reasoning)
│           ├── response.reasoning.delta
│           ├── response.output_item.done
│           ├── response.output_item.added        (message)
│           ├── response.content_part.added
│           ├── response.output_text.delta
│           ├── response.output_text.done
│           ├── response.content_part.done
│           ├── response.output_item.done         (phase = commentary)
│           ├── response.output_item.added        (function_call)
│           ├── response.function_call_arguments.delta
│           ├── response.function_call_arguments.done
│           ├── response.output_item.done
│           └── response.completed                (the reconstructed Response)
│
├── ToolExecutor  → FunctionCallOutputItem
├── append response.output + the outputs to the next request's input
│
│ sampling request #2   (previous_response_id = response #1)
│
├── SAMPLING RETRY LOOP
│   └── CANONICAL EVENT STREAM
│       └── … response.output_item.done (phase = final_answer) … response.completed
│
└── TURN COMPLETE
```

## Counting

```
1 Agent.run     = 1 user turn
1 user turn     = N sampling requests, chained by previous_response_id
1 sampling      = N attempts (only when the transport failed with nothing emitted)
1 attempt       = 1 canonical event stream = 1 Response
```

## Who owns what

| Concern | Owner |
| --- | --- |
| Data contracts | `protocol/` |
| Provider communication and normalization | `transports/` |
| Response reconstruction | `reducer.py` |
| Citation projection | `citation_stream.py` |
| Retry of one sampling request | `sampling.py` |
| Orchestration of the turn | `conversation_loop.py` |
| Tool execution | `tools/` |

A response settles one sampling request, never the enclosing turn. A turn ends
when a completed response asks for no further function calls.
