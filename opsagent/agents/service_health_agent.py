from pathlib import Path

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from ..tools.service_health_tools import (
    check_azure_service_health,
    check_databricks_health,
    check_snowflake_health,
)
from ..utils.config_loader import load_agent_config
from ..utils.settings import AzureOpenAISettings


def create_service_health_agent() -> ChatAgent:
    """Create and return the Service Health agent."""
    config_path = Path(__file__).parent.parent / "config" / "service_health_agent.yaml"
    config = load_agent_config(str(config_path))
    settings = AzureOpenAISettings()

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
        tools=[check_databricks_health, check_snowflake_health, check_azure_service_health],
    )
