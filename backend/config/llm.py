"""Centralized LLM configuration for GraphRecall.

Uses Google Gemini models for cost-effectiveness and reliability.

Model Options (2026):
- gemini-2.5-flash: Best cost/intelligence ratio ($0.15/$0.60 per 1M tokens)
- gemini-2.5-flash-lite: Cheapest, for simple tasks ($0.10/$0.40 per 1M tokens)
- gemini-2.5-pro: Most capable, for complex reasoning ($1.25/$10 per 1M tokens)

Embedding:
- gemini-embedding-001: #1 on MTEB, supports MRL (768/1536/3072 dims)
  Using 768 dims: only 0.26% quality loss vs 3072, 75% less storage
"""

import os
from functools import lru_cache
from typing import Optional

import structlog
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from backend.telemetry import LLM_TIMING_CALLBACK

logger = structlog.get_logger()

# Default models — overridable per environment. Google retired gemini-2.5-flash for new
# API keys (Sep 2026), so defaults track the current Flash / Flash-Lite generation.
DEFAULT_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.6-flash")  # Assistant answers, synthesis
DEFAULT_REASONING_MODEL = os.getenv("GEMINI_REASONING_MODEL", DEFAULT_CHAT_MODEL)
# Measured Sep 2026: 3.5-flash-lite reached its first token in ~1.1 s vs ~2.0 s for 3.1-flash-lite.
DEFAULT_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-3.5-flash-lite")  # Cheap classification / extraction
DEFAULT_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-001")  # #1 on MTEB multilingual
DEFAULT_EMBEDDING_DIMS = 768  # MRL: 768 dims = 99.74% quality of 3072, 75% less storage


DEFAULT_CHAT_TIMEOUT_S = float(os.getenv("LLM_CHAT_TIMEOUT_S", "25"))
DEFAULT_FAST_TIMEOUT_S = float(os.getenv("LLM_FAST_TIMEOUT_S", "10"))
DEFAULT_CHAT_MAX_TOKENS = int(os.getenv("LLM_CHAT_MAX_TOKENS", "2048"))
DEFAULT_FAST_MAX_TOKENS = int(os.getenv("LLM_FAST_MAX_TOKENS", "1024"))


@lru_cache(maxsize=16)
def get_chat_model(
    model: Optional[str] = None,
    temperature: float = 0.3,
    json_mode: bool = False,
    timeout: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> ChatGoogleGenerativeAI:
    """Get a cached chat model instance.

    Args:
        model: Model name (defaults to gemini-3.6-flash)
        temperature: Creativity (0.0 = deterministic, 1.0 = creative)
        json_mode: If True, enables JSON output mode
        timeout: Per-call HTTP timeout in seconds (defaults to LLM_CHAT_TIMEOUT_S=25)
        max_output_tokens: Output token cap (defaults to LLM_CHAT_MAX_TOKENS=2048)
    """
    model_name = model or DEFAULT_CHAT_MODEL
    resolved_timeout = timeout if timeout is not None else DEFAULT_CHAT_TIMEOUT_S
    resolved_max_tokens = max_output_tokens if max_output_tokens is not None else DEFAULT_CHAT_MAX_TOKENS

    logger.debug(
        "Creating chat model",
        model=model_name,
        temperature=temperature,
        json_mode=json_mode,
        timeout=resolved_timeout,
        max_output_tokens=resolved_max_tokens,
    )

    # Build kwargs - only pass generation_config for json_mode to avoid
    # conflicting with the direct temperature parameter
    kwargs: dict = {}
    if json_mode:
        kwargs["model_kwargs"] = {
            "generation_config": {"response_mime_type": "application/json"}
        }

    # Langchain's Google GenAI integration supports a 'max_retries' param
    # which handles 5xx errors automatically
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
        temperature=temperature,
        convert_system_message_to_human=True,
        max_retries=2,
        timeout=resolved_timeout,
        max_output_tokens=resolved_max_tokens,
        # Latency, time-to-first-token and token usage for every call (GET /api/debug/latency).
        callbacks=[LLM_TIMING_CALLBACK],
        **kwargs,
    )


def get_reasoning_model(
    temperature: float = 0.2,
    json_mode: bool = False,
    timeout: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> ChatGoogleGenerativeAI:
    """Get a model for complex reasoning tasks."""
    return get_chat_model(
        model=DEFAULT_REASONING_MODEL,
        temperature=temperature,
        json_mode=json_mode,
        timeout=timeout,
        max_output_tokens=max_output_tokens,
    )


def get_fast_model(
    temperature: float = 0.3,
    json_mode: bool = False,
    timeout: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> ChatGoogleGenerativeAI:
    """Get the fastest/cheapest model for simple tasks."""
    return get_chat_model(
        model=DEFAULT_FAST_MODEL,
        temperature=temperature,
        json_mode=json_mode,
        timeout=timeout if timeout is not None else DEFAULT_FAST_TIMEOUT_S,
        max_output_tokens=max_output_tokens if max_output_tokens is not None else DEFAULT_FAST_MAX_TOKENS,
    )


@lru_cache(maxsize=1)
def get_embeddings() -> GoogleGenerativeAIEmbeddings:
    """Get embedding model for vector search.

    Uses gemini-embedding-001 (#1 on MTEB multilingual benchmark).
    Default dimensionality is 768 (MRL-trained, 99.74% quality of 3072).
    """
    return GoogleGenerativeAIEmbeddings(
        model=DEFAULT_EMBEDDING_MODEL,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


def get_embedding_dims() -> int:
    """Get the configured embedding dimensionality."""
    return DEFAULT_EMBEDDING_DIMS


# Backwards compatibility aliases
def ChatModel(
    model: str = DEFAULT_CHAT_MODEL,
    temperature: float = 0.3,
    **kwargs,
) -> ChatGoogleGenerativeAI:
    """Drop-in replacement for ChatOpenAI."""
    json_mode = kwargs.get("model_kwargs", {}).get("response_format", {}).get("type") == "json_object"
    return get_chat_model(model=model, temperature=temperature, json_mode=json_mode)
