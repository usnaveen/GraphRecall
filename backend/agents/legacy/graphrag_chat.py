"""GraphRAG Chat Agent - Combines knowledge graph traversal with RAG for intelligent Q&A.

This agent:
1. Extracts entities/concepts from user queries
2. Traverses the knowledge graph to find relevant context
3. Retrieves related notes using vector similarity
4. Generates responses using the combined context
"""

import json
from typing import Optional

import structlog
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.models.feed_schemas import ChatMessage, ChatResponse

logger = structlog.get_logger()


class QueryAnalysis(BaseModel):
    """Analysis of user query for GraphRAG."""
    
    intent: str  # explain, compare, find, summarize, quiz, path
    entities: list[str]  # Concept names mentioned
    requires_graph: bool  # Whether graph traversal is needed
    requires_rag: bool  # Whether document retrieval is needed


class GraphRAGAgent:
    """
    GraphRAG Chat Agent for knowledge-aware conversations.
    
    Combines:
    - Knowledge Graph: For structured concept relationships
    - Vector Search: For semantic similarity in notes
    - LLM: For natural language understanding and generation
    """
    
    def __init__(
        self,
        neo4j_client,
        pg_client,
        model: str = "gpt-4o-mini",
        embedding_model: str = "text-embedding-3-small",
    ):
        self.neo4j_client = neo4j_client
        self.pg_client = pg_client
        self.model_name = model
        
        self.llm = ChatOpenAI(
            model=model,
            temperature=0.3,  # Lower temperature for more factual responses
        )
        
        self.query_analyzer = ChatOpenAI(
            model="gpt-3.5-turbo-1106",  # Faster model for query analysis
            temperature=0,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        
        self.embeddings = OpenAIEmbeddings(model=embedding_model)
    
    async def analyze_query(self, query: str) -> QueryAnalysis:
        """
        Analyze the user's query to determine intent and extract entities.
        
        Args:
            query: User's natural language query
            
        Returns:
            QueryAnalysis with intent and extracted entities
        """
        prompt = f"""Analyze this user query about their knowledge base.

QUERY: "{query}"

Determine:
1. intent: What does the user want?
   - "explain": Wants explanation of a concept
   - "compare": Wants comparison between concepts
   - "find": Looking for specific information
   - "summarize": Wants summary of a topic
   - "quiz": Wants to be quizzed/tested
   - "path": Wants learning path/prerequisites
   - "general": General question

2. entities: List any concept/topic names mentioned

3. requires_graph: Does this need knowledge graph traversal?
   (Yes for: relationships, prerequisites, connections, paths)

4. requires_rag: Does this need document retrieval?
   (Yes for: specific quotes, detailed explanations, examples from notes)

Output JSON:
{{
    "intent": "explain|compare|find|summarize|quiz|path|general",
    "entities": ["concept1", "concept2"],
    "requires_graph": true|false,
    "requires_rag": true|false
}}"""
        
        try:
            response = await self.query_analyzer.ainvoke(prompt)
            parsed = json.loads(response.content)
            
            return QueryAnalysis(
                intent=parsed.get("intent", "general"),
                entities=parsed.get("entities", []),
                requires_graph=parsed.get("requires_graph", True),
                requires_rag=parsed.get("requires_rag", True),
            )
        except Exception as e:
            logger.error("GraphRAG: Query analysis failed", error=str(e))
            # Default to using both graph and RAG
            return QueryAnalysis(
                intent="general",
                entities=[],
                requires_graph=True,
                requires_rag=True,
            )
    
    async def get_graph_context(
        self,
        entities: list[str],
        depth: int = 2,
    ) -> dict:
        """
        Get context from knowledge graph for given entities.
        
        Args:
            entities: List of concept names to look up
            depth: How many relationship hops to traverse
            
        Returns:
            Dictionary with concepts and relationships
        """
        context = {
            "concepts": [],
            "relationships": [],
            "paths": [],
        }
        
        if not entities:
            return context
        
        try:
            # Find matching concepts
            for entity in entities:
                concepts = await self.neo4j_client.get_concepts_by_name(entity)
                if concepts:
                    context["concepts"].extend(concepts[:3])  # Top 3 matches
            
            # If we found concepts, get their relationships
            concept_ids = [c["id"] for c in context["concepts"]]
            
            if concept_ids:
                # Get relationships between found concepts and neighbors
                relationships_query = """
                MATCH (c1:Concept)-[r]->(c2:Concept)
                WHERE c1.id IN $concept_ids OR c2.id IN $concept_ids
                RETURN 
                    c1.name as from_name,
                    c2.name as to_name,
                    type(r) as relationship,
                    r.strength as strength
                LIMIT 20
                """
                
                relationships = await self.neo4j_client.execute_query(
                    relationships_query,
                    {"concept_ids": concept_ids},
                )
                context["relationships"] = relationships
                
                # Get prerequisite paths if there are multiple concepts
                if len(concept_ids) >= 2:
                    paths_query = """
                    MATCH path = shortestPath(
                        (c1:Concept {id: $id1})-[:PREREQUISITE_OF|BUILDS_ON*..5]-(c2:Concept {id: $id2})
                    )
                    RETURN [n IN nodes(path) | n.name] as concept_path
                    """
                    
                    try:
                        paths = await self.neo4j_client.execute_query(
                            paths_query,
                            {"id1": concept_ids[0], "id2": concept_ids[1]},
                        )
                        context["paths"] = paths
                    except:
                        pass  # Path might not exist
            
            return context
            
        except Exception as e:
            logger.error("GraphRAG: Graph context retrieval failed", error=str(e))
            return context
    
    async def get_rag_context(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
    ) -> list[dict]:
        """
        Get relevant notes using vector similarity search.
        
        Args:
            query: User's query
            user_id: User ID to filter notes
            limit: Maximum number of notes to retrieve
            
        Returns:
            List of relevant note excerpts
        """
        try:
            # Generate query embedding
            query_embedding = await self.embeddings.aembed_query(query)
            
            # Search for similar notes using pgvector
            # Note: This requires the notes to have embeddings stored
            search_query = """
            SELECT 
                id,
                content_text,
                source_url,
                created_at,
                1 - (embedding <=> :embedding::vector) as similarity
            FROM notes
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
            """
            
            results = await self.pg_client.execute_query(
                search_query,
                {
                    "user_id": user_id,
                    "embedding": query_embedding,
                    "limit": limit,
                },
            )
            
            return results
            
        except Exception as e:
            logger.warning("GraphRAG: RAG context retrieval failed", error=str(e))
            
            # Fallback to keyword search
            fallback_query = """
            SELECT 
                id,
                content_text,
                source_url,
                created_at
            FROM notes
            WHERE user_id = :user_id
              AND content_text ILIKE :search_pattern
            ORDER BY created_at DESC
            LIMIT :limit
            """
            
            try:
                results = await self.pg_client.execute_query(
                    fallback_query,
                    {
                        "user_id": user_id,
                        "search_pattern": f"%{query}%",
                        "limit": limit,
                    },
                )
                return results
            except:
                return []
    
    async def generate_response(
        self,
        query: str,
        analysis: QueryAnalysis,
        graph_context: dict,
        rag_context: list[dict],
        conversation_history: list[ChatMessage],
    ) -> str:
        """
        Generate a response using all gathered context.
        
        Args:
            query: User's original query
            analysis: Query analysis results
            graph_context: Context from knowledge graph
            rag_context: Context from document retrieval
            conversation_history: Previous messages for context
            
        Returns:
            Generated response text
        """
        # Build context sections
        context_parts = []
        
        # Graph context
        if graph_context["concepts"]:
            concepts_text = "\n".join([
                f"- {c['name']}: {c.get('definition', 'No definition')}"
                for c in graph_context["concepts"]
            ])
            context_parts.append(f"RELEVANT CONCEPTS:\n{concepts_text}")
        
        if graph_context["relationships"]:
            rels_text = "\n".join([
                f"- {r['from_name']} {r['relationship']} {r['to_name']}"
                for r in graph_context["relationships"]
            ])
            context_parts.append(f"CONCEPT RELATIONSHIPS:\n{rels_text}")
        
        if graph_context.get("paths"):
            paths_text = "\n".join([
                f"- Learning path: {' → '.join(p['concept_path'])}"
                for p in graph_context["paths"]
            ])
            context_parts.append(f"LEARNING PATHS:\n{paths_text}")
        
        # RAG context
        if rag_context:
            notes_text = "\n\n".join([
                f"From note ({n.get('created_at', 'unknown date')}):\n{n['content_text'][:500]}..."
                for n in rag_context
            ])
            context_parts.append(f"RELEVANT NOTES:\n{notes_text}")
        
        full_context = "\n\n".join(context_parts) if context_parts else "No specific context found in your knowledge base."
        
        # Build conversation history
        history_text = ""
        if conversation_history:
            history_text = "\n".join([
                f"{msg.role}: {msg.content}"
                for msg in conversation_history[-5:]  # Last 5 messages
            ])
            history_text = f"\nPREVIOUS CONVERSATION:\n{history_text}\n"
        
        # Intent-specific instructions
        intent_instructions = {
            "explain": "Provide a clear, educational explanation using the context from the user's notes.",
            "compare": "Compare and contrast the mentioned concepts, highlighting key differences and similarities.",
            "find": "Search through the context and provide specific information the user is looking for.",
            "summarize": "Provide a concise summary of the topic using the user's notes as reference.",
            "quiz": "Generate a quick quiz question about the concept (but don't give the answer yet).",
            "path": "Outline a learning path showing prerequisites and how concepts build on each other.",
            "general": "Provide a helpful response based on the user's knowledge base.",
        }
        
        instruction = intent_instructions.get(analysis.intent, intent_instructions["general"])
        
        prompt = f"""You are a knowledgeable study assistant helping a user review their notes and concepts.

{history_text}
CONTEXT FROM USER'S KNOWLEDGE BASE:
{full_context}

USER'S QUESTION: {query}

INSTRUCTIONS: {instruction}

Guidelines:
1. Use the context from their notes/concepts when possible
2. If the context doesn't contain relevant information, say so honestly
3. Reference specific concepts or notes when applicable
4. Keep the response conversational but educational
5. If asked about something not in their knowledge base, suggest they add notes about it

Respond naturally and helpfully:"""
        
        try:
            response = await self.llm.ainvoke(prompt)
            return response.content
        except Exception as e:
            logger.error("GraphRAG: Response generation failed", error=str(e))
            return "I'm sorry, I encountered an error while processing your question. Please try again."
    
    async def chat(
        self,
        user_id: str,
        message: str,
        conversation_history: list[ChatMessage] = None,
    ) -> ChatResponse:
        """
        Main chat method - orchestrates the full GraphRAG pipeline.
        
        Args:
            user_id: User ID
            message: User's message
            conversation_history: Previous messages
            
        Returns:
            ChatResponse with response and metadata
        """
        if conversation_history is None:
            conversation_history = []
        
        logger.info(
            "GraphRAG: Processing chat",
            user_id=user_id,
            message_length=len(message),
        )
        
        # Step 1: Analyze the query
        analysis = await self.analyze_query(message)
        
        logger.info(
            "GraphRAG: Query analyzed",
            intent=analysis.intent,
            entities=analysis.entities,
        )
        
        # Step 2: Get graph context (if needed)
        graph_context = {"concepts": [], "relationships": [], "paths": []}
        if analysis.requires_graph:
            graph_context = await self.get_graph_context(analysis.entities)
        
        # Step 3: Get RAG context (if needed)
        rag_context = []
        if analysis.requires_rag:
            rag_context = await self.get_rag_context(message, user_id)
        
        # Step 4: Generate response
        response_text = await self.generate_response(
            query=message,
            analysis=analysis,
            graph_context=graph_context,
            rag_context=rag_context,
            conversation_history=conversation_history,
        )
        
        # Step 5: Prepare response metadata
        sources = []
        if rag_context:
            sources = [
                {
                    "type": "note",
                    "id": n.get("id"),
                    "title": n.get("source_url") or f"Note from {n.get('created_at', 'unknown')}",
                    "preview": n.get("content_text", "")[:100] + "...",
                }
                for n in rag_context
            ]
        
        related_concepts = [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "domain": c.get("domain"),
            }
            for c in graph_context.get("concepts", [])
        ]
        
        # Generate suggested actions based on intent
        suggested_actions = []
        if analysis.intent == "explain" and related_concepts:
            suggested_actions.append("Practice these concepts")
            suggested_actions.append("View in knowledge graph")
        elif analysis.intent == "path":
            suggested_actions.append("Start learning path")
        elif analysis.intent == "quiz":
            suggested_actions.append("Take a full quiz")
        
        if sources:
            suggested_actions.append("Open source notes")
        
        return ChatResponse(
            response=response_text,
            sources=sources,
            related_concepts=related_concepts,
            suggested_actions=suggested_actions,
        )
