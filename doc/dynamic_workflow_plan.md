# Dynamic Workflow Implementation Plan

## Overview

创建一个新的 `dynamic_workflow.py`，实现动态的多 agent 编排，支持：
- 动态规划执行顺序（sequential/parallel/mixed）
- Review 机制确保答案完整性
- Clarify 机制处理模糊问题
- 最多一次 review 循环，避免无限循环

## Architecture Diagram

```
                                    ┌─────────────────────┐
                                    │    User Query       │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                              ┌────────────────────────────────┐
                              │     Dynamic Triage Agent       │
                              │     (user_mode / review_mode)  │
                              └───────────────┬────────────────┘
                                              │
                        ┌─────────────────────┼─────────────────────┐
                        │                     │                     │
                        ▼                     ▼                     ▼
                ┌───────────────┐    ┌───────────────┐    ┌────────────────┐
                │ should_reject │    │    clarify    │    │  Execute Plan  │
                │    = true     │    │    = true     │    │                │
                │ clarify=false │    │               │    │                │
                └───────┬───────┘    └───────┬───────┘    └────────┬───────┘
                        │                    │                     │
                        ▼                    ▼                     ▼
                ┌───────────────┐    ┌───────────────┐    ┌────────────────┐
                │ Reject Node   │    │ Clarify Agent │    │  Orchestrator  │
                │ (direct msg)  │    │               │    │  (step-based)  │
                └───────────────┘    └───────────────┘    └────────┬───────┘
                                                                   │
                                                          ┌────────┴────────┐
                                                          │  Step Executor  │
                                                          │ (parallel/seq)  │
                                                          └────────┬────────┘
                                                                   │
                                                                   ▼
                                                          ┌────────────────┐
                                                          │  Review Agent  │
                                                          └────────┬───────┘
                                              ┌────────────────────┼────────────────────┐
                                              │                    │                    │
                                              ▼                    ▼                    ▼
                                    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
                                    │   Complete      │  │  Needs Retry    │  │  Triage Rejects │
                                    │   (Summarize)   │  │  (→ Triage)     │  │  Review Comment │
                                    └─────────────────┘  └─────────────────┘  └─────────────────┘
                                                                   │                    │
                                                                   ▼                    ▼
                                                         ┌─────────────────┐   ┌─────────────────┐
                                                         │ Dynamic Triage  │   │ Output Original │
                                                         │ (review_mode)   │   │ Aggregated Resp │
                                                         └────────┬────────┘   └─────────────────┘
                                                                  │
                                                                  ▼
                                                         (Execute New Plan)
```

## New Files to Create

### 1. Agents (opsagent/agents/)
- `dynamic_triage_agent.py` - 动态规划 agent，支持 user_mode 和 review_mode
- `review_agent.py` - 审核 agent，判断答案是否完整
- `clarify_agent.py` - 澄清 agent，礼貌地请求用户澄清

### 2. Configs (opsagent/config/)
- `dynamic_triage_agent.yaml` - 动态 triage 配置
- `review_agent.yaml` - Review agent 配置
- `clarify_agent.yaml` - Clarify agent 配置

### 3. Workflow (opsagent/workflows/)
- `dynamic_workflow.py` - 新的动态工作流

## Data Structures

### 1. Plan Step Structure

```python
class PlanStep(BaseModel):
    """A single step in the execution plan."""
    step: int                    # Step number (1-based), same step = parallel
    agent: Literal["servicenow", "log_analytics", "service_health"]
    question: str                # Clear, specific task for this agent
```

**Dependency Rule**: Step N automatically receives ALL outputs from step N-1 as context. No explicit `depends_on` needed.

### 2. Two Separate Output Models (based on input mode)

```python
class UserModeOutput(BaseModel):
    """Output when triage processes USER query (initial request)."""
    should_reject: bool
    reject_reason: str = ""
    clarify: bool = False        # If true, route to clarify agent instead of reject
    plan: list[PlanStep] = []    # Execution plan
    plan_reason: str = ""        # Explanation of why this plan was chosen

class ReviewModeOutput(BaseModel):
    """Output when triage processes REVIEWER feedback (after review agent)."""
    accept_review: bool              # True = accept feedback, False = reject feedback
    new_plan: list[PlanStep] = []    # Additional/new plan if accepting review
    rejection_reason: str = ""       # Why current answer is sufficient (if rejecting)
```

