import json
from typing import Annotated


def query_pipeline_status(
    pipeline_name: Annotated[str, "Name of the ADF pipeline to query"],
) -> str:
    """Query the execution status of an ADF pipeline."""
    return json.dumps(
        {
            "pipeline_name": pipeline_name,
            "last_runs": [
                {
                    "run_id": "abc-123-def",
                    "start_time": "2024-01-15T08:00:00Z",
                    "end_time": "2024-01-15T08:45:00Z",
                    "status": "Succeeded",
                    "duration_minutes": 45,
                },
                {
                    "run_id": "abc-124-def",
                    "start_time": "2024-01-14T08:00:00Z",
                    "end_time": "2024-01-14T08:30:00Z",
                    "status": "Failed",
                    "duration_minutes": 30,
                    "error": "Timeout connecting to source database",
                },
            ],
            "total_runs_returned": 2,
        },
        indent=2,
    )


def get_pipeline_run_details(
    run_id: Annotated[str, "The pipeline run ID to get details for"],
) -> str:
    """Get detailed information about a specific pipeline run."""
    return json.dumps(
        {
            "run_id": run_id,
            "pipeline_name": "daily-etl-pipeline",
            "start_time": "2024-01-15T08:00:00Z",
            "end_time": "2024-01-15T08:45:00Z",
            "status": "Succeeded",
            "duration_minutes": 45,
            "activities": [
                {"name": "CopyFromSource", "status": "Succeeded", "duration_seconds": 1200},
                {"name": "TransformData", "status": "Succeeded", "duration_seconds": 900},
                {"name": "LoadToTarget", "status": "Succeeded", "duration_seconds": 600},
            ],
            "trigger_type": "ScheduleTrigger",
            "parameters": {"date": "2024-01-15", "mode": "full"},
        },
        indent=2,
    )


def list_failed_pipelines(
    time_range: Annotated[
        str, "Time range: 'last_hour', 'last_24h', 'last_7d'"
    ] = "last_24h",
) -> str:
    """List all failed pipeline runs in the specified time range."""
    return json.dumps(
        {
            "time_range": time_range,
            "failed_runs": [
                {
                    "pipeline_name": "daily-etl-pipeline",
                    "run_id": "abc-124-def",
                    "failed_at": "2024-01-14T08:30:00Z",
                    "error": "Timeout connecting to source database",
                },
                {
                    "pipeline_name": "hourly-sync",
                    "run_id": "xyz-789-abc",
                    "failed_at": "2024-01-14T12:15:00Z",
                    "error": "Authentication failed for target storage",
                },
            ],
            "total_failed": 2,
        },
        indent=2,
    )
