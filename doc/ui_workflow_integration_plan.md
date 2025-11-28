# Plan: Integrate UI with Triage Workflow

## Overview

Integrate the Flask UI (`opsagent/ui/`) with the triage workflow (`opsagent/workflows/triage_workflow.py`) to replace the LLM stub with actual workflow execution, maintaining full conversation context across turns.

## Design Decisions

- **Triage scope**: Re-triage on each turn with full conversation history
- **History source**: Redis first, fallback to PostgreSQL (existing write-through pattern)
- **Execution mode**: `workflow.run()` (blocking) for this phase

---

## Implementation Plan

### Step 1: Modify Workflow to Accept Message History

**File**: `opsagent/workflows/triage_workflow.py`

The workflow currently accepts a single `str` query. Modify it to accept a list of messages for multi-turn context.

**Changes**:

1. Change `store_query` executor signature from `query: str` to `messages: list[ChatMessage]`
2. Store full message history in shared state
3. Pass all messages to triage agent (not just latest)

```python
# New input type for workflow
@dataclass
class WorkflowInput:
    messages: list[ChatMessage]  # Full conversation history

@executor(id="store_query")
async def store_query(input: WorkflowInput, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Store conversation history and send to triage agent."""
    await ctx.set_shared_state("conversation_history", input.messages)
    await ctx.send_message(
        AgentExecutorRequest(
            messages=input.messages,  # Full history to triage
            should_respond=True
        )
    )
```

### Step 2: Update Triage Agent to Summarize Context

**File**: `opsagent/config/triage_agent.yaml`

The triage agent should focus on the **LATEST question** and use history only to resolve references. Update the instructions:

```yaml
name: "triage-agent"
description: "Routes user queries to specialized IT operations agents"
model:
  api_version: "2024-12-01-preview"
  model_id: "gpt-4.1"
instructions: |
  You are a triage agent for IT operations. Your job is to analyze the user's **LATEST question** and route it to the appropriate specialized agent(s).

  ## IMPORTANT: Focus on the Latest Question
  - **Primary focus**: The user's most recent message (the last user message in the conversation)
  - **Conversation history**: Use previous messages ONLY as context to resolve references (e.g., "that incident", "the failed ones", "show me more details")
  - Do NOT re-process or re-route previous questions - only handle the current one

  ## Specialized Agents Available:
  - **servicenow**: ServiceNow ITSM operations - change requests (CHG), incidents (INC)
  - **log_analytics**: Azure Data Factory pipeline monitoring - pipeline status, failed pipelines
  - **service_health**: Service health checks - Databricks, Snowflake, Azure services

  ## Your Task:
  1. Identify what the user is asking in their LATEST message
  2. If UNRELATED to any specialized agent, set should_reject=true
  3. If related, create task(s) for appropriate agent(s)
  4. When the latest question references something from history (e.g., "show details for that"), resolve the reference into a clear, specific, self-contained task question

  ## Output Format (JSON):
  {
    "should_reject": false,
    "reject_reason": "",
    "tasks": [
      {"question": "Clear, specific task question", "agent": "agent_name"}
    ]
  }

  ## Examples:

  ### Example 1: Simple question (no history needed)
  User: "List all open change requests"
  → Task: {"question": "List all open change requests", "agent": "servicenow"}

  ### Example 2: Follow-up with reference to history
  History: User asked "List incidents", assistant showed INC001234, INC005678
  Latest: "show me details for INC001234"
  → Task: {"question": "Show details for incident INC001234", "agent": "servicenow"}

  ### Example 3: Ambiguous reference resolved from context
  History: User asked "Check pipeline status"
  Latest: "what about the failed ones?"
  → Task: {"question": "List failed Azure Data Factory pipelines", "agent": "log_analytics"}

  ### Example 4: Rejection
  Latest: "What's the weather?"
  → should_reject: true, reject_reason: "Weather is not related to IT operations"
```

**No changes needed to FilteredAgentExecutor** - specialized agents receive only the clear, specific task question from triage, not full conversation history.

### Step 3: Replace call_llm_stub in Flask App

**File**: `opsagent/ui/flask_app.py`

Add imports and workflow initialization at the top, then replace the stub:

