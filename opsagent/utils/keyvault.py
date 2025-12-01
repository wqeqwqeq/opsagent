"""Azure Key Vault utility for secret management."""
import os
import logging
from typing import List, Optional

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

logger = logging.getLogger(__name__)


class AKV:
    """Azure Key Vault client wrapper.

    Uses DefaultAzureCredential for authentication:
    - Local: Azure CLI credentials
    - Production: Managed Identity
    """

    def __init__(self, vault_name: Optional[str] = None):
        """Initialize Key Vault client.

        Args:
            vault_name: Key Vault name. Defaults to AZURE_KEYVAULT_NAME env var.
        """
        self.vault_name = vault_name or os.getenv("AZURE_KEYVAULT_NAME")
        if not self.vault_name:
            raise ValueError("vault_name required or set AZURE_KEYVAULT_NAME")

        self.vault_url = f"https://{self.vault_name}.vault.azure.net/"
        self._credential = DefaultAzureCredential()
        self._client = SecretClient(vault_url=self.vault_url, credential=self._credential)

    def list_secrets(self) -> List[str]:
        """List all secret names in the vault.

        Returns:
            List of secret names
        """
        return [s.name for s in self._client.list_properties_of_secrets()]

    def get_secret(self, name: str) -> Optional[str]:
        """Get a secret value by name.

        Args:
            name: Secret name

        Returns:
            Secret value, or None if not found
        """
        try:
            secret = self._client.get_secret(name)
            return secret.value
        except Exception as e:
            logger.warning(f"Failed to get secret '{name}': {e}")
            return None
