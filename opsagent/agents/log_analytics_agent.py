from pathlib import Path

from agent_framework import ChatAgent
from agent_framework.azure import AzureOpenAIChatClient

from ..utils.observability import (
    observability_agent_middleware,
    observability_function_middleware,
)
from ..tools.log_analytics_tools import (
    get_pipeline_run_details,
    list_failed_pipelines,
    query_pipeline_status,
)
from ..utils.config_loader import load_agent_config
from ..utils.settings import get_azure_openai_settings


def create_log_analytics_agent() -> ChatAgent:
    """Create and return the Log Analytics agent."""
    config_path = Path(__file__).parent.parent / "config" / "log_analytics_agent.yaml"
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
        tools=[query_pipeline_status, get_pipeline_run_details, list_failed_pipelines],
        middleware=[
            observability_agent_middleware,
            observability_function_middleware,
        ],
    )
