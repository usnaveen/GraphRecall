"""
LangGraph Workflow Graphs for GraphRecall

This package contains the LangGraph StateGraph workflows used for orchestrating
multi-step AI pipelines.

Workflows reachable from the API: ingestion (human-in-the-loop interrupt), chat, article and
link suggestion. The v1 supervisor / research / content / quiz / mermaid / MCP-verify graphs were
removed on 27 Nov 2026: nothing called them, and several queried concepts with no user filter.
"""

from backend.graphs.ingestion_graph import (
    ingestion_graph,
    run_ingestion,
    resume_ingestion,
    get_ingestion_status,
)
from backend.graphs.chat_graph import (
    chat_graph,
    run_chat,
    get_chat_history,
)
from backend.graphs.link_suggestion_graph import (
    link_suggestion_graph,
    run_link_suggestions,
)
from backend.graphs.checkpointer import get_checkpointer, setup_postgres_checkpointer

__all__ = [
    # Ingestion
    "ingestion_graph",
    "run_ingestion",
    "resume_ingestion",
    "get_ingestion_status",
    # Chat (MessagesState pattern)
    "chat_graph",
    "run_chat",
    "get_chat_history",
    # Link Suggestions
    "link_suggestion_graph",
    "run_link_suggestions",
    # Utilities
    "get_checkpointer",
    "setup_postgres_checkpointer",
]
