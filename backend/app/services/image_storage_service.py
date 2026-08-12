"""Hardened S3/MinIO storage functions for the Universal Image Processing Pipeline --
deliberately NOT reusing app/services/storage_service.py's client, which is tuned for a
best-effort, optional attachment (invoice PDFs): a 2-second connect timeout and zero
retries, wrapped in try/except at its one call site, so a MinIO blip silently no-ops
instead of failing the customer's order.

An image upload is the opposite: the whole point of POST /images is "the file is now
durably stored," so a storage failure must be a real, surfaced error -- never a silent
no-op that leaves an Image row stuck at status="processing" forever. Callers (the images
router for the original, app/services/image_pipeline.py for variants) let
ImageStorageError propagate; nothing here swallows it.
"""

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings


class ImageStorageError(RuntimeError):
    """A genuine, unrecovered storage failure -- callers must surface this (e.g. as a 502
    from the upload endpoint, or a status="failed" Image row from the processing task),
    never catch-and-ignore it."""


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            # More patient than storage_service.py's best-effort client: a real failure
            # here is customer-facing, so it's worth real retries/timeouts before giving up.
            config=Config(signature_version="s3v4", connect_timeout=5, read_timeout=20, retries={"max_attempts": 3}),
        )
    return _client


def upload_bytes(key: str, content: bytes, content_type: str) -> None:
    try:
        _get_client().put_object(Bucket=settings.S3_BUCKET, Key=key, Body=content, ContentType=content_type)
    except (BotoCoreError, ClientError) as exc:
        raise ImageStorageError(f"Failed to upload {key}") from exc


def download_bytes(key: str) -> bytes:
    try:
        response = _get_client().get_object(Bucket=settings.S3_BUCKET, Key=key)
        return response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise ImageStorageError(f"Failed to download {key}") from exc


def public_url(key: str) -> str:
    """No CDN in front yet (explicit follow-up, not this task) -- a long-lived presigned
    URL is the best available option meanwhile. Callers should re-fetch from GET
    /images/{id} rather than caching this indefinitely.
    """
    return _get_client().generate_presigned_url(
        "get_object", Params={"Bucket": settings.S3_BUCKET, "Key": key}, ExpiresIn=30 * 24 * 3600
    )
