"""Dynamic Workflow with multi-agent orchestration and review loop.

This workflow implements:
- Dynamic planning with step-based execution (sequential/parallel/mixed)
- Review mechanism to ensure answer completeness
- Clarify mechanism for ambiguous queries
- Maximum one review retry to avoid infinite loops
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from agent_framework import (
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

from ..agents.clarify_agent import ClarifyOutput
from ..agents.dynamic_triage_agent import (
    PlanStep,
    ReviewModeOutput,
    UserModeOutput,
)
from ..agents.review_agent import ReviewOutput


# === Pydantic Models for Input ===
class MessageData(BaseModel):
    """Raw message data for Flask compatibility."""

    role: str
    text: str


class WorkflowInput(BaseModel):
    """Input for the dynamic workflow."""

    query: str = ""  # Simple string input for DevUI
    messages: list[MessageData] = []  # Full message history for Flask


# === Internal Dataclasses for Routing ===
@dataclass
class TriageUserResult:
    """Result from triage in user mode."""

    should_reject: bool
    reject_reason: str
    clarify: bool
    plan: list[PlanStep]
    plan_reason: str
    original_query: str


@dataclass
class TriageReviewResult:
    """Result from triage in review mode."""

    accept_review: bool
    new_plan: list[PlanStep]
    rejection_reason: str


@dataclass
class ExecutionResult:
    """Result from a single agent execution."""

    agent: str
    question: str
    response: str


@dataclass
class StepResults:
    """Results from all steps of execution."""

    results: dict[int, list[ExecutionResult]] = field(default_factory=dict)
    original_query: str = ""


@dataclass
class ReviewRequest:
    """Request for review agent."""

    original_query: str
    execution_results: dict[int, list[ExecutionResult]]
    is_retry: bool


@dataclass
class ReviewDecision:
    """Decision from review agent."""

    is_complete: bool
    summary: str
    missing_aspects: list[str]
    suggested_approach: str
    confidence: float
    execution_results: dict[int, list[ExecutionResult]]
    original_query: str


@dataclass
class ClarifyRequest:
    """Request for clarify agent."""

    original_query: str


# === Request Types (must be defined before executors that use them) ===
@dataclass
class UserModeRequest:
    """Request to triage agent in user mode."""

    messages: list[ChatMessage]
    original_query: str


@dataclass
class ReviewModeRequest:
    """Request to triage agent in review mode."""

    review_feedback: ReviewDecision
    previous_results: dict[int, list[ExecutionResult]]
    original_query: str


# === Input Processing ===
@executor(id="store_query")
async def store_query(
    input: WorkflowInput, ctx: WorkflowContext[UserModeRequest]
) -> None:
    """Store conversation history and prepare for triage."""
    # Handle both input modes: query (DevUI) or messages (Flask)
    if input.messages:
        chat_messages = [
            ChatMessage(
                Role.USER if msg.role == "user" else Role.ASSISTANT,
                text=msg.text,
            )
            for msg in input.messages
        ]
    else:
        chat_messages = [ChatMessage(Role.USER, text=input.query)]

    # Store conversation history
    await ctx.set_shared_state("conversation_history", chat_messages)

    # Extract latest user query
    latest_query = ""
    for msg in reversed(chat_messages):
        if msg.role == Role.USER:
            latest_query = msg.text
            break
    await ctx.set_shared_state("original_query", latest_query)

    # Initialize retry tracking
    await ctx.set_shared_state("is_retry", False)
    await ctx.set_shared_state("retry_count", 0)

    # Send to triage in user mode
    await ctx.send_message(
        UserModeRequest(messages=chat_messages, original_query=latest_query)
    )


# === User Mode Triage Executor ===
class UserModeTriageExecutor(Executor):
    """Triage executor for initial user queries."""

    def __init__(self, agent: ChatAgent, id: str = "user_mode_triage"):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(
        self, request: UserModeRequest, ctx: WorkflowContext[TriageUserResult]
    ) -> None:
        """Process user query and generate execution plan."""
        prompt = self._build_prompt(request.messages)

        response = await self._agent.run(
            messages=[ChatMessage(Role.USER, text=prompt)]
        )

        # Parse response as UserModeOutput (strip markdown code blocks if present)
        output = UserModeOutput.model_validate_json(response.text)

        await ctx.send_message(
            TriageUserResult(
                should_reject=output.should_reject,
                reject_reason=output.reject_reason,
                clarify=output.clarify,
                plan=output.plan,
                plan_reason=output.plan_reason,
                original_query=request.original_query,
            )
        )

    def _build_prompt(self, messages: list[ChatMessage]) -> str:
        """Build prompt for user mode triage."""
        history = "\n".join(
            f"[{msg.role.value}]: {msg.text}" for msg in messages
        )
        return f"""## Mode: USER_MODE

