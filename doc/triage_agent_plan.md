# Triage Agent Workflow Design

## Overview

The triage workflow routes user queries to specialized IT operations agents using a WorkflowBuilder-based design with conditional fan-out for parallel execution.

## Architecture

```
User Query
    → [store_query] - Store query in shared state
    → [triage_agent (AgentExecutor)] - Analyze and decompose query
    → [parse_triage_output] - Parse JSON output
    → [Multi-Selection Edge Group]
        ├── [reject_query] - If unrelated query
        └── [dispatch_to_agents] - If related query
            → [Fan-Out to selected agents IN PARALLEL]
                ├── servicenow_executor (AgentExecutor)
                ├── log_analytics_executor (AgentExecutor)
                └── service_health_executor (AgentExecutor)
            → [aggregate_responses (Fan-In)]
    → Final Output
```

## Key Design Decisions

### Why WorkflowBuilder instead of Agent-as-Tool?

| Aspect | Agent-as-Tool | WorkflowBuilder |
|--------|---------------|-----------------|
| Visibility | Black box - can't see tool calls in DevUI | Full visibility - each agent is an AgentExecutor |
| Execution | Sequential | Parallel via fan-out/fan-in |
| Control | LLM decides routing at runtime | Structured JSON → deterministic routing |

### Key Patterns Used

1. **`add_multi_selection_edge_group`** - Routes to dispatcher OR reject based on triage output
2. **`add_fan_out_edges` / `add_fan_in_edges`** - Parallel execution of multiple agents
3. **`target_id` in `ctx.send_message()`** - Dynamic routing to specific agents based on triage result

## Files

| File | Purpose |
|------|---------|
| `opsagent/agents/triage_agent.py` | Triage agent factory with `TriageOutput` Pydantic model |
| `opsagent/config/triage_agent.yaml` | Triage agent instructions and model settings |
| `opsagent/workflows/triage_workflow.py` | Main workflow with conditional fan-out |
| `main.py` | Entry point - serves the workflow via DevUI |

## Triage Output Format

```python
class TaskAssignment(BaseModel):
    question: str  # Decomposed question for the agent
    agent: Literal["servicenow", "log_analytics", "service_health"]

class TriageOutput(BaseModel):
    should_reject: bool  # True if query is unrelated
    reject_reason: str   # Reason for rejection
    tasks: list[TaskAssignment]  # List of agent assignments
```

## Testing Scenarios

| Query | Expected Behavior |
|-------|-------------------|
| "What's the weather?" | Reject with "I don't have knowledge..." |
| "List all open change requests" | Route to servicenow_executor only |
| "Check Databricks health" | Route to service_health_executor only |
| "Show failed pipelines" | Route to log_analytics_executor only |
| "Check health and list incidents" | Fan-out to service_health + servicenow in parallel |
| "Give me a full status report" | Fan-out to all 3 agents in parallel |

## Running

```bash
python main.py
```

Then access http://localhost:8090 to interact with the triage workflow.
