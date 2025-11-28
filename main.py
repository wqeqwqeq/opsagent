import logging

from agent_framework.devui import serve

from opsagent.workflows.triage_workflow import create_triage_workflow


def main():
    """Main entry point for the Ops Agents DevUI."""
    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)

    logger.info("Creating Triage Workflow...")

    # Create the triage workflow with all specialized agents
    workflow = create_triage_workflow()

    logger.info("Starting DevUI server...")
    logger.info("Available at: http://localhost:8090")
    logger.info("Workflow: triage-workflow")
    logger.info("  Routes queries to:")
    logger.info("    - servicenow-agent")
    logger.info("    - log-analytics-agent")
    logger.info("    - service-health-agent")
    import os
    os.environ['ENABLE_OTEL']='true'
    # Launch DevUI with the workflow
    serve(
        entities=[workflow],
        port=8090,
        auto_open=True,
    )


if __name__ == "__main__":
    main()
