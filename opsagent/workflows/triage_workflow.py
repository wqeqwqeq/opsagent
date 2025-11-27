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


# === Dispatcher for Conditional Fan-Out ===
class DispatchToAgents(Executor):
    """Dispatch decomposed questions to selected agents."""

    def __init__(self, agent_id_map: dict[str, str], id: str = "dispatch_to_agents"):
        super().__init__(id=id)
        self._agent_id_map = agent_id_map  # {"servicenow": "servicenow_executor", ...}

    @handler
    async def dispatch(
        self, triage: TriageResult, ctx: WorkflowContext[AgentExecutorRequest]
    ) -> None:
        # Store tasks for aggregator to use later
        await ctx.set_shared_state("tasks", triage.tasks)

        for task in triage.tasks:
            agent_executor_id = self._agent_id_map.get(task.agent)
            if agent_executor_id:
                await ctx.send_message(
                    AgentExecutorRequest(
                        messages=[ChatMessage(Role.USER, text=task.question)],
                        should_respond=True,
                    ),
                    target_id=agent_executor_id,
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
    """Select which agents to fan-out to based on triage result.

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

    # Wrap agents as AgentExecutors for workflow
    triage_executor = AgentExecutor(triage, id="triage_agent")
    servicenow_executor = AgentExecutor(servicenow, id="servicenow_executor")
    log_analytics_executor = AgentExecutor(log_analytics, id="log_analytics_executor")
    service_health_executor = AgentExecutor(
        service_health, id="service_health_executor"
    )

    # Create dispatcher and aggregator
    agent_id_map = {
        "servicenow": "servicenow_executor",
        "log_analytics": "log_analytics_executor",
        "service_health": "service_health_executor",
    }
    dispatcher = DispatchToAgents(agent_id_map=agent_id_map)
    aggregator = AggregateResponses()

    # Build workflow
    workflow = (
        WorkflowBuilder(
        )
        .set_start_executor(store_query)
        .add_edge(store_query, triage_executor)
        .add_edge(triage_executor, parse_triage_output)
        # Conditional routing: dispatch to agents OR reject
        .add_multi_selection_edge_group(
            parse_triage_output,
            [dispatcher, reject_query],
            selection_func=select_agents,
        )
        # Fan-out from dispatcher to all 3 agent executors
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
