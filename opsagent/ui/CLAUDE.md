# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Flask-based chat UI (ChatGPT-like interface) called "DAPE OpsAgent Manager" that supports persistent chat history, multiple models, PostgreSQL/Redis storage, and Azure Easy Auth integration for SSO.

## Development Commands

### Running the Application

Development server (Flask debug mode):
```bash
python flask_app.py
```

Production server (using Gunicorn):
```bash
gunicorn -w 4 -b 0.0.0.0:8000 flask_app:app
```

The app runs on `http://localhost:8000` by default.

### Environment Setup

This project uses `pyproject.toml` for dependency management. The `requirements.txt` file is auto-generated during deployment.

Using uv (recommended):
```bash
uv sync
```

Using pip:
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv pip compile pyproject.toml -o requirements.txt
pip install -r requirements.txt
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
docker run -p 8000:8000 stanley-dev-ui-app:latest
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

### Application Structure

The application follows a REST API architecture with a clear separation between frontend and backend:

- **flask_app.py**: Flask REST API server
  - API endpoints for conversations, messages, and user info
  - Model selection and chat management
  - SSO integration via Azure Easy Auth headers (`X-MS-CLIENT-PRINCIPAL-NAME`, `X-MS-CLIENT-PRINCIPAL-ID`)
  - LLM integration stub (`call_llm_stub` at flask_app.py:133)