```python
# At top of file, add imports
import asyncio
from agent_framework import ChatMessage, Role
from opsagent.workflows.triage_workflow import create_triage_workflow, WorkflowInput

# Create workflow instance at module level (after imports)
WORKFLOW = create_triage_workflow()

# Helper function to convert Flask messages to ChatMessage
def convert_messages(messages: List[Dict]) -> List[ChatMessage]:
    """Convert Flask message format to ChatMessage objects."""
    result = []
    for msg in messages:
        role = Role.USER if msg["role"] == "user" else Role.ASSISTANT
        result.append(ChatMessage(role, text=msg["content"]))
    return result

# Replace call_llm_stub function (around line 146)
def call_llm(model: str, messages: List[Dict]) -> str:
    """Execute the triage workflow with conversation history."""
    try:
        chat_messages = convert_messages(messages)
        input_data = WorkflowInput(messages=chat_messages)

        # Run async workflow synchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(WORKFLOW.run(input_data))
        finally:
            loop.close()

        # Extract output
        outputs = result.get_outputs()
        if outputs:
            return outputs[0]
        return "No response from workflow"

    except Exception as e:
        logger.error(f"Workflow execution failed: {e}")
        return f"Error: Unable to process request. {str(e)}"
```

Update the `api_send_message()` function to use the new `call_llm()`:

```python
# In api_send_message() around line 332
# Change: assistant_text = call_llm_stub(conv["model"], conv["messages"])
# To:     assistant_text = call_llm(conv["model"], conv["messages"])
```

### Step 4: Storage Integration (No Changes Needed)

**File**: `opsagent/ui/flask_app.py`

The existing `api_get_conversation()` endpoint already loads full conversation with messages from storage (Redis first, fallback to PostgreSQL). No changes needed here - the ChatHistoryManager handles this.

The flow is:
1. User sends message → Flask receives with `conversation_id`
2. Flask loads conversation from `HISTORY.get_conversation(id, user_id)` (Redis → PostgreSQL)
3. Appends user message to `conv["messages"]`
4. Calls `call_llm(model, conv["messages"])` with full history
5. Workflow runs with full context
6. Saves updated conversation via `HISTORY.save_conversation()` (write-through to both)

### Step 5: Environment Configuration

**File**: `opsagent/ui/.env` (update)

Add Azure OpenAI configuration required by the workflow:

```env
# Existing UI config...
CHAT_HISTORY_MODE=redis

# Add workflow/agent configuration
AZURE_OPENAI_API_KEY=<your-key>
AZURE_OPENAI_ENDPOINT=https://stanleyai.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=<deployment-name>
```

### Step 6: Update Dependencies

**File**: `opsagent/ui/pyproject.toml`

Add the agent framework dependency (or reference the parent package):

```toml
[project]
dependencies = [
    # existing deps...
    "agent-framework",  # or local path reference
]
```

---

## File Changes Summary

| File | Action | Description |
|------|--------|-------------|
| `opsagent/workflows/triage_workflow.py` | Modify | Accept `WorkflowInput` with message list for multi-turn context |
| `opsagent/config/triage_agent.yaml` | Modify | Focus on latest question, use history only for reference resolution |
| `opsagent/ui/flask_app.py` | Modify | Import workflow, replace `call_llm_stub` with `call_llm` |
| `opsagent/ui/.env` | Update | Add Azure OpenAI credentials |
| `opsagent/ui/pyproject.toml` | Update | Add agent-framework dependency |

---

## Data Flow Diagram

```
User Message → Flask API
                  ↓
         Load conversation from storage
         (Redis → PostgreSQL fallback)
                  ↓
         Append user message to history
                  ↓
         call_llm(model, messages)
                  ↓
         Convert to ChatMessage list
                  ↓
         workflow.run(WorkflowInput)
                  ↓
    ┌─────────────────────────────────────┐
    │  Triage Agent                        │
    │  - Sees full history                 │
    │  - Focuses on LATEST question        │
    │  - Resolves references from context  │
    │  → Creates specific task questions   │
    └─────────────────────────────────────┘
                  ↓
    ┌─────────────────────────────────────┐
    │ Specialized Agents                   │
    │ (receive specific task question only)│
    │ - ServiceNow                         │
    │ - Log Analytics                      │
    │ - Service Health                     │
    └─────────────────────────────────────┘
                  ↓
         Aggregate responses
                  ↓
         Return to Flask
                  ↓
         Save conversation to storage
         (PostgreSQL + Redis write-through)
                  ↓
         Return response to UI
```

---

## Testing Checklist

1. [ ] Single-turn query works (new conversation)
2. [ ] Multi-turn context preserved (follow-up questions work)
3. [ ] Rejected queries return appropriate message
4. [ ] Storage write-through works (check both Redis and PostgreSQL)
5. [ ] Conversation reload from cache works
6. [ ] Error handling for workflow failures
