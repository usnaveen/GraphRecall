"""Serve book/image assets from a configurable directory."""

from pathlib import Path
import os

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = structlog.get_logger()

router = APIRouter(prefix="/api/images", tags=["Images"])

# Default to the sample book images (note the trailing space in folder name)
DEFAULT_IMAGE_DIR = Path(
    os.environ.get(
        "BOOK_IMAGE_DIR",
        "sample_content/The Hundred-Page Language Models Book /images",
    )
).resolve()


def _safe_join(base: Path, filename: str) -> Path:
    """Prevent path traversal while resolving the image file."""
    candidate = (base / filename).resolve()
    if not str(candidate).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return candidate


@router.get("/{filename:path}")
async def get_image(filename: str):
    """
    Serve an image by filename from the configured directory.

    This keeps ingestion simple: stored image URLs can point to `/api/images/{filename}`.
    """
    base_dir = DEFAULT_IMAGE_DIR
    try:
        path = _safe_join(base_dir, filename)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Image path resolution failed", filename=filename, error=str(e))
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(path)

