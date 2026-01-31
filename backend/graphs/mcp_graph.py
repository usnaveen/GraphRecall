"""
LangGraph MCP (Model Context Protocol) Workflow

Demonstrates how to integrate an MCP Client within a LangGraph node.
This graph simulates connecting to a "Context7" Fact Checking Server via MCP.

Pattern:
START → call_mcp_server → parse_mcp_result → END
"""

import json
import structlog
from typing import Literal
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

from backend.agents.states import MCPState
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()


# ============================================================================
# Mock MCP Client (Simulating external connection)
# ============================================================================

async def mock_mcp_call(server_name: str, tool_name: str, arguments: dict) -> dict:
    """
    Simulates a call to an MCP server.
    In a real app, this would use `mcp-sdk-python` to connect to a stdio/sse transport.
    """
    logger.info(f"MCP Call: {server_name}/{tool_name}", args=arguments)
    
    # Simulate network latency
    import asyncio
    await asyncio.sleep(1)
    
    claim = arguments.get("query", "").lower()
    
    # Mock responses for demonstration
    if "langgraph" in claim:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "Verified: LangGraph is a library for building stateful, multi-actor applications with LLMs. It extends LangChain. Current version is 1.0+."
                }
            ]
        }
    elif "postgres" in claim:
        return {
            "content": [
                {
                    "type": "text", 
                    "text": "Verified: PostgreSQL is a powerful, open source object-relational database system."
                }
            ]
        }
    else:
        return {
            "content": [
                {
                    "type": "text", 
                    "text": "Ambiguous: Context7 knowledge base has limited information on this specific claim. Recommend cross-referencing with web search."
                }
            ]
        }


# ============================================================================
# Node Functions
# ============================================================================


async def call_mcp_server_node(state: MCPState) -> dict:
    """
    Node 1: Call the Context7 MCP server to verify the claim.
    """
    claim = state.get("claim", "")
    logger.info("call_mcp_server_node: Verifying", claim=claim)
    
    try:
        # User "Context7" server, tool "fact_check"
        response = await mock_mcp_call(
            server_name="context7",
            tool_name="fact_check",
            arguments={"query": claim}
        )
        
        return {"mcp_server_response": response}
        
    except Exception as e:
        logger.error("call_mcp_server_node: MCP Error", error=str(e))
        return {
            "mcp_server_response": {
                "content": [{"type": "text", "text": f"Error connecting to Context7: {str(e)}"}]
            }
        }


async def parse_mcp_result_node(state: MCPState) -> dict:
    """
    Node 2: Interpret MCP response using an LLM to form a final verdict.
    """
    raw_response = state.get("mcp_server_response", {})
    claim = state.get("claim", "")
    
    # Extract text content from MCP format
    content_list = raw_response.get("content", [])
    mcp_text = "\n".join([c.get("text", "") for c in content_list if c.get("type") == "text"])
    
    llm = ChatOpenAI(
        model="gpt-4o-mini", 
        temperature=0,
        model_kwargs={"response_format": {"type": "json_object"}}
    )
    
    prompt = f"""You are a Fact Check Arbiter.
    
    Claim: "{claim}"
    
    Evidence from Context7 (via MCP):
    {mcp_text}
    
    determine the verdict and explanation.
    
    Return JSON:
    {{
        "verdict": "verified" | "incorrect" | "ambiguous",
        "explanation": "Clear explanation citing the evidence",
        "sources": ["Context7"]
    }}
    """
    
    try:
        result = await llm.ainvoke(prompt)
        parsed = json.loads(result.content)
        
        return {
            "verdict": parsed.get("verdict", "ambiguous"),
            "explanation": parsed.get("explanation", "Could not parse verdict."),
            "sources": parsed.get("sources", ["Context7"])
        }
        
    except Exception as e:
        return {
            "verdict": "ambiguous",
            "explanation": f"Failed to parse evidence: {str(e)}",
            "sources": ["System Error"]
        }


# ============================================================================
# Graph Construction
# ============================================================================


def create_mcp_graph():
    builder = StateGraph(MCPState)
    
    builder.add_node("call_mcp", call_mcp_server_node)
    builder.add_node("parse_result", parse_mcp_result_node)
    
    builder.add_edge(START, "call_mcp")
    builder.add_edge("call_mcp", "parse_result")
    builder.add_edge("parse_result", END)
    
    return builder.compile()


mcp_graph = create_mcp_graph()


# ============================================================================
# Public Interface
# ============================================================================

async def run_verification(claim: str) -> dict:
    """Run the verification graph."""
    result = await mcp_graph.ainvoke({"claim": claim})
    return {
        "verdict": result.get("verdict"),
        "explanation": result.get("explanation"),
        "sources": result.get("sources")
    }
