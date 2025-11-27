import yaml
from pydantic import BaseModel


class AgentConfig(BaseModel):
    """Agent configuration loaded from YAML."""

    name: str
    description: str
    instructions: str
    api_version: str
    model_id: str


def load_agent_config(config_path: str) -> AgentConfig:
    """Load agent configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    return AgentConfig(
        name=config["name"],
        description=config["description"],
        instructions=config["instructions"],
        api_version=config["model"]["api_version"],
        model_id=config["model"]["model_id"],
    )
