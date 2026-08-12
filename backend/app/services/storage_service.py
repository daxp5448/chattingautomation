import boto3
from botocore.client import Config

from app.core.config import settings

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
            # Short connect timeout + no retries: when MinIO/S3 isn't reachable (e.g. not
            # configured yet), fail fast instead of stalling every webhook response for
            # boto3's default multi-retry backoff -- the caller treats this as best-effort.
            config=Config(signature_version="s3v4", connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
        )
    return _client


def ensure_bucket() -> None:
    client = _get_client()
    try:
        client.head_bucket(Bucket=settings.S3_BUCKET)
    except Exception:
        client.create_bucket(Bucket=settings.S3_BUCKET)


def upload_bytes(key: str, content: bytes, content_type: str, expires_in: int = 7 * 24 * 3600) -> str:
    """Uploads bytes to the configured bucket and returns a presigned GET URL.
    Used for invoice PDFs; the same helper works for product/logo image uploads later.
    """
    client = _get_client()
    client.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=content, ContentType=content_type)
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
