"""
LangGraph Workflow Graphs for GraphRecall

This package contains the LangGraph StateGraph workflows used for orchestrating
multi-step AI pipelines.

Interview-ready patterns demonstrated:
- MessagesState with add_messages reducer (chat_graph)
- Conditional edges for routing (quiz_graph)
- create_react_agent prebuilt (research_graph)
- Human-in-the-loop with interrupts (ingestion_graph)
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
from backend.graphs.quiz_graph import (
    quiz_graph,
    run_quiz_generation,
)
from backend.graphs.research_graph import (
    research_agent,
    run_research,
    get_research_history,
)
from backend.graphs.mermaid_graph import (
    mermaid_graph,
    run_mermaid_generation,
)
from backend.graphs.content_graph import (
    content_graph,
    run_content_generation,
)
from backend.graphs.supervisor_graph import supervisor_graph
from backend.graphs.mcp_graph import mcp_graph, run_verification
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
    # Quiz (Conditional routing)
    "quiz_graph",
    "run_quiz_generation",
    # Research (ReAct agent)
    "research_agent",
    "run_research",
    "get_research_history",
    # Mermaid (Self-Correction)
    "mermaid_graph",
    "run_mermaid_generation",
    # Content (Parallel)
    "content_graph",
    "run_content_generation",
    # Supervisor (Orchestrator)
    "supervisor_graph",
    # Verification (MCP)
    "mcp_graph",
    "run_verification",
    # Utilities
    "get_checkpointer",
    "setup_postgres_checkpointer",
]