**Why Two Models:**
- User mode needs: reject/clarify logic, full plan
- Review mode needs: accept/reject decision, optional new plan
- Cleaner separation, no unused fields

### 3. Review Agent Output

```python
class ReviewOutput(BaseModel):
    """Structured output from review agent."""
    is_complete: bool                    # Whether all user questions are answered
    summary: str = ""                    # Final summary (if complete)
    missing_aspects: list[str] = []      # What's missing (if incomplete)
    suggested_approach: str = ""         # Suggestion for retry
    confidence: float = 0.0              # 0-1 confidence in assessment
```

### 4. Clarify Agent Output

```python
class ClarifyOutput(BaseModel):
    """Structured output from clarify agent."""
    clarification_request: str    # Polite request for clarification
    possible_interpretations: list[str]  # What user might have meant
```

## Workflow Implementation Details

### Phase 1: Input Processing

```python
@executor(id="store_query")
async def store_query(input: WorkflowInput, ctx: WorkflowContext) -> None:
    # Store conversation history
    # Store original query
    # Track if this is first run or retry
    await ctx.set_shared_state("is_retry", False)
    await ctx.set_shared_state("retry_count", 0)
```

### Phase 2: Dynamic Triage

The triage agent receives:
- **User mode**: Original user query + conversation history
- **Review mode**: Review agent's feedback + previous execution results

```python
class DynamicTriageExecutor(Executor):
    @handler
    async def handle_user_mode(self, request: UserModeRequest, ctx) -> None:
        # Generate execution plan based on user query
        pass

    @handler
    async def handle_review_mode(self, request: ReviewModeRequest, ctx) -> None:
        # Decide whether to accept reviewer's feedback or reject it
        # If accept: generate new plan
        # If reject: output existing response to user
        pass
```

### Phase 3: Conditional Routing

```python
def select_execution_path(triage: DynamicTriageOutput, targets: list[str]) -> list[str]:
    """Route to: reject, clarify, or execute."""
    reject_id, clarify_id, execute_id = targets

    if triage.should_reject:
        if triage.clarify:
            return [clarify_id]   # Polite clarification
        return [reject_id]        # Direct rejection

    return [execute_id]           # Execute the plan
```

### Phase 4: Dynamic Orchestrator

The orchestrator reads the plan and executes steps. **Key Logic:**
- Same step number → execute in parallel (asyncio.gather)
- Different step numbers → execute sequentially (step 1 → step 2 → ...)
- Step N receives ALL outputs from step N-1 as context

```python
class DynamicOrchestrator(Executor):
    def __init__(self, agents: dict[str, ChatAgent]):
        """Initialize with pre-created agents."""
        super().__init__(id="orchestrator")
        self._agents = agents  # {"servicenow": agent, "log_analytics": agent, ...}

    @handler
    async def execute_plan(self, triage: UserModeOutput, ctx: WorkflowContext) -> None:
        plan = triage.plan
        all_results = {}  # step_number -> list[{agent, question, response}]

        # Group tasks by step number
        steps_grouped = defaultdict(list)
        for task in plan:
            steps_grouped[task.step].append(task)

        # Execute steps in order (1, 2, 3, ...)
        for step_num in sorted(steps_grouped.keys()):
            tasks = steps_grouped[step_num]

            # Build context from previous step (N-1)
            prev_step = step_num - 1
            context = ""
            if prev_step in all_results:
                context_parts = []
                for result in all_results[prev_step]:
                    context_parts.append(
                        f"---\nAgent: {result['agent']}\n"
                        f"Question: {result['question']}\n"
                        f"Response: {result['response']}\n---"
                    )
                context = "Previous step results:\n" + "\n".join(context_parts)

            # Execute all tasks in this step IN PARALLEL
            step_results = await self._execute_step_parallel(tasks, context)
            all_results[step_num] = step_results

        # Store results and send to review
        await ctx.set_shared_state("execution_results", all_results)
        await ctx.send_message(ExecutionComplete(results=all_results))

    async def _execute_step_parallel(self, tasks: list[PlanStep], context: str) -> list:
        """Execute all tasks in a step concurrently using asyncio.gather."""
        async def run_single_task(task: PlanStep) -> dict:
            agent = self._agents[task.agent]
            # Build message with context if available
            message = task.question
            if context:
                message = f"{context}\n\nYour task: {task.question}"

            response = await agent.run(messages=[ChatMessage(Role.USER, text=message)])
            return {
                "agent": task.agent,
                "question": task.question,
                "response": response.text
            }

        # Execute ALL tasks in parallel
        results = await asyncio.gather(*[run_single_task(t) for t in tasks])
        return list(results)
```

