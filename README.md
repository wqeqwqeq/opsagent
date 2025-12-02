# DAPE OpsAgent Manager

An operations agent system built on Microsoft Agent Framework with a ChatGPT-like Flask UI interface. Combines intelligent query routing with persistent chat history, Azure Easy Auth SSO integration, and PostgreSQL/Redis backend.

## Features

### Intelligent Triage Workflow
- **servicenow-agent**: ServiceNow ITSM operations (change requests, incidents)
- **log-analytics-agent**: Azure Data Factory pipeline monitoring
- **service-health-agent**: Health monitoring for Databricks, Snowflake, Azure services

### Chat UI
- ChatGPT-like interface with persistent conversation history
- Multiple LLM model support (configurable)
- Azure Easy Auth (SSO) integration
- PostgreSQL database for conversation persistence
- **Write-through Redis caching** for improved performance
- **Flexible storage modes** configured via `CHAT_HISTORY_MODE`

### Infrastructure
- Container-based deployment to Azure App Service
- **VNet Integration with NAT Gateway** for network isolation
- **Network-isolated PostgreSQL** with IP whitelisting
- Secure infrastructure with Managed Identity and Key Vault

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Local Development](#local-development)
- [Deployment](#deployment)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### Required Tools

- **Python 3.12+**: Required runtime
- **uv** (recommended): `pip install uv` or [install uv](https://github.com/astral-sh/uv)
- **Azure CLI**: [Install Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)
- **Docker**: [Install Docker](https://docs.docker.com/get-docker/)
- **PostgreSQL Client (psql)**: For database initialization
  - macOS: `brew install postgresql`
  - Ubuntu: `sudo apt-get install postgresql-client`

### Azure Requirements

- Azure subscription with appropriate permissions
- Azure OpenAI resource with deployed model
- Azure AD App Registration for Easy Auth (SSO) - not required for sandbox environments

## Quick Start

```bash
# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your Azure OpenAI credentials

# Run the application
python flask_app.py

# Open http://localhost:8000
```

## Configuration

### Environment File

Copy the example environment file and configure it:

```bash
cp .env.example .env
```

### Required Variables

```bash
# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name

# Storage Mode
CHAT_HISTORY_MODE=local  # Options: local, local_psql, postgres, local_redis, redis
```

### Storage Modes

| Mode | Backend | Use Case |
|------|---------|----------|
| `local` | JSON files | Local development without database |
| `local_psql` | PostgreSQL | Local dev with Azure PostgreSQL |
| `postgres` | PostgreSQL | Production PostgreSQL-only |
| `local_redis` | PostgreSQL + Redis | Local dev with write-through cache |
| `redis` | PostgreSQL + Redis | Production with caching |

See `.env.example` for complete configuration options.

## Local Development

### Install Dependencies

```bash
uv sync
```

### Run the Application

**Flask UI with workflow backend:**
```bash
python flask_app.py
```
Open http://localhost:8000

**Workflow-only (DevUI):**
```bash
python workflow_run/workflow_run_devui.py
```
Open http://localhost:8090

### Testing with Azure PostgreSQL

1. Deploy infrastructure first (see [Deployment](#deployment))
2. Update `.env`:
   ```bash
   CHAT_HISTORY_MODE=local_psql
   POSTGRES_HOST=your-prefix-postgres.postgres.database.azure.com
   ```
3. Run the app locally

## Deployment

### Deployment Sequence

Follow these steps in order:

#### Step 1: Deploy Resource Group
```bash
cd deployment
./deploy_infra.sh rg
```

#### Step 2: Deploy Infrastructure
```bash
./deploy_infra.sh app
```

This provisions:
- App Service Plan + App Service (Python 3.12, VNet-integrated)
- Virtual Network + NAT Gateway (static outbound IP)
- PostgreSQL Flexible Server (network-isolated)
- Redis Cache
- Azure Container Registry (ACR)
- Key Vault, Application Insights, Managed Identity

#### Step 3: Build Container Image
```bash
./build_container.sh build
```

Test locally:
```bash
docker run -p 8000:8000 your-prefix-app:latest
```

#### Step 4: Push to ACR
```bash
./build_container.sh push
# Or build and push in one step:
./build_container.sh all
```

#### Step 5: Initialize Database
```bash
./deploy_script.sh db
```

#### Step 6: Deploy Application
```bash
./deploy_script.sh app
# Or deploy database + app together:
./deploy_script.sh all
```

### Access Your Application

After deployment (wait ~2 minutes for startup):
```
https://{RESOURCE_PREFIX}-app.azurewebsites.net
```

## Architecture

```
+----------------------------------------------------------+
|              Virtual Network (10.0.0.0/16)               |
|  +----------------------------------------------------+  |
|  |          App Service Subnet (10.0.1.0/26)          |  |
|  |  +----------------------------------------------+  |  |
|  |  |         Azure App Service (Linux)            |  |  |
|  |  |                                              |  |  |
|  |  |  Flask Container (Python 3.12)               |  |  |
|  |  |  - flask_app.py (REST API)                   |  |  |
|  |  |  - Triage Workflow (agent routing)           |  |  |
|  |  |  - ChatHistoryManager (storage)              |  |  |
|  |  |  - Azure Easy Auth (SSO)                     |  |  |
|  |  +----------------------------------------------+  |  |
|  +----------------------------------------------------+  |
+----------------------------------------------------------+
                            |
                    (NAT Gateway)
                            |
                   Static Public IP
                            |
            +---------------+---------------+
            |                               |
            v                               v
  +-------------------+         +-------------------+
  | PostgreSQL        |         | Redis Cache       |
  | Flexible Server   |         |                   |
  |                   |         | - WRITE-THROUGH   |
  | - Conversations   |         | - 30min TTL       |
  | - Messages        |         | - Cache Layer     |
  | - PRIMARY STORE   |         |                   |
  | - Firewall:       |         |                   |
  |   NAT Gateway IP  |         |                   |
  +-------------------+         +-------------------+
```

### Project Structure

```
opsagent2/
├── flask_app.py              # Main Flask application
├── Dockerfile                # Container image definition
├── workflow_run/             # Workflow runner scripts
│   ├── workflow_run_devui.py     # DevUI server
│   ├── workflow_run.py           # Direct workflow execution
│   └── workflow_run_with_trace.py # Workflow with OpenTelemetry tracing
├── pyproject.toml            # Python dependencies
├── deployment/               # Azure deployment scripts
│   ├── build_container.sh    # Docker build/push
│   ├── deploy_infra.sh       # Bicep infrastructure
│   ├── deploy_script.sh      # App deployment
│   ├── init.sql              # Database schema
│   ├── rg.bicep              # Resource group template
│   └── simplified.bicep      # Infrastructure template
├── doc/                      # Planning documents
└── opsagent/
    ├── config/               # Agent YAML configs
    ├── tools/                # Agent tool functions
    ├── agents/               # Agent factories
    ├── workflows/            # Workflow definitions
    ├── utils/                # Settings, config loader
    └── ui/
        └── app/
            ├── storage/      # Chat history backends
            └── static/       # Frontend files
```

## Troubleshooting

### View Application Logs
```bash
az webapp log tail -g $AZURE_RESOURCE_GROUP -n ${RESOURCE_PREFIX}-app
```

### View Configuration
```bash
az webapp config appsettings list -g $AZURE_RESOURCE_GROUP -n $APP_NAME
```

### Restart Application
```bash
az webapp restart -g $AZURE_RESOURCE_GROUP -n ${RESOURCE_PREFIX}-app
```

### SSH into Container
```bash
az webapp ssh -g $AZURE_RESOURCE_GROUP -n ${RESOURCE_PREFIX}-app
```

### Check PostgreSQL Connection
```bash
psql -h ${RESOURCE_PREFIX}-postgres.postgres.database.azure.com \
     -U $POSTGRES_ADMIN_LOGIN \
     -d $POSTGRES_DATABASE
```

### Common Issues

**Database connection timeout:**
- PostgreSQL firewall only allows NAT Gateway IP
- Solution: Add your local IP temporarily for database initialization
  ```bash
  az postgres flexible-server firewall-rule create \
    -g $AZURE_RESOURCE_GROUP \
    -n ${RESOURCE_PREFIX}-postgres \
    --rule-name temp-local-access \
    --start-ip-address $(curl -s https://api.ipify.org) \
    --end-ip-address $(curl -s https://api.ipify.org)
  ```

**Container deployment fails:**
- Check ACR authentication:
  ```bash
  az acr login --name $(echo ${RESOURCE_PREFIX} | tr -d '-')acr
  az acr repository list --name $(echo ${RESOURCE_PREFIX} | tr -d '-')acr
  ```

**"Local Mode" instead of username:**
- Verify Easy Auth is enabled (not for sandbox environments):
  ```bash
  az webapp auth show -g $AZURE_RESOURCE_GROUP -n ${RESOURCE_PREFIX}-app
  ```

## License

[Add your license here]