Analyze this conversation and create an execution plan.

## Conversation History
{history}

## Instructions
Output a JSON object with UserModeOutput schema:
- should_reject: bool
- reject_reason: str (if rejecting)
- clarify: bool (if need clarification)
- plan: list of {{step, agent, question}}
- plan_reason: str

Remember: same step number = parallel, different step numbers = sequential."""


# === Review Mode Triage Executor ===
class ReviewModeTriageExecutor(Executor):
    """Triage executor for processing reviewer feedback."""

    def __init__(self, agent: ChatAgent, id: str = "review_mode_triage"):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(
        self, request: ReviewModeRequest, ctx: WorkflowContext[TriageReviewResult]
    ) -> None:
        """Process reviewer feedback and decide on retry strategy."""
        prompt = self._build_prompt(request)

        response = await self._agent.run(
            messages=[ChatMessage(Role.USER, text=prompt)]
        )

        # Parse response as ReviewModeOutput (strip markdown code blocks if present)
        output = ReviewModeOutput.model_validate_json(response.text)

        await ctx.send_message(
            TriageReviewResult(
                accept_review=output.accept_review,
                new_plan=output.new_plan,
                rejection_reason=output.rejection_reason,
            )
        )

    def _build_prompt(self, request: ReviewModeRequest) -> str:
        """Build prompt for review mode triage."""
        # Format execution results
        results_str = self._format_execution_results(request.previous_results)

        # Format review feedback
        feedback = request.review_feedback
        feedback_str = f"""- Missing aspects: {feedback.missing_aspects}
- Suggested approach: {feedback.suggested_approach}
- Confidence: {feedback.confidence}"""

        return f"""## Mode: REVIEW_MODE

The review agent found the following gaps in the response.

## Original Query
{request.original_query}

## Previous Execution Results
{results_str}

## Review Feedback
{feedback_str}

## Instructions
Decide whether to accept or reject this review feedback.
Output a JSON object with ReviewModeOutput schema:
- accept_review: bool
- new_plan: list of {{step, agent, question}} (if accepting)
- rejection_reason: str (if rejecting)

Be critical - only accept if the gap is genuine and addressable."""

    def _format_execution_results(
        self, results: dict[int, list[ExecutionResult]]
    ) -> str:
        """Format execution results for prompts."""
        parts = []
        for step_num in sorted(results.keys()):
            for result in results[step_num]:
                parts.append(
                    f"---\nStep {step_num} | Agent: {result.agent}\n"
                    f"Question: {result.question}\n"
                    f"Response: {result.response}\n---"
                )
        return "\n".join(parts) if parts else "(No results)"


# === Routing After User Mode Triage ===
@executor(id="route_user_triage")
async def route_user_triage(
    triage: TriageUserResult, ctx: WorkflowContext[TriageUserResult]
) -> None:
    """Route based on user mode triage result."""
    # Store plan for orchestrator
    await ctx.set_shared_state("current_plan", triage.plan)
    await ctx.send_message(triage)


def select_user_triage_path(
    triage: TriageUserResult, target_ids: list[str]
) -> list[str]:
    """Select path after user mode triage.

    target_ids order: [reject_query, clarify_executor, orchestrator]
    """
    reject_id, clarify_id, orchestrator_id = target_ids

    if triage.should_reject:
        if triage.clarify:
            return [clarify_id]
        return [reject_id]

    return [orchestrator_id]


# === Reject Handler ===
@executor(id="reject_query")
async def reject_query(
    triage: TriageUserResult, ctx: WorkflowContext[Never, str]
) -> None:
    """Handle rejected queries."""
    await ctx.yield_output(
        f"I don't have knowledge about that topic. {triage.reject_reason}\n\n"
        "I can only help with:\n"
        "- ServiceNow operations (change requests, incidents)\n"
        "- Azure Data Factory pipeline monitoring\n"
        "- Service health checks (Databricks, Snowflake, Azure)"
    )


# === Clarify Executor ===
class ClarifyExecutor(Executor):
    """Executor for clarification requests."""

    def __init__(self, agent: ChatAgent, id: str = "clarify_executor"):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def handle(
        self, triage: TriageUserResult, ctx: WorkflowContext[Never, str]
    ) -> None:
        """Generate clarification request."""
        prompt = f"""The user asked: "{triage.original_query}"

