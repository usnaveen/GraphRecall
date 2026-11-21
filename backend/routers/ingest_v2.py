"""
V2 Ingest Router - LangGraph-powered note ingestion.

This router uses the new LangGraph StateGraph workflow for ingestion,
following modern LangGraph 1.0.7 patterns with:
- Conditional edges for overlap detection
- Human-in-the-loop interrupts for concept review
- PostgresSaver for production persistence
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import os
import posixpath
from typing import Any, Optional
import uuid

import asyncio
import zipfile
import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from backend.auth.middleware import get_current_user
from backend.services.quota import require_quota
from backend.agents.scanner_agent import ScannerAgent
from backend.db.postgres_client import get_postgres_client
from backend.services.community_service import CommunityService
from backend.services.storage_service import get_storage_service
from backend.services.ingestion.reembed import reembed_missing_chunks
import base64

from backend.agent_v2.enqueue import enqueue_durable_job
from backend.agent_v2.protocols import (
    CommunityRecomputePayload,
    EmbeddingsRetryPayload,
    NoteIngestedPayload,
    QuizScanPayload,
)
from backend.graphs.ingestion_graph import (
    run_ingestion,
    resume_ingestion,
    get_ingestion_status,
)
from backend.routers import agent_v2 as agent_v2_router

logger = structlog.get_logger()
scanner_agent = ScannerAgent()

router = APIRouter(prefix="/api/v2", tags=["V2 Ingestion"])


async def _enqueue_note_ingested_event(
    user_id: str,
    note_id: Optional[str],
    note_title: str,
    concepts: list[Any],
) -> None:
    """Best-effort enqueue of a `note.ingested` Agent v2 job; never fails HTTP ingest."""
    if not note_id:
        return
    concept_names: list[str] = []
    for item in concepts or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("concept_name")
            if name:
                concept_names.append(str(name))
        elif isinstance(item, str) and item.strip():
            concept_names.append(item.strip())
    try:
        queue = await agent_v2_router.get_job_queue()
        payload = NoteIngestedPayload(
            note_id=str(note_id),
            note_title=note_title or "",
            concept_names=concept_names,
        )
        await queue.enqueue(user_id, "note.ingested", payload.model_dump())
    except Exception as exc:  # noqa: BLE001 - best-effort async event hook
        logger.warning(
            "v2/ingest: failed to enqueue note.ingested",
            note_id=note_id,
            error=str(exc),
        )

SUPPORTED_ZIP_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}
MAX_ZIP_EVENTS = 300

# In-memory event/result buffers for active processed-zip ingestions.
_zip_ingest_events: dict[str, list[dict[str, Any]]] = {}
_zip_ingest_results: dict[str, dict[str, Any]] = {}
_zip_ingest_owners: dict[str, str] = {}


def _append_zip_event(thread_id: str, level: str, message: str, **details: Any) -> None:
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": message,
    }
    if details:
        event["details"] = details

    events = _zip_ingest_events.setdefault(thread_id, [])
    events.append(event)
    if len(events) > MAX_ZIP_EVENTS:
        del events[: len(events) - MAX_ZIP_EVENTS]


def _replace_image_references(content: str, references: list[str], replacement_url: str) -> str:
    updated = content
    for ref in sorted(set(references), key=len, reverse=True):
        if ref:
            updated = updated.replace(ref, replacement_url)
    return updated


def _extract_processed_zip_payload(zip_bytes: bytes) -> tuple[str, list[dict[str, Any]], str]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as archive:
        entries = [name for name in archive.namelist() if not name.endswith("/")]

        md_entries = [name for name in entries if name.lower().endswith(".md")]
        if not md_entries:
            raise ValueError("No markdown file found in zip")

        def rank_markdown_entry(name: str) -> tuple[int, int, int]:
            basename = posixpath.basename(name).lower()
            is_full_text = 0 if basename == "full_text.md" else 1
            depth = name.count("/")
            return (is_full_text, depth, len(name))

        markdown_entry = sorted(md_entries, key=rank_markdown_entry)[0]
        markdown_content = archive.read(markdown_entry).decode("utf-8", errors="replace")

        basename_counts = Counter(
            posixpath.basename(path).lower()
            for path in entries
            if posixpath.splitext(path)[1].lower() in SUPPORTED_ZIP_IMAGE_TYPES
        )

        image_entries: list[dict[str, Any]] = []
        for name in entries:
            normalized = name.replace("\\", "/").lstrip("./")
            ext = posixpath.splitext(normalized)[1].lower()
            if ext not in SUPPORTED_ZIP_IMAGE_TYPES:
                continue

            basename = posixpath.basename(normalized)
            references = {
                normalized,
                normalized.lstrip("/"),
            }
            parts = normalized.split("/")
            if len(parts) >= 2:
                references.add("/".join(parts[-2:]))
            if basename_counts[basename.lower()] == 1:
                references.add(basename)

            image_entries.append(
                {
                    "basename": basename,
                    "content_type": SUPPORTED_ZIP_IMAGE_TYPES[ext],
                    "bytes": archive.read(name),
                    "references": sorted(references, key=len, reverse=True),
                }
            )

    return markdown_content, image_entries, markdown_entry


async def _ingest_processed_zip_background(
    *,
    thread_id: str,
    user_id: str,
    zip_bytes: bytes,
    filename: str,
    title: Optional[str],
    skip_review: bool,
    resource_type: Optional[str],
) -> None:
    try:
        _append_zip_event(thread_id, "info", "Background ingest started", filename=filename)
        content, image_entries, markdown_entry = _extract_processed_zip_payload(zip_bytes)
        _append_zip_event(
            thread_id,
            "info",
            "Zip payload extracted",
            markdown_entry=markdown_entry,
            image_count=len(image_entries),
            content_chars=len(content),
        )

        final_content = content
        if image_entries:
            storage = get_storage_service()
            total_images = len(image_entries)
            for idx, image in enumerate(image_entries, start=1):
                try:
                    uploaded_url = await storage.upload_file(
                        image["bytes"],
                        image["basename"],
                        image["content_type"],
                        user_id,
                    )
                    final_content = _replace_image_references(
                        final_content,
                        image["references"],
                        uploaded_url,
                    )
                except Exception as image_error:
                    _append_zip_event(
                        thread_id,
                        "warning",
                        "Image upload failed",
                        image=image["basename"],
                        error=str(image_error),
                    )
                    continue

                if idx == 1 or idx == total_images or idx % 10 == 0:
                    _append_zip_event(
                        thread_id,
                        "info",
                        "Image upload progress",
                        uploaded=idx,
                        total=total_images,
                    )

        resolved_title = title or posixpath.splitext(filename)[0] or "Processed Book"
        content_hash = hashlib.sha256(final_content.encode("utf-8")).hexdigest()
        _append_zip_event(thread_id, "info", "Invoking ingestion workflow", skip_review=skip_review)

        result = await run_ingestion(
            content=final_content,
            title=resolved_title,
            user_id=user_id,
            skip_review=skip_review,
            content_hash=content_hash,
            resource_type=resource_type or "book",
            thread_id=thread_id,
        )
        _zip_ingest_results[thread_id] = result

        status = result.get("status", "completed")
        _append_zip_event(
            thread_id,
            "info",
            "Background ingest completed",
            status=status,
            status_reason=result.get("status_reason"),
            note_id=result.get("note_id"),
            concepts=len(result.get("concept_ids", []) or []),
            flashcards=len(result.get("flashcard_ids", []) or []),
        )

        if status == "completed":
            await _schedule_community_recompute(user_id, result.get("note_id"))
            await _enqueue_note_ingested_event(
                user_id,
                result.get("note_id"),
                resolved_title,
                result.get("concepts", []) or [],
            )
        await _schedule_reembed_if_needed(result, user_id)

        if status in {"completed", "awaiting_review"} and result.get("note_id"):
            await _schedule_quiz_scan(user_id, result.get("note_id"), final_content)
    except Exception as e:
        logger.error(
            "v2/ingest/processed-zip: Background task failed",
            thread_id=thread_id,
            error=str(e),
        )
        error_result = {
            "status": "error",
            "status_reason": "error_runtime",
            "next_action": "none",
            "error": str(e),
            "thread_id": thread_id,
        }
        _zip_ingest_results[thread_id] = error_result
        _append_zip_event(thread_id, "error", "Background ingest failed", error=str(e))


REEMBED_RETRY_DELAYS_S = (60, 300, 900)


async def _schedule_community_recompute(user_id: str, note_id: Optional[str] = None) -> None:
    """Enqueue durable community recomputation with short dedup window."""
    try:
        pg = await get_postgres_client()
    except Exception:
        pg = None
    if pg is None:
        return
    await enqueue_durable_job(
        user_id,
        "community.recompute",
        CommunityRecomputePayload(note_id=str(note_id) if note_id else None).model_dump(),
        dedupe_window_seconds=120,
        pg_client=pg,
    )


async def _schedule_quiz_scan(user_id: str, note_id: Optional[str], content: str) -> None:
    """Enqueue durable passive quiz scan on `agent_jobs`."""
    if not note_id:
        return
    try:
        pg = await get_postgres_client()
    except Exception:
        pg = None
    if pg is None:
        return
    await enqueue_durable_job(
        user_id,
        "quiz.scan",
        QuizScanPayload(note_id=str(note_id), content=content[:12000]).model_dump(),
        pg_client=pg,
    )


async def _schedule_reembed_if_needed(result: dict, user_id: str) -> None:
    """If an ingest saved chunks without vectors, enqueue durable backoff retries."""
    if result.get("next_action") == "reembed" and result.get("note_id"):
        try:
            pg = await get_postgres_client()
        except Exception:
            pg = None
        if pg is None:
            return
        await enqueue_durable_job(
            user_id,
            "embeddings.retry",
            EmbeddingsRetryPayload(note_id=str(result["note_id"])).model_dump(),
            delay_seconds=60.0,
            max_attempts=4,
            pg_client=pg,
        )


async def _retry_missing_embeddings(note_id: str, user_id: str, delays=REEMBED_RETRY_DELAYS_S) -> None:
    """Backoff retries for chunks saved without embeddings (quota errors are usually transient).

    In-process, so a restart drops pending retries; POST /ingest/notes/{note_id}/reembed and the
    eval's backfill script cover that until a durable job queue owns retries.
    """
    for delay in delays:
        await asyncio.sleep(delay)
        try:
            result = await reembed_missing_chunks(user_id, note_id)
        except Exception as e:  # noqa: BLE001 - background task; log and try again later
            logger.warning("reembed retry failed", note_id=note_id, error=str(e))
            continue
        if result["still_missing"] == 0:
            return
    logger.error("reembed: chunks still without embeddings after retries", note_id=note_id)


class ReembedResponse(BaseModel):
    note_id: str
    missing_before: int
    embedded: int
    still_missing: int


@router.post("/ingest/notes/{note_id}/reembed", response_model=ReembedResponse)
async def reembed_note(note_id: str, current_user: dict = Depends(get_current_user)):
    """Embed this note's chunks that were saved without a vector (makes them searchable)."""
    user_id = str(current_user["id"])
    pg = await get_postgres_client()
    owned = await pg.execute_query(
        "SELECT 1 FROM notes WHERE id = CAST(:n AS uuid) AND user_id = CAST(:u AS uuid)", {"n": note_id, "u": user_id}
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Note not found")
    result = await reembed_missing_chunks(user_id, note_id, pg=pg)
    return ReembedResponse(note_id=note_id, **result)


async def _recompute_communities(user_id: str) -> None:
    """Recompute communities in the background after ingestion.

    Runs Louvain detection, persists results, and generates LLM summaries.
    Errors are logged but never propagated (fire-and-forget task).
    """
    try:
        service = CommunityService()
        communities = await service.compute_communities(user_id)
        await service.persist_communities(user_id, communities)
        await service.generate_community_summaries(user_id)
        logger.info(
            "Background community recompute complete",
            user_id=user_id,
            num_communities=len(communities),
        )
    except Exception as e:
        logger.error("Background community recompute failed", user_id=user_id, error=str(e))


# ============================================================================
# Request/Response Models
# ============================================================================


class IngestRequest(BaseModel):
    """Request body for note ingestion."""

    content: str
    title: Optional[str] = None
    skip_review: bool = False  # If True, auto-approve concepts
    resource_type: Optional[str] = None  # e.g. "book", "notes", "article"
    images: Optional[dict[str, str]] = None  # Map of filename -> base64 string


class IngestResponse(BaseModel):
    """Response from note ingestion."""

    note_id: Optional[str] = None
    concepts: list[dict] = []
    concept_ids: list[Optional[str]] = []  # Allow None values (filtered on output)
    flashcard_ids: list[str] = []
    synthesis_decisions: Optional[list[dict]] = None
    processing_metadata: Optional[dict] = None  # Geekout facts for UI
    status: str  # "completed", "awaiting_review", "error"
    status_reason: str = "completed"  # completed, awaiting_review_overlap, error_extraction, ...
    next_action: str = "none"  # approve_required, none
    thread_id: str  # For resuming workflow
    error: Optional[str] = None
    # e.g. chunks saved without embeddings (status_reason "completed_missing_embeddings")
    warnings: list[str] = []


class ResumeRequest(BaseModel):
    """Request to resume ingestion after user review."""
    
    approved_concepts: list[dict]  # User-approved/modified concepts
    cancelled: bool = False


class StatusResponse(BaseModel):
    """Current status of an ingestion workflow."""
    
    status: str  # "processing", "awaiting_review", "completed", "error", "not_found"
    status_reason: str = "processing"
    next_action: str = "none"
    thread_id: str
    stage: Optional[str] = None
    progress: Optional[dict] = None
    note_id: Optional[str] = None
    next_step: Optional[str] = None
    concepts: list[dict] = []
    synthesis_decisions: Optional[list[dict]] = None
    error: Optional[str] = None


class ProcessedZipIngestStartResponse(BaseModel):
    """Response when processed zip ingestion is queued in background."""

    status: str  # processing, completed_duplicate, error
    status_reason: str = "queued"
    next_action: str = "none"
    thread_id: str
    message: str
    note_id: Optional[str] = None
    error: Optional[str] = None


class IngestEventsResponse(BaseModel):
    """Event stream + current status for processed zip ingestion."""

    thread_id: str
    status: str
    status_reason: str = "processing"
    next_action: str = "none"
    stage: Optional[str] = None
    progress: Optional[dict] = None
    note_id: Optional[str] = None
    events: list[dict] = []
    result: Optional[dict] = None


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/ingest", response_model=IngestResponse)
async def ingest_note(
    request: IngestRequest,
    current_user: dict = Depends(require_quota("ingest")),
):
    """
    Ingest a note using the LangGraph workflow.
    
    This endpoint uses the StateGraph-based ingestion pipeline:
    1. extract_concepts - LLM extracts key concepts
    2. store_note - Saves note to PostgreSQL
    3. find_related - Finds similar existing concepts
    4. (conditional) - If overlap detected, prepares synthesis decisions
    5. user_review - PAUSES for human approval (unless skip_review=True)
    6. create_concepts - Creates concept nodes in Neo4j
    7. generate_flashcards - Creates flashcards for learning
    
    If overlap is detected and skip_review=False, returns with status="awaiting_review".
    Use the thread_id to check status or resume the workflow.
    """
    user_id = str(current_user["id"])
    logger.info(
        "v2/ingest: Starting ingestion",
        content_length=len(request.content),
        user_id=user_id,
        skip_review=request.skip_review,
    )
    
    try:
        # 1. Check for duplicates
        content_hash = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
        
        pg_client = await get_postgres_client()
        existing_note = await pg_client.execute_query(
            "SELECT id FROM notes WHERE user_id = :user_id AND content_hash = :hash_val",
            {"user_id": user_id, "hash_val": content_hash}
        )
        
        if existing_note:
            logger.info("v2/ingest: Duplicate detected", note_id=existing_note[0]["id"])
            # Return successfully but point to existing note
            return IngestResponse(
                note_id=str(existing_note[0]["id"]),
                status="completed",
                status_reason="completed_duplicate",
                next_action="none",
                thread_id="duplicate_skipped",
                error="Duplicate content detected. Note already exists."
            )

        # Process Images first (if any)
        final_content = request.content
        if request.images:
            storage = get_storage_service()
            logger.info("v2/ingest: Processing images", count=len(request.images))
            
            for filename, b64_data in request.images.items():
                try:
                    # Decode base64
                    # Handle data:image/png;base64, prefix if present
                    if "," in b64_data:
                        b64_data = b64_data.split(",")[1]
                        
                    file_data = base64.b64decode(b64_data)
                    
                    # Determine content type
                    content_type = "image/png"
                    if filename.lower().endswith((".jpg", ".jpeg")):
                        content_type = "image/jpeg"
                        
                    # Upload
                    url = await storage.upload_file(
                        file_data, 
                        filename, 
                        content_type, 
                        user_id
                    )
                    
                    # Replace in markdown content
                    # We replace the filename with the full URL
                    # This handles ![alt](filename) -> ![alt](url)
                    final_content = final_content.replace(filename, url)
                    
                except Exception as e:
                    logger.warning("v2/ingest: Failed to upload image", filename=filename, error=str(e))

        # Wrap in shield to ensure ingestion completes even if client disconnects
        result = await asyncio.shield(run_ingestion(
            content=final_content,
            title=request.title,
            user_id=user_id,
            skip_review=request.skip_review,
            content_hash=content_hash, # Pass hash to save it
            resource_type=request.resource_type,  # Pass through (e.g. "book")
        ))
        
        status = result.get("status", "completed")
        
        if status == "awaiting_review":
            logger.info(
                "v2/ingest: Paused for user review",
                thread_id=result.get("thread_id"),
                num_concepts=len(result.get("concepts", [])),
            )
        elif result.get("error"):
            logger.warning(
                "v2/ingest: Completed with error",
                error=result["error"],
            )
        else:
            logger.info(
                "v2/ingest: Success",
                note_id=result.get("note_id"),
                num_concepts=len(result.get("concept_ids", [])),
                num_flashcards=len(result.get("flashcard_ids", [])),
            )
        
        if status == "completed":
            await _schedule_community_recompute(user_id, result.get("note_id"))
            await _enqueue_note_ingested_event(
                user_id,
                result.get("note_id"),
                request.title or result.get("note_title") or "",
                result.get("concepts", []) or [],
            )
        await _schedule_reembed_if_needed(result, user_id)

        if status == "completed" or (status == "awaiting_review" and result.get("note_id")):
             # Trigger durable Lazy Quiz Scanner
             note_id = result.get("note_id")
             if note_id:
                 await _schedule_quiz_scan(user_id, note_id, request.content)
        
        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=result.get("concepts", []),
            concept_ids=[c for c in result.get("concept_ids", []) if c is not None],
            flashcard_ids=result.get("flashcard_ids", []),
            synthesis_decisions=result.get("synthesis_decisions"),
            processing_metadata=result.get("processing_metadata"),
            status=status,
            status_reason=result.get("status_reason", "completed" if status == "completed" else status),
            next_action=result.get("next_action", "approve_required" if status == "awaiting_review" else "none"),
            thread_id=result.get("thread_id", ""),
            error=result.get("error"),
            warnings=result.get("warnings", []),
        )
        
    except Exception as e:
        logger.error("v2/ingest: Fatal error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/processed-zip", response_model=ProcessedZipIngestStartResponse)
