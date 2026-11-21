"""Shared setup for the GraphRAG eval scripts: isolated databases, the Gemini key, quiet logs.

Defaults point at a dedicated local database (graphrecall_eval) and the local Neo4j, so the eval
never touches app data. Override any of them with real environment variables.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

DEFAULTS = {
    "DATABASE_URL": f"postgresql://{os.getenv('USER', 'postgres')}@localhost:5432/graphrecall_eval",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "graphrecall-dev",
    "CHECKPOINTER": "memory",
}

EVAL_USER_EMAIL = "graphrag-eval@graphrecall.local"


def setup() -> None:
    for k, v in DEFAULTS.items():
        os.environ.setdefault(k, v)
    # The key and the model choice come from the app's own .env, so the eval runs the models the
    # app is configured with (there: GEMINI_CHAT_MODEL / GEMINI_FAST_MODEL). Real env vars win.
    env_file = Path(os.getenv("GR_ENV_FILE", Path.home() / "Projects/GraphRecall/.env"))
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name in ("GOOGLE_API_KEY", "GEMINI_CHAT_MODEL", "GEMINI_FAST_MODEL", "GEMINI_REASONING_MODEL",
                        "GEMINI_EMBEDDING_MODEL") and value:
                os.environ.setdefault(name, value.strip().strip('"'))
    if not os.getenv("GOOGLE_API_KEY"):
        sys.exit("GOOGLE_API_KEY is not set (or set GR_ENV_FILE to a .env that has it)")
    sys.path.insert(0, str(REPO))

    import structlog

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    logging.basicConfig(level=logging.WARNING)
    for noisy in ("httpx", "neo4j", "google_genai", "langchain_google_genai"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    throttle_llm()  # before any backend module builds a model (see throttle_llm)


def models() -> dict:
    from backend.config import llm

    return {"chat": llm.DEFAULT_CHAT_MODEL, "fast": llm.DEFAULT_FAST_MODEL,
            "reasoning": llm.DEFAULT_REASONING_MODEL, "embedding": llm.DEFAULT_EMBEDDING_MODEL}


# Embedding failures are swallowed inside product nodes (chunks saved without vectors, synthesis
# skipped), so the eval counts them here. DAILY_QUOTA flips when the free tier's per-day cap is hit.
EMBED_ERRORS = {"count": 0, "daily_quota": False}


def _record_embed_error(e: Exception) -> None:
    EMBED_ERRORS["count"] += 1
    if "PerDay" in str(e) or "per_day" in str(e).lower():
        EMBED_ERRORS["daily_quota"] = True


_THROTTLED = False


def throttle_llm() -> None:
    """Client-side rate limit on every Gemini chat call (EVAL_RPM, default 12/min for the free tier).

    The app's nodes catch model errors, so an unthrottled run that hits 429s would quietly produce a
    thinner graph instead of failing. It must run before any backend graph module is imported: the
    ingestion graph builds its agents' models at import time, and a client built before this patch
    keeps the unthrottled class (that is how the 2026-11-21 run made ~20 calls/min under EVAL_RPM=12).
    setup() therefore calls it; calling it again is a no-op.
    """
    global _THROTTLED
    if _THROTTLED:
        return
    _THROTTLED = True
    from langchain_core.rate_limiters import InMemoryRateLimiter
    from langchain_google_genai import ChatGoogleGenerativeAI

    from backend.config import llm

    rpm = float(os.getenv("EVAL_RPM", "12"))
    limiter = InMemoryRateLimiter(requests_per_second=rpm / 60, check_every_n_seconds=0.1, max_bucket_size=2)

    class Throttled(ChatGoogleGenerativeAI):
        def __init__(self, **kw):
            kw.setdefault("rate_limiter", limiter)
            super().__init__(**kw)

    llm.ChatGoogleGenerativeAI = Throttled
    llm.get_chat_model.cache_clear()

    # Embeddings have their own free-tier quota (100 requests/min); a burst there makes the synthesis
    # step fail per concept. One token per text, to be safe about how batch requests are counted.
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    erpm = float(os.getenv("EVAL_EMBED_RPM", "80"))
    elimiter = InMemoryRateLimiter(requests_per_second=erpm / 60, check_every_n_seconds=0.1, max_bucket_size=5)

    class ThrottledEmbeddings(GoogleGenerativeAIEmbeddings):
        async def aembed_query(self, text, **kw):
            await elimiter.aacquire()
            try:
                return await super().aembed_query(text, **kw)
            except Exception as e:
                _record_embed_error(e)
                raise

        async def aembed_documents(self, texts, **kw):
            for _ in texts:
                await elimiter.aacquire()
            try:
                return await super().aembed_documents(texts, **kw)
            except Exception as e:
                _record_embed_error(e)
                raise

    llm.GoogleGenerativeAIEmbeddings = ThrottledEmbeddings
    llm.get_embeddings.cache_clear()


def run_key(dataset: str = "grb") -> str:
    """Dataset name plus the optional EVAL_RUN tag. A new tag gives a fresh eval user and ingest log,
    so a re-run never has to delete an earlier run's data (concept ids are unique, names per user)."""
    tag = os.getenv("EVAL_RUN", "").strip()
    return f"{dataset}-{tag}" if tag else dataset


async def eval_user_id(dataset: str = "grb") -> str:
    """One user per dataset (and EVAL_RUN tag), so corpora and runs never share a graph."""
    from backend.db.postgres_client import get_postgres_client

    email = EVAL_USER_EMAIL.replace("@", f"+{run_key(dataset)}@")
    pg = await get_postgres_client()
    rows = await pg.execute_query("SELECT id FROM users WHERE email = :e", {"e": email})
    if rows:
        return str(rows[0]["id"])
    await pg.execute_update("INSERT INTO users (email, name) VALUES (:e, :n)", {"e": email, "n": f"GraphRAG eval ({run_key(dataset)})"})
    rows = await pg.execute_query("SELECT id FROM users WHERE email = :e", {"e": email})
    return str(rows[0]["id"])
