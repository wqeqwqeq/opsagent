# Project Consolidation Plan: Move UI Deployment to Root Level

## Overview
Consolidate the `opsagent/ui/` deployment infrastructure to the root level and clean up redundant files to create a unified project structure.

## Key Decisions (from user input)
- **doc/ folder**: Keep planning documents
- **Storage module**: Keep at `opsagent/ui/app/storage/`
- **.env files**: Single root `.env` only

---

## Phase 1: Move Deployment Files to Root

### 1.1 Create `deployment/` directory at root and move files
Move these files from `opsagent/ui/deployment/` to root `deployment/`:
- `build_container.sh`
- `deploy_infra.sh`
- `deploy_script.sh`
- `init.sql`
- `rg.bicep`
- `simplified.bicep`

### 1.2 Move Docker files to root
- Move `opsagent/ui/Dockerfile` → `Dockerfile`
- Move `opsagent/ui/.dockerignore` → `.dockerignore`

---

## Phase 2: Update Path References

### 2.1 Update `deployment/build_container.sh`
**Current**: `ENV_FILE="$SCRIPT_DIR/../.env"` (expects .env one level up)
**Change to**: `ENV_FILE="$SCRIPT_DIR/../.env"` (no change needed - still points to root)

**Current**: `cd "$SCRIPT_DIR/.."` then `docker buildx build ... -f Dockerfile .`
**Change to**: `cd "$SCRIPT_DIR/.."` (still correct - builds from root)

### 2.2 Update `deployment/deploy_script.sh`
**Current**: `ENV_FILE="$SCRIPT_DIR/../.env"`
**No change needed** - will correctly point to root `.env`

**Current**: `psql -f "$SCRIPT_DIR/init.sql"`
**No change needed** - init.sql moves with the script

### 2.3 Update `deployment/deploy_infra.sh`
**Current**: `ENV_FILE="$SCRIPT_DIR/../.env"`
**No change needed** - will correctly point to root `.env`

**Current**: `--template-file "$SCRIPT_DIR/rg.bicep"` and `"$SCRIPT_DIR/simplified.bicep"`
**No change needed** - bicep files move with the script

### 2.4 Update root `Dockerfile`
**Current** (in opsagent/ui/):
```dockerfile
COPY pyproject.toml .
COPY flask_app.py ./
COPY app/ ./app/
COPY .env .
```

**Change to**:
```dockerfile
COPY pyproject.toml .
COPY flask_app.py ./
COPY opsagent/ ./opsagent/
COPY .env .
```

The container needs the full `opsagent/` directory because `flask_app.py` imports from:
- `opsagent.workflows.triage_workflow`
- `opsagent.ui.app.storage`

### 2.5 Update root `.dockerignore`
Merge with existing and ensure:
```
.venv/
__pycache__/
*.pyc
.chat_history/
.git/
deployment/
*.md
.DS_Store
doc/
samples/
```

### 2.6 Update `flask_app.py` static folder reference
**Current**: `app = Flask(__name__, static_folder='opsagent/ui/app/static')`
**No change needed** - path is relative to flask_app.py at root

### 2.7 Update index route
**Current**: `return send_from_directory('opsagent/ui/app/static', 'index.html')`
**No change needed** - path is correct for root location

---

## Phase 3: Remove Redundant Files from `opsagent/ui/`

### 3.1 Delete these files from `opsagent/ui/`:
- `opsagent/ui/deployment/` (entire directory - moved to root)
- `opsagent/ui/Dockerfile` (moved to root)
- `opsagent/ui/.dockerignore` (moved to root)
- `opsagent/ui/pyproject.toml` (redundant - root has merged version)
- `opsagent/ui/requirements.txt` (auto-generated, not needed)
- `opsagent/ui/uv.lock` (use root uv.lock)
- `opsagent/ui/.env` (use single root .env)
- `opsagent/ui/.env.example` (move to root if not exists, else delete)
- `opsagent/ui/.gitignore` (merge into root .gitignore)
- `opsagent/ui/.python-version` (use root version)
- `opsagent/ui/CLAUDE.md` (merge into root CLAUDE.md)
- `opsagent/ui/README.md` (merge into root README.md)

### 3.2 Keep in `opsagent/ui/`:
- `opsagent/ui/app/` directory (storage module + static files)
- `opsagent/ui/__init__.py` (if exists, for package structure)

