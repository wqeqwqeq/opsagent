"""Run the triage workflow directly without DevUI."""

import asyncio
import logging

from agent_framework import WorkflowOutputEvent

from opsagent.workflows.triage_workflow import create_triage_workflow


async def run_workflow(query: str) -> None:
    """Run the triage workflow with a query."""
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
        else:
            # Print other events for debugging
            print(f"[Event] {type(event).__name__}: {event}")


async def main():
    """Run test queries through the workflow."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Test queries
    test_queries = [
        # Should reject - unrelated query
        "What's the weather today?",
        # Should route to servicenow only
        # "List all open change requests",
        # Should route to service_health only
        # "Check Databricks health status",
        # Should route to multiple agents
        # "Check all service health and list any recent incidents",
    ]

    for query in test_queries:
        await run_workflow(query)
        print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