- **app/storage/**: Multi-backend persistence layer
  - `manager.py`: Central ChatHistoryManager orchestrating storage backends
  - `postgresql.py`: Two-table schema (conversations + messages)
  - `redis.py`: Write-through caching with configurable TTL
  - `local.py`: JSON file storage in `.chat_history/` directory
  - User-scoped conversation storage (user_id parameter)

- **app/static/**: Frontend files
  - `index.html`: Main chat UI page
  - `script.js`: Frontend logic (REST API client, state management)
  - `styles.css`: UI styling

### Key Concepts

#### Storage Modes

The `CHAT_HISTORY_MODE` environment variable controls the storage backend:

| Mode | Backend | User Auth | Use Case |
|------|---------|-----------|----------|
| `local` | JSON files | Local fallback | Local development without database |
| `local_psql` | PostgreSQL | Test credentials from env | Local development with Azure PostgreSQL |
| `postgres` | PostgreSQL | SSO headers | Production PostgreSQL-only |
| `local_redis` | PostgreSQL + Redis | Test credentials from env | Local development with write-through cache |
| `redis` | PostgreSQL + Redis | SSO headers | Production with write-through cache |

**Write-through caching**: In `redis` and `local_redis` modes, all write operations save to both PostgreSQL (primary) and Redis (cache) simultaneously. Reads prefer Redis cache with automatic fallback to PostgreSQL.

#### Session State and User Authentication

- In `local_psql` and `local_redis` modes, user credentials come from environment variables (`LOCAL_TEST_CLIENT_ID`, `LOCAL_TEST_USERNAME`)
- In `postgres` and `redis` modes, user info is extracted from Azure Easy Auth headers
- In `local` mode, uses a fallback local user ID

User info is retrieved via `get_user_info()` (flask_app.py:96) on every API request.

#### Chat History Persistence

Conversations have the following schema:
- `conversation_id`: 8-character UUID
- `user_id`: Owner of the conversation
- `title`: Auto-generated from first message or manually set
- `model`: Selected LLM model
- `messages`: List of role/content/time objects
- `created_at`, `last_modified`: ISO 8601 timestamps

PostgreSQL schema uses two tables:
- `conversations`: Stores metadata (id, user_id, title, model, timestamps)
- `messages`: Stores individual messages (conversation_id, sequence_number, role, content, timestamp)

Conversations auto-save on every message exchange and title updates.

#### Model Integration

Currently uses a stub LLM (`call_llm_stub` in flask_app.py:146) that echoes user input. Replace this with actual model API calls (e.g., Azure OpenAI, OpenAI API, local LLM endpoint).

Available models configured in `models_list()` (flask_app.py:157):
- gpt-4o-mini (default)
- gpt-4o
- gpt-4.1
- gpt-3.5-turbo
- local-llm

### Azure Infrastructure

The Bicep template (`deployment/simplified.bicep`) provisions:
- **Virtual Network**: Isolated network with delegated subnet for App Service
- **NAT Gateway**: Static outbound public IP for consistent IP whitelisting
- **App Service Plan**: Linux, configurable SKU (default B1)
- **App Service**: Python 3.12 runtime, VNet-integrated, pulls from ACR
- **PostgreSQL Flexible Server**: Network-isolated, only accepts connections from NAT Gateway IP
- **Redis Cache**: Write-through cache layer (configurable SKU)
- **Azure Container Registry (ACR)**: Private Docker registry for app images
- **User-assigned Managed Identity**: ACR authentication, service-to-service auth
- **Application Insights + Log Analytics Workspace**: Monitoring and logging
- **Key Vault**: Secure secret storage
- **Azure AD authentication (Easy Auth)**: Disabled in sandbox environments (resource prefix contains 'sbx')

#### Network Architecture

The app uses **VNet Integration with NAT Gateway** for network isolation:

1. App Service integrates into a delegated subnet (`appServiceSubnet`)
2. NAT Gateway provides a static public IP for all outbound traffic
3. PostgreSQL firewall only allows connections from NAT Gateway IP (no public access)
4. All App Service outbound traffic routes through VNet/NAT Gateway (`vnetRouteAllEnabled`)

Configuration (set in `.env`):
- `VNET_ADDRESS_SPACE`: VNet CIDR (default: `10.0.0.0/16`)
- `SUBNET_ADDRESS_PREFIX`: Subnet CIDR (default: `10.0.1.0/26`)

Authentication is controlled by the `isSbx` variable which checks if the resource prefix contains 'sbx'.

## Important Implementation Notes

### Modifying the LLM Backend

Replace `call_llm_stub()` in flask_app.py:146 with actual API calls. The function receives:
- `model`: Selected model name
- `messages`: List of message dicts with "role" and "content" fields (OpenAI-compatible format)

Return the assistant's response as a string.

### Adding New Models

Edit `models_list()` in flask_app.py:157 to add/remove model options in the dropdown.

### Chat History Storage Mode

Set `CHAT_HISTORY_MODE` in `.env` to configure storage backend. The `ChatHistoryManager` class automatically initializes the appropriate backend based on this variable.

For local testing with Azure PostgreSQL:
```bash
CHAT_HISTORY_MODE=local_psql
POSTGRES_HOST=your-prefix-postgres.postgres.database.azure.com
```

For production with write-through Redis cache:
```bash
CHAT_HISTORY_MODE=redis
POSTGRES_HOST=your-prefix-postgres.postgres.database.azure.com
REDIS_HOST=your-prefix-redis.redis.cache.windows.net
```

### Container Deployment

The application runs in a Docker container on Azure App Service. The Dockerfile:
- Uses Python 3.12 slim base image
- Installs dependencies from `pyproject.toml` using uv
- Runs Gunicorn on port 8000 (not Flask's default 5000)
- Binds to `0.0.0.0:8000` to match Azure Web App expectations

Startup command configured in App Service:
```bash
uv run gunicorn -w 4 -b 0.0.0.0:8000 flask_app:app
```

### Database Initialization

The `deployment/init.sql` script creates the PostgreSQL schema:
- Creates `conversations` table (conversation metadata)
- Creates `messages` table (individual messages with sequence numbers)
- Sets up proper indexes and constraints

Run via `./deploy_script.sh db`, which:
1. Adds your client IP to PostgreSQL firewall (persistent rule)
2. Connects via `psql` and runs `init.sql`
3. Leaves your IP whitelisted for future access

### Bicep Parameters

Key parameters in `simplified.bicep`:
- `resourcePrefix`: Prefix for all resource names (default: 'stanley-dev-ui')
- `skuName`: App Service Plan SKU (default: 'b1')
- `postgresSku`: PostgreSQL SKU (default: 'Standard_B1ms')
- `redisSkuName`: Redis SKU (default: 'Basic')
- `vnetAddressSpace`: VNet CIDR (required, set in `.env`)
- `subnetAddressPrefix`: Subnet CIDR (required, set in `.env`)
- `tokenProviderAppId`: Azure AD App Registration client ID for Easy Auth
- `postgresAdminPassword`: Secure parameter for PostgreSQL admin password
- `location`: Defaults to resource group location

### Environment Variables

The application reads configuration from `.env` file. Key variables:

**Storage Configuration:**
- `CHAT_HISTORY_MODE`: Storage backend (local, local_psql, postgres, local_redis, redis)
- `CONVERSATION_HISTORY_DAYS`: Days to retain conversations (default: 7)

**PostgreSQL Configuration:**
- `POSTGRES_HOST`: PostgreSQL hostname
- `POSTGRES_PORT`: PostgreSQL port (default: 5432)
- `POSTGRES_ADMIN_LOGIN`: Admin username
- `POSTGRES_ADMIN_PASSWORD`: Admin password
- `POSTGRES_DATABASE`: Database name (default: chat_history)
- `POSTGRES_SSLMODE`: SSL mode (default: require)

**Redis Configuration:**
- `REDIS_HOST`: Redis hostname
- `REDIS_PORT`: Redis port (default: 6380)
- `REDIS_PASSWORD`: Redis access key
- `REDIS_SSL`: Use SSL (default: true)
- `REDIS_TTL_SECONDS`: Cache TTL (default: 1800)

**Local Testing Configuration:**
- `LOCAL_TEST_CLIENT_ID`: Test user ID for local_psql/local_redis modes
- `LOCAL_TEST_USERNAME`: Test username for local_psql/local_redis modes

See `.env.example` for complete configuration template.
