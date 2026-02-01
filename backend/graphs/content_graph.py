"""
LangGraph Content Generation Workflow (Parallel Pattern)

Demonstrates the Parallel / Map-Reduce pattern for interview:
- Plans content strategy (Map setup)
- Executes generation in parallel (Parallel fan-out)
- Aggregates results (Reduce)
- Uses MessageState for coordination

Flow:
START → plan_content → [generate_mcq, generate_flashcards, generate_diagram] → aggregate → END
"""

import json
from typing import Annotated

import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from backend.config.llm import get_chat_model
from langgraph.graph import StateGraph, START, END

from backend.agents.states import ContentState
from backend.db.neo4j_client import get_neo4j_client
from backend.graphs.mermaid_graph import run_mermaid_generation

logger = structlog.get_logger()


# ============================================================================
# Node Functions
# ============================================================================


async def plan_content_node(state: ContentState) -> dict:
    """
    Node 1: Plan content generation.
    Fetches required concepts from DB to prepare for parallel tasks.
    """
    topic = state.get("topic", "")
    logger.info("plan_content: Planning", topic=topic)
    
    neo4j = await get_neo4j_client()
    concepts = await neo4j.execute_query(
        """
        MATCH (c:Concept)
        WHERE toLower(c.name) CONTAINS toLower($topic)
        RETURN c.name as name, c.definition as definition
        LIMIT 5
        """,
        {"topic": topic}
    )
    
    return {"concepts": concepts}


async def generate_mcq_node(state: ContentState) -> dict:
    """
    Parallel Node A: Generate MCQs.
    """
    concepts = state.get("concepts", [])
    if not concepts:
        return {"mcqs": []}
    
    logger.info("generate_mcq: Starting")
    
    llm = get_chat_model(temperature=0.5)
    
    concept_text = "\n".join([f"{c['name']}: {c['definition']}" for c in concepts])
    
    prompt = f"""Generate 3 multiple choice questions based on these concepts:
{concept_text}

Output JSON: {{ "questions": [{{ "q": "...", "options": ["..."], "answer": "..." }}] }}"""

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        data = json.loads(response.content)
        return {"mcqs": data.get("questions", [])}
    except Exception as e:
        logger.error("generate_mcq: Failed", error=str(e))
        return {"mcqs": []}


async def generate_flashcards_node(state: ContentState) -> dict:
    """
    Parallel Node B: Generate Flashcards.
    """
    concepts = state.get("concepts", [])
    if not concepts:
        return {"flashcards": []}
        
    logger.info("generate_flashcards: Starting")
    
    llm = get_chat_model(temperature=0.3)
    
    concept_text = "\n".join([f"{c['name']}: {c['definition']}" for c in concepts])
    
    prompt = f"""Generate 5 flashcards (front/back) for these concepts:
{concept_text}

Output JSON: {{ "cards": [{{ "front": "...", "back": "..." }}] }}"""

    try:
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        data = json.loads(response.content)
        return {"flashcards": data.get("cards", [])}
    except:
        return {"flashcards": []}


async def generate_diagram_node(state: ContentState) -> dict:
    """
    Parallel Node C: Generate Diagram.
    Calls the mermaid_graph for generation! (Graph calling Graph)
    """
    topic = state.get("topic", "")
    logger.info("generate_diagram: Starting")
    
    # Re-use our mermaid graph!
    result = await run_mermaid_generation(
        description=f"Concept map for {topic}", 
        chart_type="mindmap"
    )
    
    if result.get("success"):
        return {"diagram": result}
    else:
        return {"diagram": None}


async def aggregate_node(state: ContentState) -> dict:
    """
    Node 3: Aggregate parallel results.
    """
    mcqs = state.get("mcqs", [])
    cards = state.get("flashcards", [])
    diagram = state.get("diagram", {})
    
    logger.info("aggregate: Compiling final pack")
    
    final_pack = {
        "summary": f"Generated {len(mcqs)} questions, {len(cards)} cards, and 1 diagram.",
        "content": {
            "mcqs": mcqs,
            "flashcards": cards,
            "diagram": diagram
        }
    }
    
    return {"final_pack": final_pack}


# ============================================================================
# Graph Builder
# ============================================================================


def create_content_graph():
    """
    Build the Content Generation graph (Parallel Execution).
    """
    builder = StateGraph(ContentState)
    
    # Add nodes
    builder.add_node("plan", plan_content_node)
    builder.add_node("gen_mcq", generate_mcq_node)
    builder.add_node("gen_cards", generate_flashcards_node)
    builder.add_node("gen_diagram", generate_diagram_node)
    builder.add_node("aggregate", aggregate_node)
    
    # Sequencing
    builder.add_edge(START, "plan")
    
    # Parallel Fan-Out: Plan -> [A, B, C]
    builder.add_edge("plan", "gen_mcq")
    builder.add_edge("plan", "gen_cards")
    builder.add_edge("plan", "gen_diagram")
    
    # Parallel Fan-In: [A, B, C] -> Aggregate
    builder.add_edge("gen_mcq", "aggregate")
    builder.add_edge("gen_cards", "aggregate")
    builder.add_edge("gen_diagram", "aggregate")
    
    builder.add_edge("aggregate", END)
    
    return builder.compile()


# Global graph
content_graph = create_content_graph()


# ============================================================================
# Public Interface
# ============================================================================


async def run_content_generation(topic: str, user_id: str = "default") -> dict:
    """
    Run parallel content generation.
    """
    initial = {"topic": topic, "user_id": user_id}
    
    try:
        result = await content_graph.ainvoke(initial)
        return result.get("final_pack", {})
    except Exception as e:
        logger.error("run_content_generation: Failed", error=str(e))
        return {"error": str(e)}