---

## Phase 4: Merge Documentation

### 4.1 Update root `CLAUDE.md`
Merge content from both files:
- Keep existing opsagent workflow documentation
- Add UI/Flask application section from `opsagent/ui/CLAUDE.md`
- Include deployment commands
- Include architecture overview combining both projects

### 4.2 Create root `README.md`
Currently empty - create comprehensive README including:
- Project overview (both opsagent + UI)
- Prerequisites
- Development commands (both workflow + UI)
- Deployment instructions (from ui/README.md)
- Architecture diagram combining both
- Environment variables documentation

---

## Phase 5: Update Root `.gitignore`

Merge entries from `opsagent/ui/.gitignore`:
```
# Python-generated files
__pycache__/
*.py[oc]
build/
dist/
wheels/
*.egg-info

# Virtual environments
.venv
samples

# Environment variables (contains secrets!)
.env

# Chat history (local storage)
.chat_history/

# Generated files
requirements.txt

# Deployment artifacts
app_bundle.zip
app_bundle/
video
```

---

## Phase 6: Verify Root `pyproject.toml`

Current root `pyproject.toml` already has merged dependencies. Verify it includes:
- `flask>=3.0.0`
- `flask-cors>=4.0.0`
- `gunicorn>=21.2.0`
- `psycopg2-binary==2.9.9`
- `python-dotenv>=1.0.0`
- `redis>=5.0.0`
- `azure-storage-blob>=12.19.0`
- `azure-identity>=1.15.0`
- `pyyaml>=6.0.1` (for opsagent)

---

## Final Project Structure

```
opsagent2/
├── .env                          # Single environment file
├── .env.example                  # Template (moved from ui/)
├── .gitignore                    # Merged gitignore
├── .dockerignore                 # Moved from ui/
├── .python-version
├── CLAUDE.md                     # Merged documentation
├── README.md                     # Comprehensive readme
├── Dockerfile                    # Moved from ui/, updated paths
├── pyproject.toml                # Merged dependencies
├── uv.lock
├── flask_app.py                  # Main Flask application
├── main.py                       # Workflow runner entry point
├── deployment/                   # Moved from opsagent/ui/deployment/
│   ├── build_container.sh
│   ├── deploy_infra.sh
│   ├── deploy_script.sh
│   ├── init.sql
│   ├── rg.bicep
│   └── simplified.bicep
├── doc/                          # Keep planning documents
│   ├── parallel_workflow_implementation.md
│   ├── triage_agent_plan.md
│   └── ui_workflow_integration_plan.md
└── opsagent/
    ├── __init__.py
    ├── config/                   # Agent YAML configs
    ├── tools/                    # Tool functions
    ├── agents/                   # Agent factories
    ├── workflows/                # Workflow definitions
    ├── utils/                    # Settings, config loader
    └── ui/
        └── app/                  # UI application module
            ├── __init__.py
            ├── storage/          # Chat history backends
            │   ├── __init__.py
            │   ├── manager.py
            │   ├── local.py
            │   ├── postgresql.py
            │   └── redis.py
            └── static/           # Frontend files
                ├── index.html
                ├── script.js
                └── styles.css
```

---

## Implementation Order

1. Move `deployment/` directory to root
2. Move `Dockerfile` and `.dockerignore` to root
3. Update `Dockerfile` paths for new structure
4. Move `.env.example` to root (keep as template)
5. Delete `opsagent/ui/.env` (use root only)
6. Merge `.gitignore` content
7. Merge `CLAUDE.md` documentation
8. Create comprehensive `README.md`
9. Delete redundant files from `opsagent/ui/`
10. Run `uv sync` to verify dependencies
11. Test with `python flask_app.py`
12. Test Docker build: `cd deployment && ./build_container.sh build`

---

## Files to Modify

| File | Action |
|------|--------|
| `deployment/*` | Move from `opsagent/ui/deployment/` |
| `Dockerfile` | Move + update COPY paths |
| `.dockerignore` | Move + merge content |
| `.gitignore` | Merge entries from ui/ |
| `CLAUDE.md` | Merge ui/ content |
| `README.md` | Create comprehensive version |
| `.env.example` | Move from ui/ |
| `opsagent/ui/*` | Delete redundant files |
