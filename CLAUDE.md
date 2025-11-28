# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **DAPE OpsAgent Manager** - an operations agent system built on Microsoft Agent Framework with a Flask-based chat UI. It combines:

1. **Triage Workflow**: Routes queries to 3 specialized agents:
   - **servicenow-agent**: ServiceNow ITSM operations (change requests, incidents)
   - **log-analytics-agent**: Azure Data Factory pipeline monitoring
   - **service-health-agent**: Health monitoring for Databricks, Snowflake, Azure services

2. **Chat UI**: ChatGPT-like interface with persistent chat history, multiple model support, PostgreSQL/Redis backend, and Azure Easy Auth SSO integration.

## Commands

### Running the Application

Development server (Flask UI with workflow backend):
```bash
python flask_app.py
```

Production server (using Gunicorn):
```bash
gunicorn -w 4 -b 0.0.0.0:8000 flask_app:app
```

The app runs on `http://localhost:8000` by default.

### Workflow-only Development

Run the DevUI server (launches workflow at http://localhost:8090):
```bash
python main.py
```

### Install Dependencies

```bash
uv sync
```

### Container Operations

Build container image:
```bash
cd deployment
./build_container.sh build
```

Build and push to ACR:
```bash
./build_container.sh all
```

Test container locally:
```bash
docker run -p 8000:8000 opsagent2-app:latest
```

### Deployment to Azure

Deploy resource group:
```bash
cd deployment
./deploy_infra.sh rg
```

Deploy infrastructure (VNet, App Service, PostgreSQL, Redis, ACR, Key Vault):
```bash
./deploy_infra.sh app
```

Preview infrastructure changes (dry run):
```bash
./deploy_infra.sh app --what-if
```

Initialize PostgreSQL database:
```bash
./deploy_script.sh db
```

Deploy application container:
```bash
./deploy_script.sh app
```

Full deployment (database + app):
```bash
./deploy_script.sh all
```

## Architecture

```
opsagent2/
├── flask_app.py                  # Main Flask application with REST API
├── main.py                       # Workflow-only runner (DevUI)
├── deployment/                   # Azure deployment scripts
│   ├── build_container.sh        # Docker build & push to ACR
│   ├── deploy_infra.sh           # Bicep infrastructure deployment
│   ├── deploy_script.sh          # App & database deployment
│   ├── init.sql                  # PostgreSQL schema
│   ├── rg.bicep                  # Resource group template
│   └── simplified.bicep          # Full infrastructure template
├── doc/                          # Planning and design documents
└── opsagent/
    ├── config/                   # YAML configs with agent prompts and model settings
    │   └── {agent}_agent.yaml    # name, description, model, instructions
    ├── tools/                    # Tool functions for each agent
    ├── agents/                   # Agent factory functions using ChatAgent
    ├── workflows/                # Workflow definitions using WorkflowBuilder
    │   └── triage_workflow.py    # Main entry: fan-out to agents, fan-in responses
    ├── utils/
    │   ├── settings.py           # Pydantic Settings for env vars (AZURE_OPENAI_*)
    │   └── config_loader.py      # YAML config loader -> AgentConfig model
    └── ui/
        └── app/                  # UI application module
            ├── storage/          # Multi-backend persistence layer
            │   ├── manager.py    # ChatHistoryManager orchestrator
            │   ├── postgresql.py # PostgreSQL backend
            │   ├── redis.py      # Write-through Redis caching
            │   └── local.py      # JSON file storage
            └── static/           # Frontend files
                ├── index.html    # Main chat UI
                ├── script.js     # Frontend logic
                └── styles.css    # UI styling
```

## Key Patterns

### Workflow Pattern
The triage workflow (`triage_workflow.py`) implements:
1. Query intake → Triage agent parses and routes
2. Conditional fan-out: dispatch to selected agents OR reject
3. Fan-in: aggregate responses from all invoked agents

### Agent Creation Pattern
Each agent is created via `create_*_agent()` which:
1. Loads YAML config (prompts + model settings)
2. Creates `AzureOpenAISettings()` for API credentials from env
3. Initializes `AzureOpenAIChatClient` with deployment_name from env
4. Returns `ChatAgent` with tools attached (or `response_format` for structured output)

### Tool Definition Pattern
Tools are plain Python functions with `Annotated` type hints for parameter descriptions. Return JSON strings.

### Storage Modes
The `CHAT_HISTORY_MODE` environment variable controls the storage backend:

| Mode | Backend | User Auth | Use Case |
|------|---------|-----------|----------|
| `local` | JSON files | Local fallback | Local development without database |
| `local_psql` | PostgreSQL | Test credentials from env | Local development with Azure PostgreSQL |
| `postgres` | PostgreSQL | SSO headers | Production PostgreSQL-only |
| `local_redis` | PostgreSQL + Redis | Test credentials from env | Local development with write-through cache |
| `redis` | PostgreSQL + Redis | SSO headers | Production with write-through cache |

**Write-through caching**: In `redis` and `local_redis` modes, all write operations save to both PostgreSQL (primary) and Redis (cache) simultaneously.

## Environment Variables

Required in `.env`:
```bash
# Azure OpenAI (for workflow agents)
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://stanleyai.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=...

# Storage Mode
CHAT_HISTORY_MODE=local  # or local_psql, postgres, local_redis, redis

# PostgreSQL (for non-local modes)
POSTGRES_HOST=your-prefix-postgres.postgres.database.azure.com
POSTGRES_ADMIN_LOGIN=pgadmin
POSTGRES_ADMIN_PASSWORD=...
POSTGRES_DATABASE=chat_history

# Redis (for redis modes)
REDIS_HOST=your-prefix-redis.redis.cache.windows.net
REDIS_PASSWORD=...
```

See `.env.example` for complete configuration options.

## Important Implementation Notes

### Modifying the LLM Backend
The `call_llm()` function in `flask_app.py` executes the triage workflow. It receives:
- `model`: Selected model name
- `messages`: List of message dicts with "role" and "content" fields (OpenAI-compatible format)

### Adding New Models
Edit `models_list()` in `flask_app.py` to add/remove model options in the dropdown.

### Container Deployment
The application runs in a Docker container on Azure App Service. The Dockerfile:
- Uses Python 3.12 slim base image
- Installs dependencies from `pyproject.toml` using uv
- Copies the full `opsagent/` module for workflow and storage
- Runs Gunicorn on port 8000

### Database Initialization
The `deployment/init.sql` script creates the PostgreSQL schema:
- Creates `conversations` table (conversation metadata)
- Creates `messages` table (individual messages with sequence numbers)
- Sets up proper indexes and constraints

Run via `./deploy_script.sh db`

## Reference Samples

The `samples/` directory contains Microsoft Agent Framework examples:
- `samples/getting_started/devui/` - DevUI integration patterns
- `samples/getting_started/agents/azure_openai/` - Azure OpenAI client usage
- `samples/getting_started/tools/` - Tool definition patterns
- `samples/getting_started/workflows/` - Workflow patterns (fan-out, fan-in, conditionals)
