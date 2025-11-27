from pydantic_settings import BaseSettings, SettingsConfigDict


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI configuration from environment variables."""

    model_config = SettingsConfigDict(env_prefix="AZURE_OPENAI_", env_file=".env", extra="ignore")

    api_key: str
    endpoint: str = "https://stanleyai.cognitiveservices.azure.com/"
    deployment_name: str
