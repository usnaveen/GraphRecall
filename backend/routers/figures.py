"""Figures cropped from the user's own sources (scripts/extract_figures.py).

Owner-only: a figure comes from a book or paper the user uploaded, so it is served to that user
and nobody else, and never from a public URL. Unknown and other users' ids both answer 404.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client

router = APIRouter(prefix="/api/figures", tags=["Figures"])


@router.get("/{figure_id}")
async def get_figure(figure_id: UUID, current_user: dict = Depends(get_current_user)):
    pg = await get_postgres_client()
    rows = await pg.execute_query(
        "SELECT image, mime FROM source_figures WHERE id = CAST(:id AS uuid) AND user_id = CAST(:u AS uuid)",
        {"id": str(figure_id), "u": str(current_user["id"])},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Figure not found")
    return Response(
        content=bytes(rows[0]["image"]),
        media_type=rows[0]["mime"] or "image/png",
        # Private: only this user's device may cache it. A day, because re-running the extractor
        # without --replace re-crops a figure in place under the same id.
        headers={"Cache-Control": "private, max-age=86400"},
    )
