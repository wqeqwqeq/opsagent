import json
from typing import Annotated


def list_change_requests(
    status: Annotated[
        str, "Filter by status: 'open', 'approved', 'closed', or 'all'"
    ] = "all",
) -> str:
    """List change requests from ServiceNow."""
    return json.dumps(
        {
            "change_requests": [
                {
                    "number": "CHG0012345",
                    "short_description": "Database migration to Azure",
                    "status": "approved",
                    "priority": "high",
                    "assigned_to": "John Smith",
                },
                {
                    "number": "CHG0012346",
                    "short_description": "Network firewall rule update",
                    "status": "open",
                    "priority": "medium",
                    "assigned_to": "Jane Doe",
                },
                {
                    "number": "CHG0012347",
                    "short_description": "SSL certificate renewal",
                    "status": "closed",
                    "priority": "low",
                    "assigned_to": "Bob Wilson",
                },
            ],
            "total_count": 3,
            "filter_applied": status,
        },
        indent=2,
    )


def get_change_request(
    ticket_number: Annotated[
        str, "The change request ticket number (e.g., CHG0012345)"
    ],
) -> str:
    """Get details of a specific change request."""
    return json.dumps(
        {
            "number": ticket_number,
            "short_description": "Database migration to Azure",
            "description": "Migrate production database from on-prem SQL Server to Azure SQL Database",
            "status": "approved",
            "priority": "high",
            "assigned_to": "John Smith",
            "created_on": "2024-01-10T09:00:00Z",
            "planned_start": "2024-01-20T02:00:00Z",
            "planned_end": "2024-01-20T06:00:00Z",
            "approval_status": "approved",
            "risk": "medium",
        },
        indent=2,
    )


def list_incidents(
    status: Annotated[
        str, "Filter by status: 'new', 'in_progress', 'resolved', 'closed', or 'all'"
    ] = "all",
) -> str:
    """List incidents from ServiceNow."""
    return json.dumps(
        {
            "incidents": [
                {
                    "number": "INC0054321",
                    "short_description": "Production API returning 500 errors",
                    "status": "in_progress",
                    "severity": "critical",
                    "assigned_to": "On-Call Team",
                },
                {
                    "number": "INC0054322",
                    "short_description": "Slow query performance on reporting DB",
                    "status": "new",
                    "severity": "high",
                    "assigned_to": "DBA Team",
                },
                {
                    "number": "INC0054323",
                    "short_description": "User unable to login to portal",
                    "status": "resolved",
                    "severity": "medium",
                    "assigned_to": "Support Team",
                },
            ],
            "total_count": 3,
            "filter_applied": status,
        },
        indent=2,
    )


def get_incident(
    ticket_number: Annotated[str, "The incident ticket number (e.g., INC0054321)"],
) -> str:
    """Get details of a specific incident."""
    return json.dumps(
        {
            "number": ticket_number,
            "short_description": "Production API returning 500 errors",
            "description": "Multiple users reporting 500 Internal Server Error when accessing /api/v1/orders endpoint",
            "status": "in_progress",
            "severity": "critical",
            "impact": "high",
            "assigned_to": "On-Call Team",
            "created_on": "2024-01-15T14:30:00Z",
            "updated_on": "2024-01-15T15:00:00Z",
            "resolution_notes": None,
            "related_changes": ["CHG0012345"],
        },
        indent=2,
    )
