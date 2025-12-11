"""Dynamic Triage Agent for multi-step execution planning.

This agent operates in two modes:
- User Mode: Analyzes user queries and creates execution plans
- Review Mode: Evaluates reviewer feedback and decides on retry strategy
"""

from pathlib import Path
from typing import Literal

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from pydantic import BaseModel, Field

from ..utils.config_loader import load_agent_config
from ..utils.observability import observability_agent_middleware
from ..utils.settings import get_azure_openai_settings


class PlanStep(BaseModel):
    """A single step in the execution plan."""

    step: int = Field(description="Step number (1-based). Same step = parallel execution")
    agent: Literal["servicenow", "log_analytics", "service_health"] = Field(
        description="Target agent for this task"
    )
    question: str = Field(description="Clear, specific task for this agent")


class UserModeOutput(BaseModel):
    """Output when triage processes USER query (initial request)."""

    should_reject: bool = Field(
        default=False, description="True if query should be rejected"
    )
    reject_reason: str = Field(
        default="", description="Reason for rejection if should_reject is True"
    )
    clarify: bool = Field(
        default=False,
        description="If True with should_reject=True, route to clarify agent",
    )
    plan: list[PlanStep] = Field(
        default_factory=list, description="Execution plan with step numbers"
    )
    plan_reason: str = Field(
        default="", description="Explanation of why this plan was chosen"
    )


class ReviewModeOutput(BaseModel):
    """Output when triage processes REVIEWER feedback (after review agent)."""

    accept_review: bool = Field(
        description="True = accept feedback and execute new plan, False = reject feedback"
    )
    new_plan: list[PlanStep] = Field(
        default_factory=list,
        description="Additional/new plan if accepting review",
    )
    rejection_reason: str = Field(
        default="",
        description="Why current answer is sufficient (if rejecting review)",
    )


def create_user_mode_triage_agent() -> ChatAgent:
    """Create triage agent for user mode with UserModeOutput response format."""
    config_path = Path(__file__).parent.parent / "config" / "dynamic_triage_agent.yaml"
    config = load_agent_config(str(config_path))
    settings = get_azure_openai_settings()

    chat_client = AzureOpenAIChatClient(
        api_key=settings.api_key,
        endpoint=settings.endpoint,
        deployment_name=settings.deployment_name,
    )

    return ChatAgent(
        name=f"{config.name}-user-mode",
        description=config.description,
        instructions=config.instructions,
        chat_client=chat_client,
        response_format=UserModeOutput,
        middleware=[observability_agent_middleware],
    )


def create_review_mode_triage_agent() -> ChatAgent:
    """Create triage agent for review mode with ReviewModeOutput response format."""
    config_path = Path(__file__).parent.parent / "config" / "dynamic_triage_agent.yaml"
    config = load_agent_config(str(config_path))
    settings = get_azure_openai_settings()

    chat_client = AzureOpenAIChatClient(
        api_key=settings.api_key,
        endpoint=settings.endpoint,
        deployment_name=settings.deployment_name,
    )

    return ChatAgent(
        name=f"{config.name}-review-mode",
        description=config.description,
        instructions=config.instructions,
        chat_client=chat_client,
        response_format=ReviewModeOutput,
        middleware=[observability_agent_middleware],
    )
