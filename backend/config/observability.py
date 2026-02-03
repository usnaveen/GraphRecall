"""LangSmith Observability Configuration."""

import os
import structlog

logger = structlog.get_logger()

def init_observability():
    """Initialize LangSmith tracing and observability.
    
    This function checks for necessary environment variables and sets defaults
    if they are not present, ensuring traces are properly captured and organized.
    """
    api_key = os.getenv("LANGCHAIN_API_KEY")
    tracing = os.getenv("LANGCHAIN_TRACING_V2")
    project = os.getenv("LANGCHAIN_PROJECT")

    if not api_key:
        logger.warning(
            "LangSmith API key not found. Observability will be disabled.",
            hint="Set LANGCHAIN_API_KEY in your .env file."
        )
        return

    # Auto-enable tracing if key is present but tracing var is missing
    if not tracing:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        logger.info("Enabled LangSmith tracing (LANGCHAIN_TRACING_V2=true)")

    # Set default project name if missing
    if not project:
        os.environ["LANGCHAIN_PROJECT"] = "GraphRecall-Dev"
        logger.info("Set default LangSmith project", project="GraphRecall-Dev")
    else:
        logger.info("LangSmith observability ready", project=project)
