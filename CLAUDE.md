# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an operations agent system built on Microsoft Agent Framework. It provides a triage workflow that routes queries to 3 specialized agents:
- **servicenow-agent**: ServiceNow ITSM operations (change requests, incidents)
- **log-analytics-agent**: Azure Data Factory pipeline monitoring
- **service-health-agent**: Health monitoring for Databricks, Snowflake, Azure services

## Commands

```bash
# Run the DevUI server (launches workflow at http://localhost:8090)
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
├── workflows/                 # Workflow definitions using WorkflowBuilder
│   └── triage_workflow.py     # Main entry: fan-out to agents, fan-in responses
└── utils/
    ├── settings.py            # Pydantic Settings for env vars (AZURE_OPENAI_*)
    └── config_loader.py       # YAML config loader -> AgentConfig model
```

**Workflow Pattern**: The triage workflow (`triage_workflow.py`) implements:
1. Query intake → Triage agent parses and routes
2. Conditional fan-out: dispatch to selected agents OR reject
3. Fan-in: aggregate responses from all invoked agents

**Agent Creation Pattern**: Each agent is created via `create_*_agent()` which:
1. Loads YAML config (prompts + model settings)
2. Creates `AzureOpenAISettings()` for API credentials from env
3. Initializes `AzureOpenAIChatClient` with deployment_name from env
4. Returns `ChatAgent` with tools attached (or `response_format` for structured output)

**Tool Definition Pattern**: Tools are plain Python functions with `Annotated` type hints for parameter descriptions. Return JSON strings.

## Environment Variables

Required in `.env`:
```
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://stanleyai.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=...
```

## Reference Samples

The `samples/` directory contains Microsoft Agent Framework examples:
- `samples/getting_started/devui/` - DevUI integration patterns
- `samples/getting_started/agents/azure_openai/` - Azure OpenAI client usage
- `samples/getting_started/tools/` - Tool definition patterns
- `samples/getting_started/workflows/` - Workflow patterns (fan-out, fan-in, conditionals)