**Example Execution:**
```
Plan: [
  {step: 1, agent: "servicenow", question: "List incidents"},
  {step: 1, agent: "log_analytics", question: "List pipelines"},
  {step: 2, agent: "service_health", question: "Check related services"}
]

Execution:
1. Step 1: Run servicenow AND log_analytics in parallel (asyncio.gather)
2. Wait for both to complete
3. Step 2: Run service_health with step 1 results as context
```

### Phase 5: Review Agent

```python
class ReviewExecutor(Executor):
    @handler
    async def review(self, execution: ExecutionComplete, ctx) -> None:
        original_query = await ctx.get_shared_state("original_query")
        retry_count = await ctx.get_shared_state("retry_count")

        # Review checks:
        # 1. Are all user questions answered?
        # 2. Is the information complete?
        # 3. Are there any obvious gaps?

        if review_result.is_complete or retry_count >= 1:
            # Output final summary
            await ctx.yield_output(review_result.summary)
        else:
            # Send feedback to triage for retry
            await ctx.set_shared_state("retry_count", retry_count + 1)
            await ctx.send_message(ReviewFeedback(
                missing=review_result.missing_aspects,
                suggestion=review_result.suggested_approach
            ))
```

### Phase 6: Review Mode Routing

```python
def handle_review_response(triage: DynamicTriageOutput, ctx) -> None:
    if not triage.accept_review:
        # Triage disagrees - output original response
        original_results = ctx.get_shared_state("execution_results")
        return aggregate_and_output(original_results)
    else:
        # Accept review - execute new plan
        return execute_new_plan(triage.plan)
```

## Agent Prompts (Key Points)

### Dynamic Triage Agent (User Mode)

```yaml
name: "dynamic-triage-agent"
description: "Plans multi-step agent execution based on user queries"
instructions: |
  You are a dynamic triage agent that plans multi-step agent execution.

  ## Your Task
  Analyze user query and create an execution plan with step numbers.

  ## Available Agents
  - **servicenow**: ServiceNow ITSM operations
    - Tools: list_change_requests, get_change_request, list_incidents, get_incident
    - Use for: CHG tickets, INC tickets, ITSM queries
  - **log_analytics**: Azure Data Factory pipeline monitoring
    - Tools: query_pipeline_status, get_pipeline_run_details, list_failed_pipelines
    - Use for: pipeline status, failures, ADF monitoring
  - **service_health**: Health monitoring
    - Tools: check_databricks_health, check_snowflake_health, check_azure_service_health
    - Use for: service status, health checks

  ## Planning Guidelines
  - Same step number = parallel execution (agents run at the same time)
  - Different step numbers = sequential (step 1 finishes before step 2 starts)
  - Step N receives ALL results from step N-1 as context
  - Can call same agent multiple times in different steps

  ## Output JSON Schema (UserModeOutput)
  {
    "should_reject": false,
    "reject_reason": "",
    "clarify": false,
    "plan": [
      {"step": 1, "agent": "servicenow", "question": "..."},
      {"step": 1, "agent": "log_analytics", "question": "..."},
      {"step": 2, "agent": "service_health", "question": "..."}
    ],
    "plan_reason": "..."
  }
```

### Dynamic Triage Agent (Review Mode)

```yaml
instructions: |
  You are receiving feedback from the review agent.

  ## Your Task
  Evaluate the reviewer's feedback and decide:
  - **Accept**: Create additional plan to address the gap
  - **Reject**: Explain why current answer is already sufficient

  ## Decision Guidelines
  - Accept if reviewer identifies a genuine gap that can be filled
  - Reject if reviewer's concern is unreasonable or already addressed
  - Be critical - don't blindly accept all feedback

  ## Output JSON Schema (ReviewModeOutput)
  {
    "accept_review": true,
    "new_plan": [
      {"step": 1, "agent": "log_analytics", "question": "..."}
    ],
    "rejection_reason": ""
  }
```

### Review Agent

