# Azure Key Vault Integration Design

## Overview

Create a simple `AKV` class in `opsagent/utils/keyvault.py` to read secrets from Azure Key Vault.

## Design Decisions

### Why Simple Direct Reads (No Caching)?

We evaluated several caching approaches:

| Approach | Pros | Cons |
|----------|------|------|
| Flask `g` object | Per-request reuse | Creates new client every request |
| In-memory singleton | Fast reads | Stale forever if secret rotates (requires restart) |
| Redis cache with TTL | Auto-refresh after TTL | Added complexity, security concerns |
| **Direct reads at startup** | Simple, same as `os.getenv()` | Requires restart on secret change |

**Decision: Direct reads at startup** because:

1. **Few secrets, read once** - Only ~5-10 secrets (Postgres password, Redis password, App Insights connection string, Tableau/PowerBI credentials)
2. **Same behavior as current approach** - `os.getenv()` also reads once at startup
3. **Restart is acceptable** - Secret rotation is rare; App Service restart takes 10-30 seconds
4. **No complexity** - No caching layer, no TTL management, no Redis dependency for secrets

### Secret Rotation Consideration

Whether secrets come from:
- `.env` file
- App Service Environment Variables
- Key Vault reference (`@Microsoft.KeyVault(SecretUri=...)`)
- Direct Key Vault read via AKV class

**All require app restart when secrets change.** This is acceptable for our use case.

## Implementation

### AKV Class

```python
class AKV:
    def __init__(self, vault_name: Optional[str] = None):
        # Reads AZURE_KEYVAULT_NAME from env if not provided
        # Uses DefaultAzureCredential (CLI locally, Managed Identity in prod)

    def list_secrets(self) -> List[str]:
        # List all secret names in vault

    def get_secret(self, name: str) -> Optional[str]:
        # Get secret value by name, returns None if not found
```

### Usage

```python
from opsagent.utils.keyvault import AKV

# At app startup
akv = AKV()

# Read secrets
POSTGRES_PASSWORD = akv.get_secret("POSTGRES-ADMIN-PASSWORD")
REDIS_PASSWORD = akv.get_secret("REDIS-PASSWORD")
```

## Files Modified

1. `opsagent/utils/keyvault.py` - New AKV class
2. `opsagent/utils/__init__.py` - Export AKV
3. `pyproject.toml` - Add `azure-keyvault-secrets>=4.8.0`
4. `.env` - Add `AZURE_KEYVAULT_NAME`

## Environment Variables

```bash
AZURE_KEYVAULT_NAME=your-vault-name
```
