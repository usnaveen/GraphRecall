"""S3-compatible storage service for file uploads."""

import os
import time
from typing import Optional

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import ClientError

logger = structlog.get_logger()

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class StorageService:
    """S3-compatible file storage (works with AWS S3, Supabase Storage, MinIO, etc.)."""

    def __init__(self) -> None:
        self.bucket_name = os.environ.get("S3_BUCKET_NAME", "graphrecall-uploads")
        self.public_url_base = os.environ.get("S3_PUBLIC_URL_BASE", "")
        self.region = os.environ.get("S3_REGION", "us-east-1")
        endpoint_url = os.environ.get("S3_ENDPOINT_URL") or None

        self.s3_client = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=endpoint_url,
            aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY"),
            config=Config(signature_version="s3v4"),
        )

    def validate_file(self, content_type: str | None, size: int) -> tuple[bool, str]:
        """Validate file type and size."""
        if not content_type or content_type not in ALLOWED_CONTENT_TYPES:
            return False, f"File type '{content_type}' not allowed. Accepted: {', '.join(ALLOWED_CONTENT_TYPES)}"
        if size > MAX_FILE_SIZE_BYTES:
            return False, f"File too large ({size} bytes). Maximum: {MAX_FILE_SIZE_BYTES} bytes ({MAX_FILE_SIZE_BYTES // 1024 // 1024} MB)"
        if size == 0:
            return False, "File is empty"
        return True, ""

    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        user_id: str,
    ) -> str:
        """Upload file to S3 and return the public URL."""
        # Sanitize filename
        safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_").strip()
        if not safe_name:
            safe_name = "upload"

        key = f"uploads/{user_id}/{int(time.time())}_{safe_name}"

        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_data,
            ContentType=content_type,
        )

        logger.info("Storage: File uploaded", key=key, size=len(file_data), content_type=content_type)

        # Build public URL
        if self.public_url_base:
            return f"{self.public_url_base.rstrip('/')}/{key}"
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}"

    async def delete_file(self, file_url: str) -> bool:
        """Delete file from S3 by its public URL. Returns True on success."""
        key = self._url_to_key(file_url)
        if not key:
            logger.warning("Storage: Could not extract key from URL", file_url=file_url)
            return False

        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)
            logger.info("Storage: File deleted", key=key)
            return True
        except ClientError as e:
            logger.error("Storage: Failed to delete file", key=key, error=str(e))
            return False

    def _url_to_key(self, url: str) -> Optional[str]:
        """Extract S3 key from a public URL."""
        if self.public_url_base and url.startswith(self.public_url_base):
            base = self.public_url_base.rstrip("/")
            return url[len(base) + 1 :]

        # Standard AWS S3 URL patterns
        for prefix in [
            f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/",
            f"https://{self.bucket_name}.s3.amazonaws.com/",
            f"https://s3.{self.region}.amazonaws.com/{self.bucket_name}/",
        ]:
            if url.startswith(prefix):
                return url[len(prefix) :]

        return None


_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """Get or create the singleton storage service."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
