import logging

from agent_framework.devui import serve

from opsagent.agents.log_analytics_agent import create_log_analytics_agent
from opsagent.agents.service_health_agent import create_service_health_agent
from opsagent.agents.servicenow_agent import create_servicenow_agent
import os 


def main():
    """Main entry point for the Ops Agents DevUI."""
    # Setup logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger(__name__)

    logger.info("Creating Ops Agents...")

    # Create all 3 agents (credentials loaded from environment via pydantic-settings)
    servicenow_agent = create_servicenow_agent()
    log_analytics_agent = create_log_analytics_agent()
    service_health_agent = create_service_health_agent()

    logger.info("Starting DevUI server...")
    logger.info("Available at: http://localhost:8090")
    logger.info("Agents:")
    logger.info("  - servicenow-agent")
    logger.info("  - log-analytics-agent")
    logger.info("  - service-health-agent")
    # os.environ["ENABLE_OTEL"]="true"    
    # # Launch DevUI with all agents for individual testing
    serve(
        entities=[servicenow_agent, log_analytics_agent, service_health_agent],
        port=8090,
        auto_open=True,
    )


if __name__ == "__main__":
    main()
