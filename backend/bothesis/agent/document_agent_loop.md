TURN LOOP
│
│ cycle #1
│
├── capture StepContext
│
├── SAMPLING RETRY LOOP
│   │
│   ├── attempt #1 → retryable error
│   │
│   └── attempt #2
│       │
│       └── RESPONSE STREAM LOOP
│           ├── item.started reasoning
│           ├── item.delta
│           ├── item.completed
│           ├── item.started commentary
│           ├── item.delta
│           ├── item.completed
│           ├── item.started tool_call
│           └── response.completed
│
├── execute tool
├── append result
│
│ cycle #2
│
├── capture StepContext
│
├── SAMPLING RETRY LOOP
│   └── RESPONSE STREAM LOOP
│       └── final assistant message
│
└── TURN COMPLETED