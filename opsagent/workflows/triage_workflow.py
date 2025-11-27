from dataclasses import dataclass
from typing import Literal

from agent_framework import (
    AgentExecutor,
    AgentExecutorRequest,
    AgentExecutorResponse,
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


# === Pydantic Models for Triage Output ===
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


# === Executors ===


@executor(id="store_query")
async def store_query(query: str, ctx: WorkflowContext[AgentExecutorRequest]) -> None:
    """Store original query and send to triage agent."""
    await ctx.set_shared_state("original_query", query)
    await ctx.send_message(
        AgentExecutorRequest(
            messages=[ChatMessage(Role.USER, text=query)], should_respond=True
        )
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


# === Agent Bridge Executors ===
# These executors check if their agent is needed and forward the question
class AgentBridge(Executor):
    """Bridge executor that checks if agent is needed and forwards the task question."""

    def __init__(self, agent_name: str, id: str):
        super().__init__(id=id)
        self._agent_name = agent_name

    @handler
    async def forward_if_needed(
        self, triage: TriageResult, ctx: WorkflowContext[AgentExecutorRequest]
    ) -> None:
        # Collect ALL tasks for this agent
        questions = [
            task.question for task in triage.tasks if task.agent == self._agent_name
        ]

        if not questions:
            # Agent not needed - don't send anything (will be excluded from fan-in)
            return

        # Combine multiple questions into a single message
        combined_question = "\n".join(f"- {q}" for q in questions) if len(questions) > 1 else questions[0]

        await ctx.send_message(
            AgentExecutorRequest(
                messages=[ChatMessage(Role.USER, text=combined_question)],
                should_respond=True,
            )
        )


# === Aggregator for Fan-In ===
class AggregateResponses(Executor):
    """Aggregate responses from specialized agents."""

    def __init__(self, id: str = "aggregate_responses"):
        super().__init__(id=id)

    @handler
    async def aggregate(
        self, results: list[AgentExecutorResponse], ctx: WorkflowContext[Never, str]
    ) -> None:
        # Build consolidated response
        sections = []
        for r in results:
            agent_name = (
                r.executor_id.replace("_executor", "").replace("_", " ").title()
            )
            sections.append(f"## {agent_name}\n{r.agent_run_response.text}")

        consolidated = "\n\n---\n\n".join(sections)
        await ctx.yield_output(consolidated)


# === Selection Function for Multi-Selection Edge Group ===
def select_agents(triage: TriageResult, target_ids: list[str]) -> list[str]:
    """Select which agent bridges to fan-out to based on triage result.

    target_ids order: [servicenow_bridge, log_analytics_bridge, service_health_bridge, reject_query]
    """
    servicenow_id, log_analytics_id, service_health_id, reject_id = target_ids

    if triage.should_reject or not triage.tasks:
        return [reject_id]

    # Return bridges for all agents that have tasks assigned
    selected = []
    agent_to_bridge = {
        "servicenow": servicenow_id,
        "log_analytics": log_analytics_id,
        "service_health": service_health_id,
    }
    for task in triage.tasks:
        bridge_id = agent_to_bridge.get(task.agent)
        if bridge_id and bridge_id not in selected:
            selected.append(bridge_id)

    return selected


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

    # Wrap agents as AgentExecutors for workflow
    triage_executor = AgentExecutor(triage, id="triage_agent")
    servicenow_executor = AgentExecutor(servicenow, id="servicenow_executor")
    log_analytics_executor = AgentExecutor(log_analytics, id="log_analytics_executor")
    service_health_executor = AgentExecutor(
        service_health, id="service_health_executor"
    )

    # Create bridge executors (fan-out targets that forward to agents)
    servicenow_bridge = AgentBridge(agent_name="servicenow", id="servicenow_bridge")
    log_analytics_bridge = AgentBridge(agent_name="log_analytics", id="log_analytics_bridge")
    service_health_bridge = AgentBridge(agent_name="service_health", id="service_health_bridge")

    aggregator = AggregateResponses()

    # Build workflow
    workflow = (
        WorkflowBuilder()
        .set_start_executor(store_query)
        .add_edge(store_query, triage_executor)
        .add_edge(triage_executor, parse_triage_output)
        # Conditional fan-out: select bridges for needed agents OR reject
        # The selection function returns multiple bridge IDs for parallel execution
        .add_multi_selection_edge_group(
            parse_triage_output,
            [servicenow_bridge, log_analytics_bridge, service_health_bridge, reject_query],
            selection_func=select_agents,
        )
        # Connect bridges to their respective agent executors
        .add_edge(servicenow_bridge, servicenow_executor)
        .add_edge(log_analytics_bridge, log_analytics_executor)
        .add_edge(service_health_bridge, service_health_executor)
        # Fan-in from all agents to aggregator
        .add_fan_in_edges(
            [servicenow_executor, log_analytics_executor, service_health_executor],
            aggregator,
        )
        .build()
    )

    return workflow