This query is related to data operations but is unclear or ambiguous.
Please provide a polite clarification request.

Output JSON with ClarifyOutput schema:
- clarification_request: str
- possible_interpretations: list[str]"""

        response = await self._agent.run(
            messages=[ChatMessage(Role.USER, text=prompt)]
        )

        output = ClarifyOutput.model_validate_json(response.text)

        # Format output for user
        interpretations = "\n".join(
            f"  - {interp}" for interp in output.possible_interpretations
        )
        message = f"{output.clarification_request}\n\nPossible interpretations:\n{interpretations}"

        await ctx.yield_output(message)


# === Dynamic Orchestrator ===
class DynamicOrchestrator(Executor):
    """Orchestrator that executes plans with step-based parallelism."""

    def __init__(self, agents: dict[str, ChatAgent], id: str = "orchestrator"):
        super().__init__(id=id)
        self._agents = agents

    @handler
    async def execute_plan(
        self, triage: TriageUserResult, ctx: WorkflowContext[ReviewRequest]
    ) -> None:
        """Execute the plan from user mode triage."""
        await self._execute(triage.plan, triage.original_query, ctx, is_retry=False)

    @handler
    async def execute_new_plan(
        self, triage: TriageReviewResult, ctx: WorkflowContext[ReviewRequest]
    ) -> None:
        """Execute new plan from review mode (retry)."""
        original_query = await ctx.get_shared_state("original_query")
        previous_results = await ctx.get_shared_state("execution_results") or {}

        # Execute new plan
        new_results = await self._run_plan(triage.new_plan, previous_results)

        # Merge with previous results (increment step numbers)
        max_step = max(previous_results.keys()) if previous_results else 0
        merged_results = dict(previous_results)
        for step_num, step_results in new_results.items():
            merged_results[max_step + step_num] = step_results

        # Store merged results
        await ctx.set_shared_state("execution_results", merged_results)

        # Send to review
        await ctx.send_message(
            ReviewRequest(
                original_query=original_query,
                execution_results=merged_results,
                is_retry=True,
            )
        )

    async def _execute(
        self,
        plan: list[PlanStep],
        original_query: str,
        ctx: WorkflowContext,
        is_retry: bool,
    ) -> None:
        """Execute a plan and send results to review."""
        all_results = await self._run_plan(plan, {})

        # Store results
        await ctx.set_shared_state("execution_results", all_results)

        # Send to review
        await ctx.send_message(
            ReviewRequest(
                original_query=original_query,
                execution_results=all_results,
                is_retry=is_retry,
            )
        )

    async def _run_plan(
        self,
        plan: list[PlanStep],
        existing_results: dict[int, list[ExecutionResult]],
    ) -> dict[int, list[ExecutionResult]]:
        """Run a plan with step-based parallelism."""
        all_results: dict[int, list[ExecutionResult]] = {}

        # Group tasks by step number
        steps_grouped: dict[int, list[PlanStep]] = defaultdict(list)
        for task in plan:
            steps_grouped[task.step].append(task)

        # Execute steps in order
        for step_num in sorted(steps_grouped.keys()):
            tasks = steps_grouped[step_num]

            # Build context from previous step (N-1)
            prev_step = step_num - 1
            context = ""
            prev_results = all_results.get(prev_step) or existing_results.get(prev_step)
            if prev_results:
                context_parts = []
                for result in prev_results:
                    context_parts.append(
                        f"---\nAgent: {result.agent}\n"
                        f"Question: {result.question}\n"
                        f"Response: {result.response}\n---"
                    )
                context = "Previous step results:\n" + "\n".join(context_parts)

            # Execute all tasks in this step in parallel
            step_results = await self._execute_step_parallel(tasks, context)
            all_results[step_num] = step_results

        return all_results

    async def _execute_step_parallel(
        self, tasks: list[PlanStep], context: str
    ) -> list[ExecutionResult]:
        """Execute all tasks in a step concurrently."""

        async def run_single_task(task: PlanStep) -> ExecutionResult:
            agent = self._agents[task.agent]

            # Build message with context if available
            message = task.question
            if context:
                message = f"{context}\n\nYour task: {task.question}"

            response = await agent.run(
                messages=[ChatMessage(Role.USER, text=message)]
            )

            return ExecutionResult(
                agent=task.agent,
                question=task.question,
                response=response.text,
            )

        # Execute ALL tasks in parallel
        results = await asyncio.gather(*[run_single_task(t) for t in tasks])
        return list(results)


# === Review Executor ===
class ReviewExecutor(Executor):
    """Executor for reviewing execution results."""

    def __init__(self, agent: ChatAgent, id: str = "review_executor"):
        super().__init__(id=id)
        self._agent = agent

    @handler
    async def review(
        self, request: ReviewRequest, ctx: WorkflowContext[ReviewDecision]
    ) -> None:
        """Review execution results for completeness."""
        retry_count = await ctx.get_shared_state("retry_count") or 0

        # Build review prompt
        results_str = self._format_results(request.execution_results)
        prompt = f"""## Review Request