async def ingest_processed_zip(
    file: UploadFile = File(...),
    skip_review: bool = Form(True),
    title: Optional[str] = Form(None),
    resource_type: Optional[str] = Form("book"),
    current_user: dict = Depends(require_quota("ingest")),
):
    """
    Queue a processed-book ZIP ingestion and run it in the background.

    Expected ZIP contents:
    - One markdown file (prefers full_text.md if present)
    - Optional images referenced from markdown
    """
    user_id = str(current_user["id"])
    filename = file.filename or "processed_book.zip"

    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are supported for processed-book ingestion")

    try:
        zip_bytes = await file.read()
        if not zip_bytes:
            raise HTTPException(status_code=400, detail="Uploaded zip file is empty")

        thread_id = str(uuid.uuid4())
        _zip_ingest_owners[thread_id] = user_id
        _zip_ingest_events[thread_id] = []
        _zip_ingest_results.pop(thread_id, None)
        _append_zip_event(
            thread_id,
            "info",
            "Ingestion queued",
            filename=filename,
            skip_review=skip_review,
            resource_type=resource_type or "book",
        )

        asyncio.create_task(
            _ingest_processed_zip_background(
                thread_id=thread_id,
                user_id=user_id,
                zip_bytes=zip_bytes,
                filename=filename,
                title=title,
                skip_review=skip_review,
                resource_type=resource_type,
            )
        )

        return ProcessedZipIngestStartResponse(
            status="processing",
            status_reason="queued",
            next_action="none",
            thread_id=thread_id,
            message="Processed zip accepted. Ingestion is running in the background.",
        )
    except HTTPException:
        raise
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file")
    except Exception as e:
        logger.error("v2/ingest/processed-zip: Failed to queue", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# URL Ingestion (Articles/Substack)
# ============================================================================

from backend.graphs.article_graph import process_article_url

class IngestUrlRequest(BaseModel):
    url: str

@router.post("/ingest/url", response_model=IngestResponse)
async def ingest_url(
    request: IngestUrlRequest,
    current_user: dict = Depends(require_quota("ingest")),
):
    """
    Ingest an article from a URL (e.g. Substack, Medium, Blog).
    
    1. Fetches HTML.
    2. Parses Title/Author/Content using Gemini.
    3. Ingests into Knowledge Graph (auto-approved).
    """
    user_id = str(current_user["id"])
    logger.info("v2/ingest/url: Starting", url=request.url)
    
    try:
        # Run Article Graph
        result = await process_article_url(request.url, user_id=user_id)
        
        if result.get("error"):
             raise HTTPException(status_code=400, detail=result["error"])
             
        ingestion_res = result.get("ingestion_result", {})
        await _schedule_reembed_if_needed(ingestion_res, user_id)
        if ingestion_res.get("note_id") and ingestion_res.get("status", "completed") == "completed":
            await _enqueue_note_ingested_event(
                user_id,
                ingestion_res.get("note_id"),
                result.get("title") or ingestion_res.get("note_title") or request.url,
                ingestion_res.get("concepts", []) or [],
            )

        # Merge structured metadata
        return IngestResponse(
            note_id=ingestion_res.get("note_id"),
            concepts=ingestion_res.get("concepts", []),
            concept_ids=ingestion_res.get("concept_ids", []),
            flashcard_ids=ingestion_res.get("flashcard_ids", []),
            processing_metadata=ingestion_res.get("processing_metadata"),
            status="completed",
            status_reason=ingestion_res.get("status_reason", "completed"),
            next_action=ingestion_res.get("next_action", "none"),
            thread_id=ingestion_res.get("thread_id", ""),
            error=ingestion_res.get("error"),
            warnings=ingestion_res.get("warnings", []),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("v2/ingest/url: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/{thread_id}/status", response_model=StatusResponse)
async def get_status(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get the current status of an ingestion workflow.
    
    Use this to check if a workflow is:
    - processing: Still running
    - awaiting_review: Paused for human approval
    - completed: Finished successfully
    - error: Failed with error
    - not_found: Thread ID not found
    """
    try:
        user_id = str(current_user["id"])
        result = await get_ingestion_status(thread_id, user_id=user_id)
        
        return StatusResponse(
            status=result.get("status", "not_found"),
            status_reason=result.get("status_reason", result.get("status", "not_found")),
            next_action=result.get("next_action", "none"),
            thread_id=thread_id,
            stage=result.get("stage"),
            progress=result.get("progress"),
            note_id=result.get("note_id"),
            next_step=result.get("next_step"),
            concepts=result.get("concepts", []),
            synthesis_decisions=result.get("synthesis_decisions"),
            error=result.get("error"),
        )
        
    except Exception as e:
        logger.error("v2/ingest/status: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/{thread_id}/events", response_model=IngestEventsResponse)
async def get_processed_zip_events(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Return structured ingestion events and current workflow status.

    This gives the Plus page a clean way to show "live logs" without
    exposing raw infrastructure logs.
    """
    user_id = str(current_user["id"])
    owner = _zip_ingest_owners.get(thread_id)
    if owner and owner != user_id:
        raise HTTPException(status_code=404, detail="Thread not found")

    status_payload = await get_ingestion_status(thread_id, user_id=user_id)
    result_payload = _zip_ingest_results.get(thread_id)

    status = status_payload.get("status", "processing")
    status_reason = status_payload.get("status_reason", "processing")
    next_action = status_payload.get("next_action", "none")
    stage = status_payload.get("stage")
    progress = status_payload.get("progress")
    note_id = status_payload.get("note_id")

    # If state is unavailable but we have a completed/error background result,
    # use that as authoritative status.
    if status == "not_found" and result_payload:
        status = result_payload.get("status", "error")
        status_reason = result_payload.get("status_reason", status)
        next_action = result_payload.get("next_action", "none")
        stage = "completed" if status == "completed" else "error"
        note_id = result_payload.get("note_id")
        progress = progress or {
            "current_node": None,
            "completed_nodes": [],
            "failed_batches": 0,
            "concepts_extracted": len(result_payload.get("concepts", []) or []),
        }

    return IngestEventsResponse(
        thread_id=thread_id,
        status=status,
        status_reason=status_reason,
        next_action=next_action,
        stage=stage,
        progress=progress,
        note_id=note_id,
        events=_zip_ingest_events.get(thread_id, []),
        result=result_payload,
    )


@router.post("/ingest/{thread_id}/approve", response_model=IngestResponse)
async def approve_and_resume(
    thread_id: str,
    request: ResumeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Resume ingestion after user has reviewed concepts.
    
    Human-in-the-Loop Flow:
    1. POST /api/v2/ingest -> status="awaiting_review", get thread_id
    2. User reviews concepts and synthesis_decisions
    3. POST /api/v2/ingest/{thread_id}/approve with approved_concepts
    4. Workflow resumes and creates concepts in Neo4j
    
    If cancelled=True, the workflow ends without creating concepts.
    """
    logger.info(
        "v2/ingest/approve: Resuming workflow",
        thread_id=thread_id,
        num_approved=len(request.approved_concepts),
        cancelled=request.cancelled,
    )
    
    try:
        user_id = str(current_user["id"])
        result = await resume_ingestion(
            thread_id=thread_id,
            user_approved_concepts=request.approved_concepts,
            user_cancelled=request.cancelled,
            user_id=user_id,
        )
        
        status = result.get("status", "completed")
        await _schedule_reembed_if_needed(result, user_id)
        if status == "completed" and result.get("note_id"):
            await _enqueue_note_ingested_event(
                user_id,
                result.get("note_id"),
                result.get("note_title") or "",
                request.approved_concepts,
            )

        if status == "cancelled":
            logger.info("v2/ingest/approve: Workflow cancelled by user")
        else:
            logger.info(
                "v2/ingest/approve: Completed",
                note_id=result.get("note_id"),
                num_concepts=len(result.get("concept_ids", [])),
            )
        
        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=[],  # Concepts already returned in initial response
            concept_ids=result.get("concept_ids", []),
            flashcard_ids=result.get("flashcard_ids", []),
            synthesis_decisions=None,
            status=status,
            status_reason=result.get("status_reason", "completed" if status == "completed" else status),
            next_action=result.get("next_action", "none"),
            thread_id=thread_id,
            error=result.get("error"),
            warnings=result.get("warnings", []),
        )
        
    except Exception as e:
        logger.error("v2/ingest/approve: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# YouTube Link Storage (no processing, just stored and linked)
# ============================================================================


class IngestYoutubeRequest(BaseModel):
    url: str
    title: Optional[str] = None


@router.post("/ingest/youtube")
async def ingest_youtube_link(
    request: IngestYoutubeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Store a YouTube link as a note resource (no processing).

    YouTube links are just stored and linked — not processed.
    """
    from backend.db.postgres_client import get_postgres_client

    user_id = str(current_user["id"])
    note_id = str(uuid.uuid4())
    title = request.title or f"YouTube: {request.url}"

    try:
        pg_client = await get_postgres_client()
        await pg_client.execute_update(
            """
            INSERT INTO notes (id, user_id, title, content_text, resource_type, source_url, created_at, updated_at)
            VALUES (:id, :user_id, :title, :content_text, :resource_type, :source_url, :created_at, :created_at)
            """,
            {
                "id": note_id,
                "user_id": user_id,
                "title": title,
                "content_text": f"YouTube link: {request.url}",
                "resource_type": "youtube",
                "source_url": request.url,
                "created_at": datetime.now(timezone.utc),
            },
        )

        logger.info("v2/ingest/youtube: Stored", note_id=note_id, url=request.url)

        return {
            "note_id": note_id,
            "status": "stored",
            "resource_type": "youtube",
            "url": request.url,
        }
    except Exception as e:
        logger.error("v2/ingest/youtube: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LLM Chat Transcript Ingestion
# ============================================================================


class IngestChatTranscriptRequest(BaseModel):
    content: str  # Raw pasted transcript (Human: ... AI: ...)
    title: Optional[str] = None


@router.post("/ingest/chat-transcript", response_model=IngestResponse)
async def ingest_chat_transcript(
    request: IngestChatTranscriptRequest,
    current_user: dict = Depends(require_quota("ingest")),
):
    """
    Ingest an LLM chat transcript.

    Processes human + AI messages, consolidates them, and stores
    them as a note in the knowledge graph.
    """
    user_id = str(current_user["id"])
    logger.info("v2/ingest/chat-transcript: Starting", content_length=len(request.content))

    try:
        # Consolidate the transcript into a structured note
        from backend.config.llm import get_chat_model
        llm = get_chat_model(temperature=0.1)

        consolidation_prompt = f"""Consolidate this LLM chat transcript into a clean knowledge note.

Transcript:
{request.content[:5000]}

Instructions:
1. Extract the KEY INFORMATION discussed (facts, concepts, explanations)
2. Remove conversational filler ("sure!", "great question", etc.)
3. Organize into clear sections with markdown headers
4. Preserve code blocks and technical details
5. Note which points were questions vs answers

Return the consolidated note as clean markdown."""

        response = await llm.ainvoke(consolidation_prompt)
        consolidated = response.text.strip()

        # Now run through standard ingestion with consolidated content
        result = await asyncio.shield(run_ingestion(
            content=consolidated,
            title=request.title or "Chat Transcript Notes",
            user_id=user_id,
            skip_review=True,
        ))

        # Trigger Lazy Quiz Scanner durably on agent_jobs
        if result.get("note_id"):
            await _schedule_quiz_scan(user_id, result.get("note_id"), consolidated)

        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=result.get("concepts", []),
            concept_ids=result.get("concept_ids", []),
            flashcard_ids=result.get("flashcard_ids", []),
            processing_metadata=result.get("processing_metadata"),
            status=result.get("status", "completed"),
            status_reason=result.get("status_reason", "completed"),
            next_action=result.get("next_action", "none"),
            thread_id=result.get("thread_id", ""),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error("v2/ingest/chat-transcript: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check for the V2 API."""
    from backend.graphs.checkpointer import checkpointer_status

    cp = checkpointer_status()
    durable = cp.get("backend") == "postgres" and cp.get("ready", False)
    return {
        "status": "healthy",
        "version": "2.2",
        "workflow": "langgraph",
        "checkpointer_mode": cp.get("backend"),
        "checkpointer_ready": cp.get("ready", False),
        "durable_thread_persistence": durable,
        "features": [
            "conditional_edges",
            "human_in_the_loop",
            *(["postgres_checkpointer"] if durable else []),
            "processed_zip_background_ingestion",
            "youtube_links",
            "chat_transcript_ingestion",
        ],
    }
