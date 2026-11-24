"""S3 / Cloudflare R2 object storage service with dev local fallback."""

from __future__ import annotations

import asyncio
import posixpath
import shutil
import os
from pathlib import Path
import time
from typing import Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
import structlog

logger = structlog.get_logger()

ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}
ALLOWED_CONTENT_TYPES = ALLOWED_IMAGE_TYPES | {"application/pdf"}

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB images
MAX_PDF_SIZE_BYTES = 50 * 1024 * 1024   # 50 MB PDFs


def _is_production() -> bool:
    return os.getenv("ENVIRONMENT", "development") == "production"


class StorageService:
    """S3-compatible object storage (Cloudflare R2, AWS S3, MinIO) with async thread offload."""

    def __init__(self) -> None:
        r2_account = os.environ.get("R2_ACCOUNT_ID")
        endpoint_url = (
            os.environ.get("R2_ENDPOINT_URL")
            or os.environ.get("S3_ENDPOINT_URL")
            or (f"https://{r2_account}.r2.cloudflarestorage.com" if r2_account else None)
        )
        self.endpoint_url = endpoint_url.rstrip("/") if endpoint_url else None
        self.bucket_name = (
            os.environ.get("R2_BUCKET_NAME")
            or os.environ.get("S3_BUCKET_NAME")
            or "graphrecall-uploads"
        )
        self.public_url_base = (
            os.environ.get("R2_PUBLIC_URL_BASE")
            or os.environ.get("S3_PUBLIC_URL_BASE")
            or ""
        ).rstrip("/")
        default_region = (
            "auto"
            if self.endpoint_url and "r2.cloudflarestorage.com" in self.endpoint_url
            else "us-east-1"
        )
        self.region = os.environ.get("S3_REGION") or default_region
        self._access_key = (
            os.environ.get("R2_ACCESS_KEY_ID") or os.environ.get("S3_ACCESS_KEY_ID")
        )
        self._secret_key = (
            os.environ.get("R2_SECRET_ACCESS_KEY") or os.environ.get("S3_SECRET_ACCESS_KEY")
        )
        self.local_fallback_dir = Path(
            os.environ.get("LOCAL_UPLOAD_DIR", "/tmp/graphrecall_uploads")
        )

        self.s3_client = (
            boto3.client(
                "s3",
                region_name=self.region,
                endpoint_url=self.endpoint_url,
                aws_access_key_id=self._access_key,
                aws_secret_access_key=self._secret_key,
                config=Config(signature_version="s3v4"),
            )
            if self.is_configured()
            else None
        )

    def is_configured(self) -> bool:
        """Return True when object-storage credentials and bucket are configured."""
        return bool(self._access_key and self._secret_key and self.bucket_name)

    def validate_file(self, content_type: str | None, size: int) -> tuple[bool, str]:
        """Validate MIME type and size (10 MB images, 50 MB PDFs)."""
        if not content_type or content_type not in ALLOWED_CONTENT_TYPES:
            return (
                False,
                f"File type '{content_type}' not allowed. Accepted: {', '.join(sorted(ALLOWED_CONTENT_TYPES))}",
            )
        max_bytes = MAX_PDF_SIZE_BYTES if content_type == "application/pdf" else MAX_FILE_SIZE_BYTES
        if size > max_bytes:
            return (
                False,
                f"File too large ({size} bytes). Maximum: {max_bytes} bytes ({max_bytes // 1024 // 1024} MB)",
            )
        if size <= 0:
            return False, "File is empty"
        return True, ""

    @staticmethod
    def _build_key(filename: str, user_id: str) -> str:
        safe_name = "".join(c for c in filename if c.isalnum() or c in ".-_").strip()
        if not safe_name:
            safe_name = "upload"
        return f"uploads/{user_id}/{int(time.time())}_{safe_name}"

    def _public_url_for_key(self, key: str) -> str:
        if self.public_url_base:
            return f"{self.public_url_base}/{key}"
        if self.endpoint_url:
            return f"{self.endpoint_url}/{self.bucket_name}/{key}"
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{key}"

    async def upload_file(
        self,
        file_data: bytes,
        filename: str,
        content_type: str,
        user_id: str,
    ) -> str:
        """Upload file to R2/S3 (async thread offload), with dev local fallback."""
        key = self._build_key(filename, user_id)

        if not self.is_configured():
            if _is_production():
                raise RuntimeError(
                    "Object storage credentials (R2/S3) must be configured when ENVIRONMENT=production"
                )
            dest = self.local_fallback_dir / key

            def _write_local() -> str:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(file_data)
                return dest.resolve().as_uri()

            url = await asyncio.to_thread(_write_local)
            logger.info("Storage: File stored in dev fallback", key=key, size=len(file_data))
            return url

        await asyncio.to_thread(
            self.s3_client.put_object,
            Bucket=self.bucket_name,
            Key=key,
            Body=file_data,
            ContentType=content_type,
        )

        logger.info("Storage: File uploaded", key=key, size=len(file_data), content_type=content_type)
        return self._public_url_for_key(key)

    @staticmethod
    def owner_prefix(owner_id: str) -> str:
        return f"uploads/{owner_id}/"

    def owned_key(self, file_url: str, owner_id: str) -> Optional[str]:
        """The object key for `file_url` if it is one of `owner_id`'s objects, else None.

        Every object we write lives under uploads/{user_id}/ (_build_key). A URL that maps to any
        other key, or that uses `..` to climb out of the prefix, is not this user's to delete.
        """
        key = self._url_to_key(file_url)
        if not key or not owner_id:
            return None
        if posixpath.normpath(key) != key or "/../" in f"/{key}/":
            return None
        return key if key.startswith(self.owner_prefix(owner_id)) else None

    def is_other_users_object(self, file_url: str, owner_id: str) -> bool:
        """True when the URL points into our bucket but outside `owner_id`'s prefix."""
        return self._url_to_key(file_url) is not None and self.owned_key(file_url, owner_id) is None

    async def delete_file(self, file_url: str, *, owner_id: str) -> bool:
        """Delete one of `owner_id`'s files by URL. Refuses (returns False) for anyone else's object."""
        if file_url.startswith("file://") and not _is_production():
            owner_root = (self.local_fallback_dir / self.owner_prefix(owner_id)).resolve()
            target = Path(file_url[len("file://") :]).resolve()
            if owner_root in target.parents:
                def _unlink_local() -> bool:
                    if target.exists():
                        target.unlink()
                        return True
                    return False

                return await asyncio.to_thread(_unlink_local)
            return False

        if self.s3_client is None:
            return False

        key = self.owned_key(file_url, owner_id)
        if not key:
            logger.warning("Storage: refusing to delete an object outside the owner's prefix")
            return False

        try:
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.bucket_name,
                Key=key,
            )
            logger.info("Storage: File deleted", key=key)
            return True
        except ClientError as e:
            logger.error("Storage: Failed to delete file", key=key, error=str(e))
            return False

    async def delete_user_prefix(self, owner_id: str) -> int:
        """Delete every object under uploads/{owner_id}/, including ones no row references any more
        (failed ingests, replaced files). Used by account deletion. Returns the number deleted."""
        if not owner_id:
            return 0
        prefix = self.owner_prefix(owner_id)
        if self.s3_client is None:
            if _is_production():
                return 0
            root = (self.local_fallback_dir / prefix).resolve()
            if not root.exists() or self.local_fallback_dir.resolve() not in root.parents:
                return 0

            def _rm_local() -> int:
                files = [p for p in root.rglob("*") if p.is_file()]
                shutil.rmtree(root, ignore_errors=True)
                return len(files)

            return await asyncio.to_thread(_rm_local)

        def _rm_s3() -> int:
            deleted = 0
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name, Prefix=prefix):
                keys = [{"Key": o["Key"]} for o in page.get("Contents", []) if o["Key"].startswith(prefix)]
                if keys:
                    self.s3_client.delete_objects(Bucket=self.bucket_name, Delete={"Objects": keys, "Quiet": True})
                    deleted += len(keys)
            return deleted

        n = await asyncio.to_thread(_rm_s3)
        logger.info("Storage: user prefix deleted", objects=n)
        return n

    def _url_to_key(self, url: str) -> Optional[str]:
        """Extract object key from an R2/S3 public or path-style URL."""
        if self.public_url_base and url.startswith(f"{self.public_url_base}/"):
            return url[len(self.public_url_base) + 1 :]

        prefixes = [
            f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/",
            f"https://{self.bucket_name}.s3.amazonaws.com/",
            f"https://s3.{self.region}.amazonaws.com/{self.bucket_name}/",
        ]
        if self.endpoint_url:
            prefixes.append(f"{self.endpoint_url}/{self.bucket_name}/")

        for prefix in prefixes:
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
