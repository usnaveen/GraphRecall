"""
LangGraph Checkpointer Configuration

This module provides the checkpointer setup for production and development.
Following LangGraph 1.0.7 patterns with PostgresSaver for production durability.
"""

import os
from typing import Optional

import structlog

logger = structlog.get_logger()


def get_checkpointer(use_postgres: bool = False):
    """
    Get the appropriate checkpointer based on environment.
    
    Args:
        use_postgres: Force PostgresSaver even in development
    
    Returns:
        A LangGraph checkpointer instance
    """
    is_production = os.getenv("ENVIRONMENT", "development") == "production"
    database_url = os.getenv("DATABASE_URL")
    
    if (is_production or use_postgres) and database_url:
        logger.info("checkpointer: Using PostgresSaver for production")
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            
            # PostgresSaver requires the connection string
            return AsyncPostgresSaver.from_conn_string(database_url)
        except ImportError:
            logger.warning(
                "checkpointer: langgraph-checkpoint-postgres not installed, "
                "falling back to MemorySaver"
            )
    
    # Development: Use MemorySaver (volatile but fast)
    logger.info("checkpointer: Using MemorySaver for development")
    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()


async def setup_postgres_checkpointer() -> Optional[object]:
    """
    Initialize PostgresSaver with required tables.
    
    Call this during app startup if using PostgresSaver.
    
    Returns:
        Initialized AsyncPostgresSaver or None if not available
    """
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        logger.warning("checkpointer: DATABASE_URL not set, skipping setup")
        return None
    
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        
        checkpointer = AsyncPostgresSaver.from_conn_string(database_url)
        
        # Setup creates the required tables if they don't exist
        await checkpointer.setup()
        
        logger.info("checkpointer: PostgresSaver initialized successfully")
        return checkpointer
        
    except ImportError:
        logger.warning(
            "checkpointer: langgraph-checkpoint-postgres not installed"
        )
        return None
    except Exception as e:
        logger.error("checkpointer: Failed to setup PostgresSaver", error=str(e))
        return None
