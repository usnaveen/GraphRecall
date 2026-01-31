"""Uploads Router - User Content Upload Endpoints."""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel

from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import FeedItemType, UserUpload, UserUploadCreate
from backend.services.storage_service import get_storage_service

logger = structlog.get_logger()

router = APIRouter(prefix="/api/uploads", tags=["User Uploads"])


class UploadResponse(BaseModel):
    """Response for upload operations."""

    id: str
    file_url: str
    thumbnail_url: Optional[str] = None
    status: str
    message: str


class LinkConceptsRequest(BaseModel):
    """Request to link concepts to an upload."""

    concept_ids: list[str]


@router.post("", response_model=UploadResponse)
async def create_upload(
    user_id: str = Form(default="00000000-0000-0000-0000-000000000001"),
    upload_type: str = Form(default="screenshot"),
    title: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    file_url: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    linked_concepts: Optional[str] = Form(default=None),  # Comma-separated IDs
):
    """
    Create a new user upload record.

    Accepts either:
    - A `file` (multipart upload) which is uploaded to S3
    - A `file_url` string pointing to an existing file

    Upload types: screenshot, infographic, diagram
    """
    try:
        # Resolve file URL: either upload to S3 or use provided URL
        resolved_url: str
        if file is not None:
            storage = get_storage_service()
            file_data = await file.read()
            is_valid, error_msg = storage.validate_file(file.content_type, len(file_data))
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_msg)
            resolved_url = await storage.upload_file(
                file_data, file.filename or "upload", file.content_type or "application/octet-stream", user_id
            )
        elif file_url:
            resolved_url = file_url
        else:
            raise HTTPException(status_code=400, detail="Either 'file' or 'file_url' must be provided")

        pg_client = await get_postgres_client()

        # Parse linked concepts
        concept_list = []
        if linked_concepts:
            concept_list = [c.strip() for c in linked_concepts.split(",") if c.strip()]

        # Validate upload type
        try:
            FeedItemType(upload_type)
        except ValueError:
            upload_type = "screenshot"

        # Insert upload record
        upload_id = await pg_client.execute_insert(
            """
            INSERT INTO user_uploads
                (user_id, upload_type, file_url, title, description, linked_concepts)
            VALUES
                (:user_id, :upload_type, :file_url, :title, :description, :linked_concepts)
            RETURNING id
            """,
            {
                "user_id": user_id,
                "upload_type": upload_type,
                "file_url": resolved_url,
                "title": title,
                "description": description,
                "linked_concepts": concept_list,
            },
        )

        logger.info(
            "Uploads: Created upload",
            upload_id=upload_id,
            upload_type=upload_type,
            has_file=file is not None,
        )

        return UploadResponse(
            id=str(upload_id),
            file_url=resolved_url,
            status="created",
            message="Upload created successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Uploads: Error creating upload", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
async def list_uploads(
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
    upload_type: Optional[str] = Query(default=None),
    limit: int = Query(default=20, le=50),
    offset: int = Query(default=0, ge=0),
):
    """
    List user uploads.

    Can filter by upload_type: screenshot, infographic, diagram
    """
    try:
        pg_client = await get_postgres_client()

        # Build query
        where_clauses = ["user_id = :user_id"]
        params = {"user_id": user_id, "limit": limit, "offset": offset}

        if upload_type:
            where_clauses.append("upload_type = :upload_type")
            params["upload_type"] = upload_type

        where_clause = " AND ".join(where_clauses)

        result = await pg_client.execute_query(
            f"""
            SELECT
                id, user_id, upload_type, file_url, thumbnail_url,
                title, description, linked_concepts, created_at,
                show_count
            FROM user_uploads
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

        # Get total count
        count_result = await pg_client.execute_query(
            f"""
            SELECT COUNT(*) as count
            FROM user_uploads
            WHERE {where_clause}
            """,
            params,
        )

        total = count_result[0]["count"] if count_result else 0

        return {
            "uploads": result,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error("Uploads: Error listing uploads", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{upload_id}")
async def get_upload(upload_id: str):
    """Get a specific upload by ID."""
    try:
        pg_client = await get_postgres_client()

        result = await pg_client.execute_query(
            """
            SELECT
                id, user_id, upload_type, file_url, thumbnail_url,
                title, description, linked_concepts, ocr_text,
                created_at, last_shown_at, show_count
            FROM user_uploads
            WHERE id = :upload_id
            """,
            {"upload_id": upload_id},
        )

        if not result:
            raise HTTPException(status_code=404, detail="Upload not found")

        return result[0]

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Uploads: Error getting upload", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{upload_id}")
async def update_upload(
    upload_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
):
    """Update upload metadata."""
    try:
        pg_client = await get_postgres_client()

        # Build update
        updates = []
        params = {"upload_id": upload_id}

        if title is not None:
            updates.append("title = :title")
            params["title"] = title

        if description is not None:
            updates.append("description = :description")
            params["description"] = description

        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")

        update_clause = ", ".join(updates)

        await pg_client.execute_insert(
            f"""
            UPDATE user_uploads
            SET {update_clause}
            WHERE id = :upload_id
            """,
            params,
        )

        return {"status": "updated", "upload_id": upload_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Uploads: Error updating upload", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{upload_id}/link-concepts")
async def link_concepts_to_upload(
    upload_id: str,
    request: LinkConceptsRequest,
):
    """
    Link concepts to an upload.

    This connects the upload to specific concepts in the knowledge graph,
    allowing it to appear in the feed when those concepts are due for review.
    """
    try:
        pg_client = await get_postgres_client()

        # Get current linked concepts
        result = await pg_client.execute_query(
            """
            SELECT linked_concepts
            FROM user_uploads
            WHERE id = :upload_id
            """,
            {"upload_id": upload_id},
        )

        if not result:
            raise HTTPException(status_code=404, detail="Upload not found")

        current = result[0].get("linked_concepts") or []

        # Merge with new concepts
        updated = list(set(current + request.concept_ids))

        # Update
        await pg_client.execute_insert(
            """
            UPDATE user_uploads
            SET linked_concepts = :concepts
            WHERE id = :upload_id
            """,
            {"upload_id": upload_id, "concepts": updated},
        )

        return {
            "status": "linked",
            "upload_id": upload_id,
            "linked_concepts": updated,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Uploads: Error linking concepts", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{upload_id}/link-concepts/{concept_id}")
async def unlink_concept_from_upload(
    upload_id: str,
    concept_id: str,
):
    """Remove a concept link from an upload."""
    try:
        pg_client = await get_postgres_client()

        # Get current linked concepts
        result = await pg_client.execute_query(
            """
            SELECT linked_concepts
            FROM user_uploads
            WHERE id = :upload_id
            """,
            {"upload_id": upload_id},
        )

        if not result:
            raise HTTPException(status_code=404, detail="Upload not found")

        current = result[0].get("linked_concepts") or []

        # Remove the concept
        if concept_id in current:
            current.remove(concept_id)

        # Update
        await pg_client.execute_insert(
            """
            UPDATE user_uploads
            SET linked_concepts = :concepts
            WHERE id = :upload_id
            """,
            {"upload_id": upload_id, "concepts": current},
        )

        return {
            "status": "unlinked",
            "upload_id": upload_id,
            "linked_concepts": current,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Uploads: Error unlinking concept", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{upload_id}")
async def delete_upload(upload_id: str):
    """
    Delete an upload record and its file from storage.
    """
    try:
        pg_client = await get_postgres_client()

        # Get the upload record to find the file URL
        result = await pg_client.execute_query(
            "SELECT id, file_url FROM user_uploads WHERE id = :upload_id",
            {"upload_id": upload_id},
        )

        if not result:
            raise HTTPException(status_code=404, detail="Upload not found")

        file_url = result[0].get("file_url")

        # Delete from S3 (best-effort)
        if file_url:
            try:
                storage = get_storage_service()
                await storage.delete_file(file_url)
            except Exception as e:
                logger.warning(
                    "Uploads: Failed to delete file from storage",
                    file_url=file_url,
                    error=str(e),
                )

        # Delete database record
        await pg_client.execute_insert(
            "DELETE FROM user_uploads WHERE id = :upload_id",
            {"upload_id": upload_id},
        )

        logger.info("Uploads: Deleted upload", upload_id=upload_id)

        return {
            "status": "deleted",
            "upload_id": upload_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Uploads: Error deleting upload", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
