"""Clarify Agent for handling ambiguous user requests.

This agent helps users refine unclear queries by providing
polite clarification requests and possible interpretations.
"""

from pathlib import Path

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from pydantic import BaseModel, Field

from ..utils.config_loader import load_agent_config
from ..utils.observability import observability_agent_middleware
from ..utils.settings import get_azure_openai_settings


class ClarifyOutput(BaseModel):
    """Structured output from clarify agent."""

    clarification_request: str = Field(
        description="Polite request for clarification"
    )
    possible_interpretations: list[str] = Field(
        default_factory=list,
        description="What user might have meant (2-4 options)",
    )


def create_clarify_agent() -> ChatAgent:
    """Create and return the Clarify agent for handling ambiguous requests."""
    config_path = Path(__file__).parent.parent / "config" / "clarify_agent.yaml"
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
        response_format=ClarifyOutput,
        middleware=[observability_agent_middleware],
    )
