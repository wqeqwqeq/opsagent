from dataclasses import dataclass
from typing import Literal

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
    ChatAgent,
    ChatMessage,
    Executor,
    Role,
    WorkflowBuilder,
    WorkflowContext,
    executor,
    handler,
)
from pydantic import BaseModel
from typing_extensions import Never


# === Custom Response for Fan-In ===
@dataclass
class AgentResponse:
    """Response from a filtered agent executor for fan-in aggregation."""

    executor_id: str
    text: str


# === Pydantic Models for Input/Output ===
class MessageData(BaseModel):
    """Raw message data for DevUI compatibility."""

    role: str
    text: str


class TaskAssignment(BaseModel):
    """A single task assignment to a specialized agent."""

    question: str
    agent: Literal["servicenow", "log_analytics", "service_health"]


class TriageOutput(BaseModel):
    """Structured output from the triage agent."""

    should_reject: bool
    reject_reason: str
    tasks: list[TaskAssignment]


# === Dataclass for workflow routing ===
@dataclass
class TriageResult:
    """Internal dataclass for routing decisions in the workflow."""

    should_reject: bool
    reject_reason: str
    tasks: list[TaskAssignment]
    original_query: str


# === Input type for workflow ===
class WorkflowInput(BaseModel):
    """Input for the triage workflow."""

    query: str = ""  # Simple string input for DevUI
    messages: list[MessageData] = []  # Full message history for Flask


# === Executors ===


@executor(id="store_query")
async def store_query(
    input: WorkflowInput, ctx: WorkflowContext[AgentExecutorRequest]
) -> None:
    """Store conversation history and send to triage agent."""
    # Handle both input modes: query (DevUI) or messages (Flask)
    if input.messages:
        # Flask mode: convert MessageData to ChatMessage
        chat_messages = [
            ChatMessage(
                Role.USER if msg.role == "user" else Role.ASSISTANT,
                text=msg.text,
            )
            for msg in input.messages
        ]
    else:
        # DevUI mode: create single user message from query
        chat_messages = [ChatMessage(Role.USER, text=input.query)]

    # Store the full conversation history for reference
    await ctx.set_shared_state("conversation_history", chat_messages)

    # Extract latest user query for original_query (used in TriageResult)
    latest_query = ""
    for msg in reversed(chat_messages):
        if msg.role == Role.USER:
            latest_query = msg.text
            break
    await ctx.set_shared_state("original_query", latest_query)

    # Send full history to triage agent
    await ctx.send_message(
        AgentExecutorRequest(messages=chat_messages, should_respond=True)
    )


@executor(id="parse_triage_output")
async def parse_triage_output(
    response: AgentExecutorResponse, ctx: WorkflowContext[TriageResult]
) -> None:
    """Parse triage agent JSON output into TriageResult for routing."""
    triage = TriageOutput.model_validate_json(response.agent_run_response.text)
    original_query = await ctx.get_shared_state("original_query")

    # Store tasks in shared state for agent bridges to access
    await ctx.set_shared_state("tasks", triage.tasks)

    await ctx.send_message(
        TriageResult(
            should_reject=triage.should_reject,
            reject_reason=triage.reject_reason,
            tasks=triage.tasks,
            original_query=original_query,
        )
    )


@executor(id="reject_query")
async def reject_query(triage: TriageResult, ctx: WorkflowContext[Never, str]) -> None:
    """Handle rejected queries."""
    await ctx.yield_output(
        f"I don't have knowledge about that topic. {triage.reject_reason}\n\n"
        "I can only help with:\n"
        "- ServiceNow operations (change requests, incidents)\n"
        "- Azure Data Factory pipeline monitoring\n"
        "- Service health checks (Databricks, Snowflake, Azure)"
    )


# === Dispatcher for Fan-Out ===
class DispatchToAgents(Executor):
    """Dispatches triage result to all agent executors for parallel processing."""

    def __init__(self, id: str = "dispatch_to_agents"):
        super().__init__(id=id)

    @handler
    async def dispatch(
        self, triage: TriageResult, ctx: WorkflowContext[TriageResult]
    ) -> None:
        # Only dispatch if not rejected and has tasks
        if not triage.should_reject and triage.tasks:
            # Send triage result to all agents (fan-out edges will route it)
            await ctx.send_message(triage)


