# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an operations agent system built on Microsoft Agent Framework. It provides 3 specialized agents for IT operations tasks:
- **servicenow-agent**: ServiceNow ITSM operations (change requests, incidents)
- **log-analytics-agent**: Azure Data Factory pipeline monitoring
- **service-health-agent**: Health monitoring for Databricks, Snowflake, Azure services

## Commands

```bash
# Run the DevUI server (launches all agents at http://localhost:8090)
python main.py

# Install dependencies
uv sync
```

## Architecture

```
opsagent/
├── config/                    # YAML configs with agent prompts and model settings
│   └── {agent}_agent.yaml     # name, description, model (api_version, model_id), instructions
├── tools/                     # Tool functions for each agent (mock implementations)
├── agents/                    # Agent factory functions using ChatAgent
└── utils/
    ├── settings.py            # Pydantic Settings for env vars (AZURE_OPENAI_*)
    └── config_loader.py       # YAML config loader -> AgentConfig model
```

**Agent Creation Pattern**: Each agent is created via `create_*_agent()` which:
1. Loads YAML config (prompts + model settings)
2. Creates `AzureOpenAISettings()` for API credentials from env
3. Initializes `AzureOpenAIChatClient` with config.model_id, config.api_version
4. Returns `ChatAgent` with tools attached

## Environment Variables

Required in `.env`:
```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://stanleyai.cognitiveservices.azure.com/
```

Model settings (`api_version`, `model_id`) are per-agent in YAML configs.

## Key Dependencies

- `agent-framework`: Microsoft Agent Framework for building agents
- `pydantic-settings`: Environment variable management
- `pyyaml`: YAML config loading

## Reference Samples

The `samples/` directory contains Microsoft Agent Framework examples. Key patterns:
- `samples/getting_started/devui/` - DevUI integration patterns
- `samples/getting_started/agents/azure_openai/` - Azure OpenAI client usage
- `samples/getting_started/tools/` - Tool definition patterns
