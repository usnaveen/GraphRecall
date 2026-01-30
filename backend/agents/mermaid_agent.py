"""Mermaid Agent - Specialized agent for generating accurate Mermaid diagrams."""

import structlog
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langchain_core.pydantic_v1 import BaseModel, Field

logger = structlog.get_logger()

class MermaidOutput(BaseModel):
    """Structured output for mermaid diagram generation."""
    code: str = Field(description="The valid Mermaid.js code for the diagram")
    explanation: str = Field(description="Brief explanation of what the diagram shows")
    chart_type: str = Field(description="The type of chart generated (e.g. flow, mindmap)")

class MermaidAgent:
    """
    Specialized agent for generating Mermaid diagrams with 'sniper precision'.
    
    Can generate:
    - Mindmaps (for concept hierarchies)
    - Flowcharts (for sensitive processes)
    - Sequence Diagrams (for interactions)
    
    Enforces specific styling to match the 'Liquid Glass' dark theme.
    """
    
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4o", temperature=0.1)
        
    async def generate_mindmap(self, root_concept: str, related_concepts: list[dict]) -> MermaidOutput:
        """Generate a mindmap for a central concept and its relations."""
        
        system_prompt = """You are a Mermaid.js Specialist. Your task is to create visually stunning and syntactically PERFECT Mermaid mindmaps.
        
        STYLE GUIDELINES (Liquid Glass Dark Theme):
        - Use the 'dark' theme base.
        - Root node should be emphasized.
        - Branches should be logically grouped.
        - Do NOT use 'style' classes effectively, rely on pure structure.
        
        IMPORTANT: Return ONLY valid Mermaid syntax for a mindmap.
        Example:
        mindmap
          root((Main Concept))
            related_1
            related_2
              sub_related
        """
        
        concepts_str = "\n".join([f"- {c['name']}: {c.get('relationship', 'related')}" for c in related_concepts])
        
        user_prompt = f"""Create a mindmap for the concept: '{root_concept}'.
        
        Here are the related concepts to include:
        {concepts_str}
        
        Make the structure deep rather than wide where appropriate.
        """
        
        structured_llm = self.llm.with_structured_output(MermaidOutput)
        return await structured_llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])

    async def generate_flowchart(self, process_name: str, steps: list[str]) -> MermaidOutput:
        """Generate a flowchart for a process."""
        
        system_prompt = """You are a Mermaid.js Specialist. Create a flowchart that is clear, logical, and uses the correct shapes.
        
        STYLE GUIDELINES:
        - Use `graph TD` (Top Down) or `graph LR` (Left Right) depending on complexity.
        - Use `([Start/End])` for terminals.
        - Use `[Process]` for actions.
        - Use `{?Decision}` for conditionals.
        - Add `classDef` styles for a neon dark theme.
        
        THEME DEFINITIONS TO INCLUDE:
        classDef default fill:#1A1A1C,stroke:#B6FF2E,stroke-width:2px,color:#fff;
        classDef decision fill:#1A1A1C,stroke:#06B6D4,stroke-width:2px,color:#fff,stroke-dasharray: 5 5;
        classDef term fill:#27272A,stroke:#B6FF2E,stroke-width:3px,color:#fff;
        """
        
        steps_str = "\n".join([f"{i+1}. {step}" for i, step in enumerate(steps)])
        
        user_prompt = f"""Create a flowchart for: '{process_name}'.
        
        Steps involved:
        {steps_str}
        
        Identify any implicit decisions or loops in these steps.
        """
        
        structured_llm = self.llm.with_structured_output(MermaidOutput)
        return await structured_llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ])
