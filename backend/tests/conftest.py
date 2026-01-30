"""Pytest configuration and fixtures for GraphRecall tests."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Set test environment variables
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "test")


@pytest.fixture
def sample_markdown_content():
    """Sample markdown content for testing."""
    return """
# Neural Networks

Neural networks are computing systems inspired by biological neural networks.
They consist of layers of interconnected nodes (neurons) that process information.

## Key Components

1. **Input Layer**: Receives the initial data
2. **Hidden Layers**: Process and transform data
3. **Output Layer**: Produces the final result

## Training

The backpropagation algorithm is used to train neural networks by calculating 
gradients and updating weights to minimize the loss function.

Gradient descent is the optimization algorithm commonly used with backpropagation.
"""


@pytest.fixture
def sample_extracted_concepts():
    """Sample extracted concepts for testing."""
    return [
        {
            "id": "concept-1",
            "name": "Neural Network",
            "definition": "Computing systems inspired by biological neural networks",
            "domain": "Machine Learning",
            "complexity_score": 6,
            "confidence": 0.95,
            "related_concepts": ["Backpropagation", "Gradient Descent"],
            "prerequisites": ["Linear Algebra"],
        },
        {
            "id": "concept-2",
            "name": "Backpropagation",
            "definition": "Algorithm to train neural networks by calculating gradients",
            "domain": "Machine Learning",
            "complexity_score": 7,
            "confidence": 0.9,
            "related_concepts": ["Neural Network", "Gradient Descent"],
            "prerequisites": ["Neural Network", "Calculus"],
        },
        {
            "id": "concept-3",
            "name": "Gradient Descent",
            "definition": "Optimization algorithm to minimize loss functions",
            "domain": "Machine Learning",
            "complexity_score": 6,
            "confidence": 0.85,
            "related_concepts": ["Backpropagation"],
            "prerequisites": ["Calculus"],
        },
    ]


@pytest.fixture
def mock_openai_response():
    """Mock OpenAI API response."""
    return {
        "concepts": [
            {
                "name": "Neural Network",
                "definition": "Computing systems inspired by biological neural networks",
                "domain": "Machine Learning",
                "complexity_score": 6,
                "confidence": 0.95,
                "related_concepts": ["Backpropagation"],
                "prerequisites": ["Linear Algebra"],
            }
        ]
    }


@pytest.fixture
def mock_llm():
    """Mock LangChain LLM."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(
        return_value=MagicMock(
            content='{"concepts": [{"name": "Test Concept", "definition": "A test", "domain": "Test", "complexity_score": 5, "confidence": 0.8, "related_concepts": [], "prerequisites": []}]}'
        )
    )
    return mock


@pytest.fixture
def mock_embeddings():
    """Mock OpenAI Embeddings."""
    mock = AsyncMock()
    mock.aembed_query = AsyncMock(return_value=[0.1] * 1536)
    return mock


@pytest.fixture
def mock_neo4j_client():
    """Mock Neo4j client."""
    mock = AsyncMock()
    mock.create_concept = AsyncMock(return_value={"id": "test-id"})
    mock.create_relationship = AsyncMock(return_value={})
    mock.link_note_to_concepts = AsyncMock(return_value={})
    mock.get_concept = AsyncMock(return_value=None)
    mock.execute_query = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def mock_postgres_client():
    """Mock PostgreSQL client."""
    mock = AsyncMock()
    mock.execute_query = AsyncMock(return_value=[])
    mock.execute_insert = AsyncMock(return_value="test-note-id")
    mock.health_check = AsyncMock(return_value={"status": "healthy"})
    return mock
