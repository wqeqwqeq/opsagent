import json
from datetime import datetime
from typing import Annotated


def check_databricks_health(
    workspace: Annotated[str, "Databricks workspace name"] = "default",
) -> str:
    """Check Databricks workspace health status."""
    return json.dumps(
        {
            "service": "databricks",
            "workspace": workspace,
            "status": "HEALTHY",
            "checked_at": datetime.utcnow().isoformat() + "Z",
        },
        indent=2,
    )


def check_snowflake_health(
    warehouse: Annotated[str, "Snowflake warehouse name"] = "default",
) -> str:
    """Check Snowflake warehouse health status."""
    return json.dumps(
        {
            "service": "snowflake",
            "warehouse": warehouse,
            "status": "HEALTHY",
            "checked_at": datetime.utcnow().isoformat() + "Z",
        },
        indent=2,
    )


def check_azure_service_health(
    service: Annotated[str, "Azure service name: 'ADF', 'Storage', 'SQL', 'KeyVault'"],
) -> str:
    """Check Azure service health status."""
    # Mock: ADF is unhealthy for demo purposes
    status = "UNHEALTHY" if service.upper() == "ADF" else "HEALTHY"
    reason = "Degraded performance in East US region" if status == "UNHEALTHY" else None

    result = {
        "service": f"azure-{service.lower()}",
        "status": status,
        "checked_at": datetime.utcnow().isoformat() + "Z",
    }
    if reason:
        result["reason"] = reason

    return json.dumps(result, indent=2)