## Original User Query
{request.original_query}

## Execution Results
{results_str}

## Context
- This is {"a retry attempt" if request.is_retry else "the first attempt"}
- Retry count: {retry_count}
- Maximum retries allowed: 1

## Instructions
Evaluate whether the execution results fully answer the user's query.
Output JSON with ReviewOutput schema:
- is_complete: bool
- summary: str (if complete, provide final user-facing summary)
- missing_aspects: list[str] (if incomplete)
- suggested_approach: str (if incomplete, how to address gaps)
- confidence: float (0.0 to 1.0)

{"IMPORTANT: This is a retry. Accept the result unless there's a critical gap." if request.is_retry else ""}
{"IMPORTANT: Maximum retries reached. Accept the result." if retry_count >= 1 else ""}"""

        response = await self._agent.run(
            messages=[ChatMessage(Role.USER, text=prompt)]
        )

        output = ReviewOutput.model_validate_json(response.text)

        await ctx.send_message(
            ReviewDecision(
                is_complete=output.is_complete,
                summary=output.summary,
                missing_aspects=output.missing_aspects,
                suggested_approach=output.suggested_approach,
                confidence=output.confidence,
                execution_results=request.execution_results,
                original_query=request.original_query,
            )
        )

    def _format_results(
        self, results: dict[int, list[ExecutionResult]]
    ) -> str:
        """Format execution results for review."""
        parts = []
        for step_num in sorted(results.keys()):
            for result in results[step_num]:
                parts.append(
                    f"---\nStep {step_num} | Agent: {result.agent}\n"
                    f"Question: {result.question}\n"
                    f"Response:\n{result.response}\n---"
                )
        return "\n".join(parts) if parts else "(No results)"


# === Review Outcome Routing ===
@executor(id="route_review")
async def route_review(
    decision: ReviewDecision, ctx: WorkflowContext[ReviewDecision]
) -> None:
    """Route based on review decision."""
    retry_count = await ctx.get_shared_state("retry_count") or 0

    # Store decision for potential retry
    await ctx.set_shared_state("review_decision", decision)

    # If incomplete and can retry, increment counter
    if not decision.is_complete and retry_count < 1:
        await ctx.set_shared_state("retry_count", retry_count + 1)
        await ctx.set_shared_state("is_retry", True)

    await ctx.send_message(decision)


def select_review_outcome(
    decision: ReviewDecision, target_ids: list[str]
) -> list[str]:
    """Select path after review.

    target_ids order: [aggregator, triage_review_mode]
    """
    aggregator_id, triage_id = target_ids

    if decision.is_complete:
        return [aggregator_id]

    # Incomplete - route to triage for potential retry
    return [triage_id]


# === Triage Review Mode Bridge ===
@executor(id="triage_review_bridge")
async def triage_review_bridge(
    decision: ReviewDecision, ctx: WorkflowContext[ReviewModeRequest]
) -> None:
    """Bridge review decision to triage in review mode."""
    retry_count = await ctx.get_shared_state("retry_count") or 0

    # If max retries reached, output directly
    if retry_count > 1:
        # Force completion
        await ctx.send_message(
            ReviewModeRequest(
                review_feedback=decision,
                previous_results=decision.execution_results,
                original_query=decision.original_query,
            )
        )
        return

    await ctx.send_message(
        ReviewModeRequest(
            review_feedback=decision,
            previous_results=decision.execution_results,
            original_query=decision.original_query,
        )
    )


# === Review Mode Response Routing ===
def select_triage_review_outcome(
    triage: TriageReviewResult, target_ids: list[str]
) -> list[str]:
    """Select path after triage review mode.

    target_ids order: [orchestrator_retry, output_existing]
    """
    orchestrator_id, output_id = target_ids

    if triage.accept_review and triage.new_plan:
        return [orchestrator_id]

    return [output_id]


# === Output Existing Response (when triage rejects review) ===
@executor(id="output_existing")
async def output_existing(
    triage: TriageReviewResult, ctx: WorkflowContext[Never, str]
) -> None:
    """Output existing response when triage rejects review feedback."""
    execution_results = await ctx.get_shared_state("execution_results")

    # Format and output existing results
    output = _format_final_output(execution_results, triage.rejection_reason)
    await ctx.yield_output(output)


# === Final Aggregator ===
class FinalAggregator(Executor):
    """Aggregate final response with review summary."""

    def __init__(self, id: str = "final_aggregator"):
        super().__init__(id=id)

    @handler
    async def aggregate(
        self, decision: ReviewDecision, ctx: WorkflowContext[Never, str]
    ) -> None:
        """Output final aggregated response."""
        if decision.summary:
            # Use review summary
            await ctx.yield_output(decision.summary)
        else:
            # Fall back to formatted results
            output = _format_final_output(decision.execution_results, "")
            await ctx.yield_output(output)


def _format_final_output(
    results: dict[int, list[ExecutionResult]], note: str = ""
) -> str:
    """Format execution results for final output."""
    sections = []

    for step_num in sorted(results.keys()):
        for result in results[step_num]:
            agent_name = result.agent.replace("_", " ").title()
            sections.append(f"## {agent_name}\n{result.response}")

    output = "\n\n---\n\n".join(sections)

    if note:
        output = f"{output}\n\n---\n\n*Note: {note}*"

    return output


# === Workflow Factory ===
def create_dynamic_workflow():
    """Create the dynamic workflow with review loop."""
    from ..agents.dynamic_triage_agent import (
        create_user_mode_triage_agent,
        create_review_mode_triage_agent,
    )
    from ..agents.review_agent import create_review_agent
    from ..agents.clarify_agent import create_clarify_agent
    from ..agents.servicenow_agent import create_servicenow_agent
    from ..agents.log_analytics_agent import create_log_analytics_agent
    from ..agents.service_health_agent import create_service_health_agent

    # Create agents - separate agents for user mode and review mode (each with its own response_format)
    user_mode_triage_agent = create_user_mode_triage_agent()
    review_mode_triage_agent = create_review_mode_triage_agent()
    review_agent = create_review_agent()
    clarify_agent = create_clarify_agent()
    servicenow_agent = create_servicenow_agent()
    log_analytics_agent = create_log_analytics_agent()
    service_health_agent = create_service_health_agent()

    # Create executors - use two separate triage executors for user mode and review mode
    user_mode_triage = UserModeTriageExecutor(user_mode_triage_agent)
    review_mode_triage = ReviewModeTriageExecutor(review_mode_triage_agent)

    clarify_executor = ClarifyExecutor(clarify_agent)

    orchestrator = DynamicOrchestrator(
        agents={
            "servicenow": servicenow_agent,
            "log_analytics": log_analytics_agent,
            "service_health": service_health_agent,
        }
    )

    review_executor = ReviewExecutor(review_agent)
    aggregator = FinalAggregator()

    # Build workflow
    workflow = (
        WorkflowBuilder(
            name="Dynamic Ops Workflow",
            description="Dynamic multi-agent workflow with planning, execution, and review loop",
        )
        # Phase 1: Input processing -> User mode triage
        .set_start_executor(store_query)
        .add_edge(store_query, user_mode_triage)
        # Phase 2: User mode routing
        .add_edge(user_mode_triage, route_user_triage)
        .add_multi_selection_edge_group(
            route_user_triage,
            [reject_query, clarify_executor, orchestrator],
            selection_func=select_user_triage_path,
        )
        # Phase 3: Orchestrator to review
        .add_edge(orchestrator, review_executor)
        # Phase 4: Review outcome routing
        .add_edge(review_executor, route_review)
        .add_multi_selection_edge_group(
            route_review,
            [aggregator, triage_review_bridge],
            selection_func=select_review_outcome,
        )
        # Phase 5: Review mode handling -> Review mode triage (separate executor)
        .add_edge(triage_review_bridge, review_mode_triage)
        # Phase 6: Review mode triage outcome
        .add_multi_selection_edge_group(
            review_mode_triage,
            [orchestrator, output_existing],
            selection_func=select_triage_review_outcome,
        )
        .build()
    )

    return workflow
