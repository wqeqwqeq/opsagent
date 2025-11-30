from pathlib import Path

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from ..observability import (
    observability_agent_middleware,
    observability_function_middleware,
)
from ..tools.servicenow_tools import (
    get_change_request,
    get_incident,
    list_change_requests,
    list_incidents,
)
from ..utils.config_loader import load_agent_config
from ..utils.settings import AzureOpenAISettings


def create_servicenow_agent() -> ChatAgent:
    """Create and return the ServiceNow agent."""
    config_path = Path(__file__).parent.parent / "config" / "servicenow_agent.yaml"
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
        tools=[list_change_requests, get_change_request, list_incidents, get_incident],
        middleware=[
            observability_agent_middleware,
            observability_function_middleware,
        ],
    )
