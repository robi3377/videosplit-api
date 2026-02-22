"""
Cloudflare R2 storage service (S3-compatible).
All boto3 calls are dispatched to a thread pool via asyncio.to_thread()
so they don't block the async event loop.

Falls back gracefully when R2 is not configured (r2_enabled = False).
"""
import asyncio
import io
import logging
from typing import List

import boto3
from botocore.config import Config

from app.saas_layer.core.config import settings

logger = logging.getLogger(__name__)


def _make_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


async def upload_file(local_path: str, key: str) -> None:
    """Upload a local file to R2 under the given key."""
    def _upload():
        _make_client().upload_file(local_path, settings.R2_BUCKET_NAME, key)

    await asyncio.to_thread(_upload)
    logger.debug("R2 uploaded: %s", key)


async def generate_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned GET URL for an R2 object (default 1-hour TTL)."""
    def _generate():
        return _make_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_in,
        )

    return await asyncio.to_thread(_generate)


async def generate_presigned_put_url(key: str, expires_in: int = 3600) -> str:
    """
    Generate a presigned PUT URL for direct browser-to-R2 uploads.
    The browser sends: PUT <url> with the raw file body.
    Requires CORS to be configured on the R2 bucket to allow PUT from browser origins.
    """
    def _generate():
        return _make_client().generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": key},
            ExpiresIn=expires_in,
        )

    return await asyncio.to_thread(_generate)


async def download_to_file(key: str, local_path: str) -> None:
    """
    Stream an R2 object directly to a local file path.
    More memory-efficient than download_to_memory() for large files
    because boto3 downloads in chunks without buffering everything at once.
    """
    def _download():
        _make_client().download_file(settings.R2_BUCKET_NAME, key, local_path)

    await asyncio.to_thread(_download)
    logger.debug("R2 downloaded %s → %s", key, local_path)


async def download_to_memory(key: str) -> bytes:
    """Download an R2 object entirely into memory and return raw bytes."""
    def _download():
        buf = io.BytesIO()
        _make_client().download_fileobj(settings.R2_BUCKET_NAME, key, buf)
        buf.seek(0)
        return buf.read()

    return await asyncio.to_thread(_download)


async def list_keys(prefix: str) -> List[str]:
    """Return all object keys under a given prefix (paginated)."""
    def _list():
        client = _make_client()
        keys: List[str] = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.R2_BUCKET_NAME, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    return await asyncio.to_thread(_list)


async def object_exists(key: str) -> bool:
    """Return True if the object exists in R2."""
    def _check():
        try:
            _make_client().head_object(Bucket=settings.R2_BUCKET_NAME, Key=key)
            return True
        except Exception:
            return False

    return await asyncio.to_thread(_check)


async def delete_prefix(prefix: str) -> int:
    """Delete all objects under a prefix. Returns the number of objects deleted."""
    def _delete():
        client = _make_client()
        deleted = 0
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=settings.R2_BUCKET_NAME, Prefix=prefix):
            objects = page.get("Contents", [])
            if objects:
                client.delete_objects(
                    Bucket=settings.R2_BUCKET_NAME,
                    Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
                )
                deleted += len(objects)
        return deleted

    count = await asyncio.to_thread(_delete)
    if count:
        logger.info("R2 deleted %d objects under prefix %s", count, prefix)
    return count