```yaml
instructions: |
  You are a review agent that evaluates execution results.

  ## Your Task
  Given the user's original question and agent execution results:
  1. Determine if ALL aspects of the question are answered
  2. If complete, summarize the findings
  3. If incomplete, identify what's missing and suggest how to address it

  ## Important
  - Be specific about what's missing
  - Only flag as incomplete if there's a clear gap
  - You can only trigger ONE retry - make it count
  - If retry was already attempted, accept the result

  ## Available Agents (for suggestions)
  - servicenow: Change requests, incidents
  - log_analytics: Pipeline monitoring
  - service_health: Health checks
```

### Clarify Agent

```yaml
instructions: |
  You are a clarification agent that helps users refine their requests.

  ## Your Task
  When a query is related but unclear:
  1. Acknowledge what you understood
  2. Politely ask for clarification
  3. Offer possible interpretations

  ## Tone
  - Friendly and helpful
  - Never dismissive
  - Guide user toward valid queries
```

## Implementation Steps

### Step 1: Create Agent Configs (YAML files)
1. `opsagent/config/dynamic_triage_agent.yaml`
   - Dual-mode instructions (user_mode / review_mode)
   - Agent capability descriptions for planning
2. `opsagent/config/review_agent.yaml`
   - Review criteria and evaluation guidelines
3. `opsagent/config/clarify_agent.yaml`
   - Polite clarification templates

### Step 2: Create Agent Factories
1. `opsagent/agents/dynamic_triage_agent.py`
   - Factory: `create_dynamic_triage_agent()`
   - Response format: `DynamicTriageOutput`
2. `opsagent/agents/review_agent.py`
   - Factory: `create_review_agent()`
   - Response format: `ReviewOutput`
3. `opsagent/agents/clarify_agent.py`
   - Factory: `create_clarify_agent()`
   - Response format: `ClarifyOutput`

### Step 3: Create Dynamic Workflow
`opsagent/workflows/dynamic_workflow.py`
1. Data models: `PlanStep`, `DynamicTriageOutput`, `ReviewOutput`, `ClarifyOutput`
2. Executors:
   - `store_query` - Input handling
   - `DynamicTriageExecutor` - User/Review mode handler
   - `parse_triage_output` - Parse and route
   - `DynamicOrchestrator` - Step-based execution
   - `ReviewExecutor` - Evaluate completeness
   - `reject_query` - Direct rejection
   - `ClarifyExecutor` - Polite clarification
   - `AggregateResponses` - Final output
3. Workflow graph with multi-selection edges

### Step 4: Update Module Exports
1. `opsagent/agents/__init__.py` - Add new agent factories
2. `opsagent/workflows/__init__.py` - Add `create_dynamic_workflow`

### Step 5: Flask Integration
1. `flask_app.py` (around line 23):
   ```python
   from opsagent.workflows.dynamic_workflow import create_dynamic_workflow, WorkflowInput, MessageData
   ```
2. `flask_app.py` (around line 116):
   ```python
   WORKFLOW = create_triage_workflow()
   DYNAMIC_WORKFLOW = create_dynamic_workflow()
   DYNAMIC_PLAN = os.getenv("DYNAMIC_PLAN", "false").lower() == "true"
   ```
3. `flask_app.py` - Modify `call_llm()` function (line 208):
   ```python
   def call_llm(model: str, messages: List[Dict], use_dynamic: bool = False) -> str:
       workflow = DYNAMIC_WORKFLOW if use_dynamic else WORKFLOW
       # ... existing code with workflow variable
   ```
4. `flask_app.py` - Pass `use_dynamic=DYNAMIC_PLAN` in API endpoint (line 474)
5. `.env.example`:
   ```bash
   # Dynamic Planning Workflow (experimental)
   # When true: Uses dynamic_workflow with review loop
   # When false: Uses triage_workflow (default)
   DYNAMIC_PLAN=false
   ```

## Critical Files to Modify/Create

