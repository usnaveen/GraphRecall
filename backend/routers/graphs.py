"""Graphs Router — the named graphs a user's concepts are filed under.

A graph is the ``domain`` on :Concept. These endpoints let the web app show a
switcher ("All graphs" plus one entry per subject), tidy up drift by renaming or
merging, and repair concepts whose embeddings are missing so similarity search
sees the whole graph.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.services import graph_registry
from backend.services.concept_similarity import (
    backfill_concept_embeddings,
    ensure_vector_index,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/graphs", tags=["Graphs"])


class RenameGraphRequest(BaseModel):
    new_name: str = Field(min_length=1, max_length=64)


class ResolveGraphRequest(BaseModel):
    concept_name: str = Field(min_length=1)
    definition: Optional[str] = None
    proposed: Optional[str] = None


@router.get("")
async def list_graphs(current_user: dict = Depends(get_current_user)):
    """Every graph the user has, largest first, with a total for 'All graphs'."""
    try:
        user_id = str(current_user["id"])
        graphs = await graph_registry.list_graphs(user_id)
        return {
            "graphs": graphs,
            "total_concepts": sum(g["concept_count"] for g in graphs),
        }
    except Exception as e:
        logger.error("Graphs: list failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/resolve")
async def resolve(
    request: ResolveGraphRequest,
    current_user: dict = Depends(get_current_user),
):
    """Which graph would this concept be filed into? Does not write anything.

    Lets the canvas show the destination graph before the concept is committed.
    """
    try:
        user_id = str(current_user["id"])
        return await graph_registry.resolve_graph(
            user_id,
            proposed=request.proposed,
            concept_name=request.concept_name,
            definition=request.definition or "",
        )
    except Exception as e:
        logger.error("Graphs: resolve failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{name}")
async def rename(
    name: str,
    request: RenameGraphRequest,
    current_user: dict = Depends(get_current_user),
):
    """Rename a graph — or merge it into another by giving an existing name."""
    try:
        user_id = str(current_user["id"])
        existing = await graph_registry.graph_names(user_id)
        if name not in existing:
            raise HTTPException(status_code=404, detail=f"No graph named {name!r}")

        target = graph_registry.normalize_graph_name(request.new_name)
        merged_into = target in existing and target != name
        moved = await graph_registry.rename_graph(user_id, name, target)

        return {
            "status": "merged" if merged_into else "renamed",
            "from": name,
            "to": target,
            "concepts_moved": moved,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Graphs: rename failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reindex")
async def reindex(current_user: dict = Depends(get_current_user)):
    """Create the vector index if missing and embed any concept lacking a vector.

    A concept without an embedding is invisible to similarity search, so it never
    attracts links and new papers never find it. Run this after a bulk ingest or
    any run where embedding calls failed.
    """
    try:
        user_id = str(current_user["id"])
        index_ready = await ensure_vector_index()
        result = await backfill_concept_embeddings(user_id)
        return {"index_ready": index_ready, **result}
    except Exception as e:
        logger.error("Graphs: reindex failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