# === Filtered Agent Executor ===
# Custom executor that filters tasks and invokes the wrapped agent directly
class FilteredAgentExecutor(Executor):
    """Agent executor that filters tasks and invokes the wrapped agent."""

    def __init__(self, agent: ChatAgent, agent_key: str, id: str):
        super().__init__(id=id)
        self._agent = agent
        self._agent_key = agent_key  # "servicenow", "log_analytics", "service_health"

    @handler
    async def handle(
        self, triage: TriageResult, ctx: WorkflowContext[AgentResponse]
    ) -> None:
        # Collect all tasks for this agent
        questions = [
            task.question for task in triage.tasks if task.agent == self._agent_key
        ]

        if not questions:
            # No tasks for this agent - send empty response for fan-in
            await ctx.send_message(
                AgentResponse(
                    executor_id=self.id,
                    text="",  # Empty response, will be filtered in aggregator
                )
            )
            return

        # Combine questions if multiple
        combined = (
            "\n".join(f"- {q}" for q in questions)
            if len(questions) > 1
            else questions[0]
        )

        # Invoke the agent (ChatAgent.run() returns AgentRunResponse)
        response = await self._agent.run(
            messages=[ChatMessage(Role.USER, text=combined)]
        )

        # Send response for fan-in aggregation
        await ctx.send_message(
            AgentResponse(
                executor_id=self.id,
                text=response.text,
            )
        )


# === Aggregator for Fan-In ===
class AggregateResponses(Executor):
    """Aggregate responses from specialized agents."""

    def __init__(self, id: str = "aggregate_responses"):
        super().__init__(id=id)

    @handler
    async def aggregate(
        self, results: list[AgentResponse], ctx: WorkflowContext[Never, str]
    ) -> None:
        # Build consolidated response, filtering out empty responses
        sections = []
        for r in results:
            if r.text:  # Only include non-empty responses
                agent_name = (
                    r.executor_id.replace("_executor", "").replace("_", " ").title()
                )
                sections.append(f"## {agent_name}\n{r.text}")

        consolidated = "\n\n---\n\n".join(sections)
        await ctx.yield_output(consolidated)


# === Selection Function for Dispatch vs Reject ===
def select_dispatch_or_reject(triage: TriageResult, target_ids: list[str]) -> list[str]:
    """Select dispatcher or reject based on triage result.

    target_ids order: [dispatch_to_agents, reject_query]
    """
    dispatch_id, reject_id = target_ids

    if triage.should_reject or not triage.tasks:
        return [reject_id]

    return [dispatch_id]


# === Workflow Factory ===
def create_triage_workflow():
    """Create the triage workflow with conditional fan-out."""
    from ..agents.triage_agent import create_triage_agent
    from ..agents.servicenow_agent import create_servicenow_agent
    from ..agents.log_analytics_agent import create_log_analytics_agent
    from ..agents.service_health_agent import create_service_health_agent

    # Create all agents using factory functions
    triage = create_triage_agent()
    servicenow = create_servicenow_agent()
    log_analytics = create_log_analytics_agent()
    service_health = create_service_health_agent()

    # Triage uses standard AgentExecutor (for structured output)
    triage_executor = AgentExecutor(triage, id="triage_agent")

    # Dispatcher routes to all agents
    dispatcher = DispatchToAgents()

    # Wrap domain agents with FilteredAgentExecutor (each checks if it has tasks)
    servicenow_executor = FilteredAgentExecutor(
        servicenow, "servicenow", id="servicenow_executor"
    )
    log_analytics_executor = FilteredAgentExecutor(
        log_analytics, "log_analytics", id="log_analytics_executor"
    )
    service_health_executor = FilteredAgentExecutor(
        service_health, "service_health", id="service_health_executor"
    )

    aggregator = AggregateResponses()

    # Build workflow
    workflow = (
        WorkflowBuilder(
            name = 'Data Ops Triage Workflow',
            description = 'Routes data ops queries to specialized agents for ServiceNow, Log Analytics, and Service Health.'
        )
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

    return workflow
