# Parallel Workflow Implementation Journey

This document captures the iterative process of implementing parallel agent execution in the triage workflow, including what was tried, why it failed, and the final working solution.

## Problem Statement

**User Query**: "List all open change requests and tell me if snowflake and databricks is up and running?"

**Expected Behavior**: `servicenow-agent` and `service-health-agent` should execute **in parallel**.

**Observed Behavior**: Agents were executing **sequentially** - servicenow-agent completed before service-health-agent started.

---

## Iteration 1: Sequential `for` Loop with `target_id`

### Initial Implementation
```python
class DispatchToAgents(Executor):
    @handler
    async def dispatch(self, triage: TriageResult, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
        for task in triage.tasks:
            agent_executor_id = self._agent_id_map.get(task.agent)
            if agent_executor_id:
                await ctx.send_message(
                    AgentExecutorRequest(...),
                    target_id=agent_executor_id,  # Routes to specific agent
                )
```

### Why It Failed
Each `await ctx.send_message(..., target_id=X)` in a sequential for-loop causes the framework to process messages one at a time. The `target_id` parameter routes to a specific executor, bypassing the framework's parallel execution mechanism.

### Reference
- `samples/getting_started/workflows/parallelism/fan_out_fan_in_edges.py` - Shows dispatcher pattern

---

## Iteration 2: `asyncio.gather()` for Parallel Message Sending

### Change Made
```python
async def send_to_agent(task: TaskAssignment) -> None:
    agent_executor_id = self._agent_id_map.get(task.agent)
    if agent_executor_id:
        await ctx.send_message(
            AgentExecutorRequest(...),
            target_id=agent_executor_id,
        )

# Send to all agents in parallel using asyncio.gather
send_tasks = [asyncio.create_task(send_to_agent(task)) for task in triage.tasks]
await asyncio.gather(*send_tasks)
```

### Why It Failed
`asyncio.gather()` only parallelizes the **message sending** operations, but the underlying workflow framework still processes the targeted messages sequentially. The `target_id` parameter tells the framework to route to a specific executor, and the framework's internal message queue processes these one at a time.

### Reference
- `samples/getting_started/workflows/parallelism/map_reduce_and_visualization.py` (lines 97-98) - Shows `asyncio.gather()` pattern

### Lesson Learned
Parallelizing the Python `send_message` calls doesn't parallelize the actual executor invocations - that's controlled by the workflow framework's edge topology.

---

## Iteration 3: `add_multi_selection_edge_group` with Bridge Executors

### Change Made
Introduced `AgentBridge` executors between `parse_triage_output` and the agents:

```python
class AgentBridge(Executor):
    def __init__(self, agent_name: str, id: str):
        self._agent_name = agent_name

    @handler
    async def forward_if_needed(self, triage: TriageResult, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
        questions = [task.question for task in triage.tasks if task.agent == self._agent_name]
        if questions:
            await ctx.send_message(AgentExecutorRequest(...))

# Workflow
.add_multi_selection_edge_group(
    parse_triage_output,
    [servicenow_bridge, log_analytics_bridge, service_health_bridge, reject_query],
    selection_func=select_agents,  # Returns multiple bridge IDs
)
.add_edge(servicenow_bridge, servicenow_executor)
.add_edge(log_analytics_bridge, log_analytics_executor)
.add_edge(service_health_bridge, service_health_executor)
```

### Result
**This worked for parallel execution!** The `add_multi_selection_edge_group` returns multiple target IDs, and the framework executes them in parallel.

### Why It Was Not Ideal
The workflow graph became cluttered with 3 extra bridge nodes:
```
parse_triage_output
    → servicenow_bridge → servicenow_executor
    → log_analytics_bridge → log_analytics_executor
    → service_health_bridge → service_health_executor
```

### Reference
- `samples/getting_started/workflows/control-flow/multi_selection_edge_group.py` (lines 219-240) - Shows selection function returning multiple targets

---

## Iteration 4: Direct `FilteredAgentExecutor` with `add_multi_selection_edge_group`

### Change Made
Removed bridges, created `FilteredAgentExecutor` that directly invokes the agent:

```python
class FilteredAgentExecutor(Executor):
    def __init__(self, agent: ChatAgent, agent_key: str, id: str):
        self._agent = agent
        self._agent_key = agent_key

    @handler
    async def handle(self, triage: TriageResult, ctx: WorkflowContext[AgentResponse]) -> None:
        questions = [task.question for task in triage.tasks if task.agent == self._agent_key]
        if not questions:
            return  # Skip if no tasks
        response = await self._agent.run(messages=[ChatMessage(Role.USER, text=combined)])
        await ctx.send_message(AgentResponse(executor_id=self.id, text=response.text))

# Workflow
.add_multi_selection_edge_group(
    parse_triage_output,
    [servicenow_executor, log_analytics_executor, service_health_executor, reject_query],
    selection_func=select_agents,
)
.add_fan_in_edges(
    [servicenow_executor, log_analytics_executor, service_health_executor],
    aggregator,
)
```

### Why It Failed
**No output was produced!** The workflow went to `IDLE` state without invoking the aggregator.

**Root Cause**: `add_fan_in_edges` waits for **ALL** listed executors to produce output. But `add_multi_selection_edge_group` only invokes **SOME** of them based on the selection function. The aggregator was waiting for 3 responses but only 2 were ever sent.

### Reference
- `samples/getting_started/workflows/control-flow/multi_selection_edge_group.py` - Notice they do NOT use `add_fan_in_edges` - each branch has its own terminal executor that calls `yield_output`

