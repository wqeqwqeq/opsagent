"""Review Agent for evaluating execution results.

This agent reviews the output from specialized agents and determines
if the user's query has been fully answered.
"""

from pathlib import Path

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient
from pydantic import BaseModel, Field

from ..utils.config_loader import load_agent_config
from ..utils.observability import observability_agent_middleware
from ..utils.settings import get_azure_openai_settings


class ReviewOutput(BaseModel):
    """Structured output from review agent."""

    is_complete: bool = Field(
        description="Whether all user questions are adequately answered"
    )
    summary: str = Field(
        default="", description="Final summary of findings (if complete)"
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="What information is missing (if incomplete)",
    )
    suggested_approach: str = Field(
        default="",
        description="Suggestion for how to address gaps using available agents",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in assessment (0.0 to 1.0)",
    )


def create_review_agent() -> ChatAgent:
    """Create and return the Review agent for result evaluation."""
    config_path = Path(__file__).parent.parent / "config" / "review_agent.yaml"
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
        response_format=ReviewOutput,
        middleware=[observability_agent_middleware],
    )
