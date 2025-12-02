"""Run the triage workflow with OpenTelemetry tracing via Aspire Dashboard.

Aspire Dashboard should be running:
    docker run --rm -it -d \
        -p 18888:18888 \
        -p 4317:18889 \
        --name aspire-dashboard \
        mcr.microsoft.com/dotnet/aspire-dashboard:latest

View traces at: http://localhost:18888
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent_framework import WorkflowOutputEvent
from agent_framework.observability import get_tracer, setup_observability
from opentelemetry.trace import SpanKind
from opentelemetry.trace.span import format_trace_id

from opsagent.utils.observability import get_appinsights_connection_string
from opsagent.workflows.triage_workflow import create_triage_workflow


async def run_workflow(query: str) -> None:
    """Run the triage workflow with a query, wrapped in a trace span."""
    tracer = get_tracer()

    with tracer.start_as_current_span(f"triage_query", kind=SpanKind.INTERNAL) as span:
        # Add query as span attribute for searchability
        span.set_attribute("query.text", query)

        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}\n")

        workflow = create_triage_workflow()

        async for event in workflow.run_stream(query):
            if isinstance(event, WorkflowOutputEvent):
                print(f"\n{'='*60}")
                print("WORKFLOW OUTPUT:")
                print(f"{'='*60}")
                print(event.data)
                span.set_attribute("workflow.output", str(event.data)[:1000])  # Truncate for safety
            else:
                # Print other events for debugging
                event_name = type(event).__name__
                print(f"[Event] {event_name}: {event}")
                span.add_event(event_name, {"event_data": str(event)[:500]})


async def main():
    """Run test queries through the workflow with tracing enabled."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Aspire Dashboard OTLP endpoint
    ASPIRE_OTLP_ENDPOINT = "http://localhost:4317"

    # Enable sensitive data to see prompts/responses in traces
    enable_sensitive = os.environ.get("ENABLE_SENSITIVE_DATA", "true").lower() == "true"

    # Get App Insights connection string from Key Vault or env
    appinsights_conn_str = get_appinsights_connection_string()

    print(f"Tracing enabled with Aspire Dashboard at: {ASPIRE_OTLP_ENDPOINT}")
    print(f"View traces at: http://localhost:18888")

    setup_observability(
        otlp_endpoint=ASPIRE_OTLP_ENDPOINT,
        enable_sensitive_data=enable_sensitive,
        applicationinsights_connection_string=appinsights_conn_str,
    )

    # Create a root span for the entire scenario
    tracer = get_tracer()

    with tracer.start_as_current_span("Triage Workflow Scenario", kind=SpanKind.CLIENT) as root_span:
        trace_id = format_trace_id(root_span.get_span_context().trace_id)
        print(f"\n{'#'*60}")
        print(f"# Trace ID: {trace_id}")
        print(f"# Use this ID to search for traces in your APM tool")
        print(f"{'#'*60}\n")

        # Test queries
        test_queries = [
            # Should reject - unrelated query
            # "What's the weather today?",
            # Uncomment to test other scenarios:
            "List all open change requests and tell my if snowflake and databricks is up and running?",  # servicenow only
            # "Check Databricks health status",  # service_health only
            # "Check all service health and list any recent incidents",  # multiple agents
        ]

        for query in test_queries:
            await run_workflow(query)
            print("\n" + "=" * 80 + "\n")

        print(f"\n{'#'*60}")
        print(f"# Workflow completed!")
        print(f"# Trace ID: {trace_id}")
        print(f"# View traces at: http://localhost:18888")
        print(f"{'#'*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