### Lesson Learned
**`add_fan_in_edges` and `add_multi_selection_edge_group` are incompatible patterns** when selection doesn't include all fan-in sources.

---

## Iteration 5: Final Working Solution - Dispatcher with Fan-Out

### Architecture
```
parse_triage_output
    → add_multi_selection_edge_group
        → dispatcher → add_fan_out_edges → [ALL 3 agents] → add_fan_in_edges → aggregator
        → reject_query
```

### Key Components

**1. DispatchToAgents** - Simple broadcaster
```python
class DispatchToAgents(Executor):
    @handler
    async def dispatch(self, triage: TriageResult, ctx: WorkflowContext[TriageResult]) -> None:
        if not triage.should_reject and triage.tasks:
            await ctx.send_message(triage)  # Broadcast to all via fan-out edges
```

**2. FilteredAgentExecutor** - Each agent checks if it has tasks
```python
class FilteredAgentExecutor(Executor):
    @handler
    async def handle(self, triage: TriageResult, ctx: WorkflowContext[AgentResponse]) -> None:
        questions = [task.question for task in triage.tasks if task.agent == self._agent_key]

        if not questions:
            # CRITICAL: Send empty response for fan-in to work
            await ctx.send_message(AgentResponse(executor_id=self.id, text=""))
            return

        response = await self._agent.run(messages=[ChatMessage(Role.USER, text=combined)])
        await ctx.send_message(AgentResponse(executor_id=self.id, text=response.text))
```

**3. AggregateResponses** - Filters empty responses
```python
class AggregateResponses(Executor):
    @handler
    async def aggregate(self, results: list[AgentResponse], ctx: WorkflowContext[Never, str]) -> None:
        sections = []
        for r in results:
            if r.text:  # Only include non-empty responses
                agent_name = r.executor_id.replace("_executor", "").replace("_", " ").title()
                sections.append(f"## {agent_name}\n{r.text}")
        await ctx.yield_output("\n\n---\n\n".join(sections))
```

**4. Selection Function** - Simple dispatch vs reject
```python
def select_dispatch_or_reject(triage: TriageResult, target_ids: list[str]) -> list[str]:
    dispatch_id, reject_id = target_ids
    if triage.should_reject or not triage.tasks:
        return [reject_id]
    return [dispatch_id]
```

**5. Workflow Builder**
```python
workflow = (
    WorkflowBuilder()
    .set_start_executor(store_query)
    .add_edge(store_query, triage_executor)
    .add_edge(triage_executor, parse_triage_output)
    # Route to dispatcher OR reject
    .add_multi_selection_edge_group(
        parse_triage_output,
        [dispatcher, reject_query],
        selection_func=select_dispatch_or_reject,
    )
    # Fan-out from dispatcher to ALL agents (they filter internally)
    .add_fan_out_edges(
        dispatcher,
        [servicenow_executor, log_analytics_executor, service_health_executor],
    )
    # Fan-in from all agents to aggregator
    .add_fan_in_edges(
        [servicenow_executor, log_analytics_executor, service_health_executor],
        aggregator,
    )
    .build()
)
```

### Why It Works
1. **`add_multi_selection_edge_group`** handles the dispatch-vs-reject decision
2. **`add_fan_out_edges`** broadcasts to ALL agents in parallel
3. **Each agent sends a response** (empty if no tasks) so fan-in receives expected count
4. **`add_fan_in_edges`** collects all 3 responses and invokes aggregator
5. **Aggregator filters** empty responses before producing output

### Reference
- `samples/getting_started/devui/fanout_workflow/workflow.py` (lines 660-679) - Shows `add_fan_out_edges` → `add_fan_in_edges` pattern
- `samples/getting_started/workflows/parallelism/fan_out_fan_in_edges.py` - Shows parallel agent execution

---

## Summary of Key Lessons

| Pattern | Use Case | Limitation |
|---------|----------|------------|
| `for` loop with `target_id` | Route to specific executors | Sequential execution |
| `asyncio.gather()` on `send_message` | Parallel Python calls | Framework still processes sequentially |
| `add_multi_selection_edge_group` | Dynamic routing to subset | Incompatible with `add_fan_in_edges` |
| `add_fan_out_edges` | Broadcast to all targets | All targets always invoked |
| `add_fan_in_edges` | Collect from multiple sources | Waits for ALL sources |

### Golden Rule
**For parallel execution with aggregation:**
1. Use `add_fan_out_edges` to invoke ALL targets
2. Have each target send a response (even if empty)
3. Use `add_fan_in_edges` to collect all responses
4. Filter empty responses in the aggregator

### Workflow Visualization
```
store_query → triage_agent → parse_triage_output ─┬→ dispatcher ─┬→ servicenow_executor ──┬→ aggregate_responses
                                                  │              ├→ log_analytics_executor ┤
                                                  │              └→ service_health_executor┘
                                                  └→ reject_query
```

---

## Files Modified
- `opsagent/workflows/triage_workflow.py` - All iterations

## Sample References
- `samples/getting_started/workflows/parallelism/fan_out_fan_in_edges.py`
- `samples/getting_started/workflows/parallelism/map_reduce_and_visualization.py`
- `samples/getting_started/workflows/control-flow/multi_selection_edge_group.py`
- `samples/getting_started/workflows/agents/custom_agent_executors.py`
- `samples/getting_started/devui/fanout_workflow/workflow.py`
- `samples/getting_started/workflows/orchestration/concurrent_custom_agent_executors.py`