| File | Action | Description |
|------|--------|-------------|
| `opsagent/config/dynamic_triage_agent.yaml` | Create | Triage prompts with dual-mode instructions |
| `opsagent/config/review_agent.yaml` | Create | Review criteria & evaluation prompts |
| `opsagent/config/clarify_agent.yaml` | Create | Polite clarification prompts |
| `opsagent/agents/dynamic_triage_agent.py` | Create | Factory with `DynamicTriageOutput` |
| `opsagent/agents/review_agent.py` | Create | Factory with `ReviewOutput` |
| `opsagent/agents/clarify_agent.py` | Create | Factory with `ClarifyOutput` |
| `opsagent/workflows/dynamic_workflow.py` | Create | Main workflow with orchestrator |
| `opsagent/agents/__init__.py` | Modify | Export 3 new agent factories |
| `opsagent/workflows/__init__.py` | Modify | Export `create_dynamic_workflow` |
| `flask_app.py` | Modify | Add `/api/chat_dynamic` endpoint |
| `.env.example` | Modify | Add `DYNAMIC_PLAN=false` |

## Design Decisions (Confirmed)

### 1. Context Passing Format
**Decision**: Step N automatically receives ALL outputs from step N-1

Format passed to dependent agents:
```
Previous step results:
---
Agent: servicenow
Question: [curated question]
Response: [agent response]
---
Agent: log_analytics
Question: [curated question]
Response: [agent response]
---

Your task: [current step's curated question]
```

### 2. Retry Scope
**Decision**: Triage decides in review_mode

When review agent flags incomplete:
- Triage receives reviewer's feedback
- Triage decides whether to:
  - Re-plan from scratch with new approach
  - Add supplementary agent calls
  - Reject the review and output existing response

### 3. Flask Integration
**Decision**: New endpoint controlled by environment variable

- Create new endpoint `/api/chat_dynamic`
- Add `DYNAMIC_PLAN=true/false` to `.env.example`
- When `DYNAMIC_PLAN=true`, use dynamic_workflow
- Existing `/api/chat` continues to use triage_workflow

## Final Workflow Graph

```
WorkflowBuilder()
    .set_start_executor(store_query)
    .add_edge(store_query, triage_executor)
    .add_edge(triage_executor, parse_triage_output)
    .add_multi_selection_edge_group(
        parse_triage_output,
        [reject_query, clarify_executor, orchestrator],
        selection_func=select_execution_path
    )
    .add_edge(orchestrator, review_executor)
    .add_multi_selection_edge_group(
        review_executor,
        [aggregator, triage_executor],  # Complete → aggregate, Retry → triage
        selection_func=select_review_outcome
    )
    .build()
```

## Execution Flow Examples

### Example 1: Sequential Execution
User: "Check pipeline status, then get details for failed ones"

Triage plan (UserModeOutput):
```json
{
  "should_reject": false,
  "clarify": false,
  "plan": [
    {"step": 1, "agent": "log_analytics", "question": "List all pipeline statuses"},
    {"step": 2, "agent": "log_analytics", "question": "Get details for failed pipelines"}
  ],
  "plan_reason": "User wants sequential: first list all, then details for failed ones"
}
```

### Example 2: Parallel Execution
User: "Check health of all services"

Triage plan (UserModeOutput):
```json
{
  "should_reject": false,
  "clarify": false,
  "plan": [
    {"step": 1, "agent": "service_health", "question": "Check Databricks health"},
    {"step": 1, "agent": "service_health", "question": "Check Snowflake health"},
    {"step": 1, "agent": "service_health", "question": "Check Azure service health"}
  ],
  "plan_reason": "All health checks are independent, run in parallel"
}
```

### Example 3: Mixed with Review Retry
User: "Get all open incidents and check if related services are healthy"

**Step A - Initial plan (UserModeOutput):**
```json
{
  "should_reject": false,
  "clarify": false,
  "plan": [
    {"step": 1, "agent": "servicenow", "question": "List all open incidents"},
    {"step": 2, "agent": "service_health", "question": "Check health of services mentioned in incidents"}
  ],
  "plan_reason": "First get incidents, then check their related services"
}
```

**Step B - Review finds gap (ReviewOutput):**
```json
{
  "is_complete": false,
  "missing_aspects": ["Incident INC001234 mentions pipeline DW_Pipeline but its status wasn't checked"],
  "suggested_approach": "Use log_analytics to check pipeline status"
}
```

**Step C - Triage accepts review (ReviewModeOutput):**
```json
{
  "accept_review": true,
  "new_plan": [
    {"step": 1, "agent": "log_analytics", "question": "Check pipeline DW_Pipeline status"}
  ],
  "rejection_reason": ""
}
```
