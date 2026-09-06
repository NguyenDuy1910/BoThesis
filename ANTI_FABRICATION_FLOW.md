# Anti-Fabrication Flow Enhancement for BoThesis Agent

## Overview

The BoThesis agent has been enhanced with strict anti-fabrication rules to ensure that:
1. Agent never makes up or guesses enterprise-related information
2. All enterprise questions must be grounded in the knowledge base
3. Vague questions trigger clarification, not hallucination
4. Empty knowledge base results are explicitly reported to users

## Key Changes

### 1. Enhanced Agent Prompt (`agent_base.md`)

Added 6 new sections with clear anti-fabrication rules:

#### `<no_fabrication_rule>`
- **CRITICAL**: Never fabricate, guess, or invent answers
- Only provide information that can be verified from:
  - Knowledge base (via `knowledge_search` tool)
  - Attached documents or conversation context
  - General factual knowledge (not enterprise-related)
- When knowledge base returns no results → explicitly state this fact

#### `<clarification_rule>`
- When user's question is too vague → ask clarifying questions FIRST
- Don't make assumptions
- Request specific details (entity names, dates, business areas, project codes)
- Example: For "Cho tôi template mẫu đăng ký môn học", ask "Which system? What format? What are the specific requirements?"

#### `<knowledge_base_requirement>`
- All enterprise-related questions MUST be grounded in knowledge base
- Enterprise facts = policies, procedures, data, systems, decisions, history
- Questions with "company", "we", "our", "our system" → requires knowledge base retrieval

#### Enhanced `<tool_use>`
- Answer directly ONLY when:
  - General knowledge question unrelated to enterprise
  - Context already in conversation/documents
  - Question is clarification, not new information
- Use knowledge_search when:
  - Question touches enterprise topic
  - Need to verify enterprise facts
  - User explicitly asks to search

#### Enhanced `<evidence_decisions>`
- If knowledge_search returns NO RESULTS → explicitly tell user
- Never provide speculation for unsourced answers

#### `<response_hierarchy>` (New)
Priority order for responding to questions:
1. Is this an enterprise question? → search knowledge base
2. Is question vague/needs clarification? → ask clarifying questions
3. Do I have sufficient grounded evidence? → answer with sources
4. If no evidence found → explicitly state "not found in knowledge base"
5. Never jump to speculation

### 2. Enhanced Knowledge Search Tool Description

Updated tool definition to include:
- ONLY use this tool when needing enterprise-specific information
- If query is too vague/generic → ask user for clarification FIRST
- If no results found → explicitly tell user, never fabricate
- Examples of vague terms to avoid: "information", "details", "company", "system" (without specific context)

### 3. Added Warning Against Vague Searches

Clear guidance in search_guidance section:
```
Vague searches that may return irrelevant results:
- Too generic: "information", "details", "data"
- Too broad: "company", "system", "project" (without specific identifiers)
- Unclear intent: "tell me more", "what about", "anything else"

Before searching with vague terms, ASK FOR CLARIFICATION from the user.
```

## Example: Test Query "Cho tôi template mẫu đăng ký môn học"

**Translation**: "Give me a template for course registration"

### Why This is a Good Test Case
1. **Enterprise-specific**: Course registration is an internal/organizational process
2. **Vague**: No specific details about:
   - Which system (academic system, HR system, third-party tool?)
   - What format (PDF, Word, Excel, online form?)
   - What department/school?
   - Current or new system?
3. **High risk for fabrication**: Agent might make up a template instead of searching or asking for details

### Expected Agent Behavior (With Enhanced Rules)

**Option A (Preferred)**: Ask for Clarification
```
I'd like to help you with a course registration template. 
To search the knowledge base effectively, could you clarify:
1. Which system or department is this for?
2. What format do you need (PDF template, form, online system)?
3. Is this for a specific academic program or organization?
4. Are you looking for a current template or creating a new one?

Once I have more details, I can search for the exact template you need.
```

**Option B**: Search & Report No Results
```
Searching knowledge base for course registration templates...

I searched for "course registration template" and "academic registration form" 
but did not find any matching documents in the knowledge base.

To help you better:
- Do you have a specific system name or platform?
- Is there a particular department or organization this is for?
- What specific information should the template include?

Please provide more details so I can assist you better.
```

### What Agent Should NOT Do
❌ "Here's a typical course registration template:" (fabricate)
❌ "Usually templates include name, student ID, courses..." (generic guessing)
❌ "Let me suggest a standard format:" (speculation)

## Implementation Details

### Files Modified
1. **backend/bothesis/agent/prompts/agent_base.md**
   - Enhanced with 6 new sections covering anti-fabrication rules
   - Total of 8 new clear rules/sections

2. **backend/bothesis/agent/tools/knowledge_search.py**
   - Updated tool description with explicit anti-fabrication guidance
   - Enhanced query schema documentation to warn against vague terms

### Tests Added
1. **tests/test_no_fabrication_flow.py**
   - 6 test cases verifying anti-fabrication rules are in place
   - Validates all key sections and rules are present
   - Tests response hierarchy, grounding, and search guidance

## Response Hierarchy Flow Diagram

```
User Question
    ↓
[Is this an enterprise question?]
    ├─ YES → Is the question vague?
    │         ├─ YES → Ask for clarification
    │         └─ NO → Search knowledge_base
    │
    └─ NO → Is context already available?
            ├─ YES → Answer directly with context
            └─ NO → General knowledge answer OK
                    (but don't fabricate enterprise facts)
                    
After Search
    ↓
[Knowledge base returned results?]
    ├─ YES → Sufficient evidence? 
    │         ├─ YES → Answer with citations
    │         └─ NO → Ask follow-up or search deeper
    └─ NO → Explicitly state: "I could not find this in knowledge base"
            Never: [fabricate, speculate, guess, provide "likely" answers]
            Instead: [Ask for clarification, narrow search, offer alternatives]
```

## Testing

Run the anti-fabrication flow tests:
```bash
source backend/.venv/bin/activate
python -m pytest tests/test_no_fabrication_flow.py -v
```

Expected output: All 6 tests PASSED

## Best Practices for Agent Interactions

### ✅ DO:
- Ask for clarification when question is vague
- Search knowledge base for all enterprise questions
- Explicitly state when information is not found
- Cite sources for all enterprise facts
- Keep asking until you have specific enough queries

### ❌ DON'T:
- Answer vague enterprise questions without clarification
- Fabricate templates, policies, or procedures
- Use words like "typically", "usually", "probably" for enterprise facts
- Combine unrelated questions in a single search
- Assume context when not explicitly provided

## Impact on User Experience

1. **More Accurate Responses**: Prevents hallucinated information
2. **Clearer Conversations**: Agent asks clarifying questions upfront
3. **Transparent Limitations**: Users know when information isn't available
4. **Better Grounding**: All answers tied to actual enterprise sources
5. **Reduced Support Burden**: Fewer follow-ups due to fabricated info

## Future Enhancements

- Add fallback suggestions when knowledge base is empty
- Implement feedback loop to improve knowledge base coverage
- Track queries that return no results to identify gaps
- Add user preference for clarification level (terse vs verbose)
