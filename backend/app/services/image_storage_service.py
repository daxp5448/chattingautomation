"""Storage functions for the Universal Image Processing Pipeline, backing onto either the
local filesystem (STORAGE_BACKEND="local", default -- no MinIO/S3 needed) or real S3/MinIO
(STORAGE_BACKEND="s3"). Deliberately NOT reusing app/services/storage_service.py's client,
which is tuned for a best-effort, optional attachment (invoice PDFs): a 2-second connect
timeout and zero retries, wrapped in try/except at its one call site, so a MinIO blip
silently no-ops instead of failing the customer's order.

An image upload is the opposite: the whole point of POST /images is "the file is now
durably stored," so a storage failure must be a real, surfaced error -- never a silent
no-op that leaves an Image row stuck at status="processing" forever. Callers (the images
router for the original, app/services/image_pipeline.py for variants) let
ImageStorageError propagate; nothing here swallows it. Both backends raise the same
ImageStorageError, so callers never need to know which one is active.
"""

from pathlib import Path

from app.core.config import settings


class ImageStorageError(RuntimeError):
    """A genuine, unrecovered storage failure -- callers must surface this (e.g. as a 502
    from the upload endpoint, or a status="failed" Image row from the processing task),
    never catch-and-ignore it."""


# --- local filesystem backend -------------------------------------------------------

def _local_path(key: str) -> Path:
    # `key` is always a server-generated path like "images/<uuid>/original.jpg" (see
    # images.py's upload_image) -- never raw user input, so no traversal risk from an
    # embedded "..", but resolve() + a root-containment check below is cheap insurance
    # against a future caller passing something less trusted.
    root = Path(settings.LOCAL_MEDIA_DIR).resolve()
    path = (root / key).resolve()
    if root not in path.parents and path != root:
        raise ImageStorageError(f"Refusing to store outside media root: {key}")
    return path


def _local_upload_bytes(key: str, content: bytes) -> None:
    path = _local_path(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    except OSError as exc:
        raise ImageStorageError(f"Failed to upload {key}") from exc


def _local_download_bytes(key: str) -> bytes:
    path = _local_path(key)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ImageStorageError(f"Failed to download {key}") from exc


def _local_public_url(key: str) -> str:
    # Rides the same /media/{key} passthrough route real S3 keys use (see
    # app/api/v1/routers/media.py) -- that route already calls download_bytes() below, so
    # it serves local-disk files transparently with zero route changes.
    return f"{settings.PUBLIC_API_BASE_URL}/media/{key}"


# --- S3/MinIO backend ------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        import boto3
        from botocore.client import Config

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


def _s3_upload_bytes(key: str, content: bytes, content_type: str) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        _get_client().put_object(Bucket=settings.S3_BUCKET, Key=key, Body=content, ContentType=content_type)
    except (BotoCoreError, ClientError) as exc:
        raise ImageStorageError(f"Failed to upload {key}") from exc


def _s3_download_bytes(key: str) -> bytes:
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        response = _get_client().get_object(Bucket=settings.S3_BUCKET, Key=key)
        return response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise ImageStorageError(f"Failed to download {key}") from exc


def _s3_public_url(key: str) -> str:
    """No CDN in front yet (explicit follow-up, not this task) -- a long-lived presigned
    URL is the best available option meanwhile. Callers should re-fetch from GET
    /images/{id} rather than caching this indefinitely.
    """
    return _get_client().generate_presigned_url(
        "get_object", Params={"Bucket": settings.S3_BUCKET, "Key": key}, ExpiresIn=30 * 24 * 3600
    )


# --- public entry points, dispatching on STORAGE_BACKEND -------------------------------

def upload_bytes(key: str, content: bytes, content_type: str) -> None:
    if settings.STORAGE_BACKEND == "local":
        _local_upload_bytes(key, content)
    else:
        _s3_upload_bytes(key, content, content_type)


def download_bytes(key: str) -> bytes:
    if settings.STORAGE_BACKEND == "local":
        return _local_download_bytes(key)
    return _s3_download_bytes(key)


def public_url(key: str) -> str:
    if settings.STORAGE_BACKEND == "local":
        return _local_public_url(key)
    return _s3_public_url(key)
