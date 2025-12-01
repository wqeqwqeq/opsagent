from pathlib import Path
from typing import Literal

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from pydantic import BaseModel

from ..observability import (
    observability_agent_middleware,
    observability_function_middleware,
)
from ..utils.config_loader import load_agent_config
from ..utils.settings import get_azure_openai_settings


class TaskAssignment(BaseModel):
    """A single task assignment to a specialized agent."""

    question: str
    agent: Literal["servicenow", "log_analytics", "service_health"]


class TriageOutput(BaseModel):
    """Structured output from the triage agent."""

    should_reject: bool
    reject_reason: str
    tasks: list[TaskAssignment]


def create_triage_agent() -> ChatAgent:
    """Create and return the Triage agent."""
    config_path = Path(__file__).parent.parent / "config" / "triage_agent.yaml"
    config = load_agent_config(str(config_path))
    settings = get_azure_openai_settings()

    chat_client = AzureOpenAIChatClient(
        api_key=settings.api_key,
        endpoint=settings.endpoint,
        deployment_name=settings.deployment_name,
    )

    return ChatAgent(
        name=config.name,
        description=config.description,
        instructions=config.instructions,
        chat_client=chat_client,
        response_format=TriageOutput,
        middleware=[
            observability_agent_middleware,
            observability_function_middleware,
        ],
    )
