"""Centralized LLM configuration for GraphRecall.

Uses Google Gemini models for cost-effectiveness and reliability.

Model Options:
- gemini-2.0-flash-exp: Latest, fastest, free tier available
- gemini-1.5-flash: Fast, cheap ($0.075/1M input tokens)
- gemini-1.5-pro: Most capable ($1.25/1M input tokens)
"""

import os
from functools import lru_cache
from typing import Optional

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

logger = structlog.get_logger()

# Default models - using cheapest options
DEFAULT_CHAT_MODEL = "gemini-2.5-flash"  # Fast, efficient
DEFAULT_REASONING_MODEL = "gemini-2.0-flash-thinking-exp-01-21"  # Thinking model
DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-001"  # 3072 dimensions


@lru_cache(maxsize=8)
def get_chat_model(
    model: Optional[str] = None,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> ChatGoogleGenerativeAI:
    """Get a cached chat model instance.

    Args:
        model: Model name (defaults to gemini-2.5-flash)
        temperature: Creativity (0.0 = deterministic, 1.0 = creative)
        json_mode: If True, enables JSON output mode
    """
    model_name = model or DEFAULT_CHAT_MODEL

    logger.debug("Creating chat model", model=model_name, temperature=temperature, json_mode=json_mode)

    # Build kwargs - only pass generation_config for json_mode to avoid
    # conflicting with the direct temperature parameter
    kwargs: dict = {}
    if json_mode:
        kwargs["model_kwargs"] = {
            "generation_config": {"response_mime_type": "application/json"}
        }

    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=temperature,
        convert_system_message_to_human=True,  # Gemini quirk
        **kwargs,
    )


def get_reasoning_model(
    temperature: float = 0.2,
    json_mode: bool = False,
) -> ChatGoogleGenerativeAI:
    """Get a model for complex reasoning tasks."""
    return get_chat_model(
        model=DEFAULT_REASONING_MODEL,
        temperature=temperature,
        json_mode=json_mode,
    )


def get_fast_model(
    temperature: float = 0.3,
    json_mode: bool = False,
) -> ChatGoogleGenerativeAI:
    """Get the fastest/cheapest model for simple tasks."""
    return get_chat_model(
        model=DEFAULT_CHAT_MODEL,
        temperature=temperature,
        json_mode=json_mode,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Get embedding model for vector search."""
    return GoogleGenerativeAIEmbeddings(
        model=DEFAULT_EMBEDDING_MODEL,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


# Backwards compatibility aliases
def ChatModel(
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.3,
    **kwargs,
) -> ChatGoogleGenerativeAI:
    """Drop-in replacement for ChatOpenAI."""
    json_mode = kwargs.get("model_kwargs", {}).get("response_format", {}).get("type") == "json_object"
    return get_chat_model(model=model, temperature=temperature, json_mode=json_mode)
