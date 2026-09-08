Session
 ├── SessionConfiguration
 ├── SessionServices
 ├── ContextManager
 └── capture_step_context()
       ↓
    TurnContext
       ↓
    StepContext
     ├── ResolvedStepSettings
     ├── TurnEnvironmentSnapshot
     └── ToolRouter
          └── ToolRegistry
               └── ToolExecutor


run_turn
 → capture StepContext
 → ContextManager history
 → Prompt
 → provider adapter
 → canonical ResponseItem
 → ToolInvocation
 → ToolExecutor
 → tool-result item
 → next sampling step


 Turn T1
│
├── StepContext S1
│      tools: search
│      ↓
│     LLM
│      ↓
│     search
│
├── StepContext S2
│      tools: search + materialize
│      ↓
│     LLM
│      ↓
│     materialize
│
├── StepContext S3
│      env: workspace ready
│      tools: search + materialize + shell
│      ↓
│     LLM
│      ↓
│     shell
│
└── StepContext S4
       updated history/world
       ↓
      LLM
       ↓
      final