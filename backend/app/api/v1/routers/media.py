"""Public passthrough for demo/catalog images stored in S3/MinIO -- lets images ride the
SAME publicly-tunnelled backend URL the WhatsApp webhook already needs (see
GOING_LIVE.md's ngrok step), instead of requiring a second public tunnel/service pointed
directly at MinIO. MinIO itself (whatever S3_ENDPOINT_URL is) never needs to be reachable
from the internet -- only this backend does, and it already has to be for the webhook.

Deliberately no auth: these are meant to be publicly fetchable (Meta's servers fetch
WhatsApp message images anonymously, and demo/catalog photos aren't sensitive), the exact
same trust level a real public S3 bucket would have.
"""

import mimetypes

from fastapi import APIRouter, HTTPException, Response, status

from app.services import image_storage_service
from app.services.image_storage_service import ImageStorageError

router = APIRouter(prefix="/media", tags=["media"])


@router.get("/{key:path}")
async def get_media(key: str) -> Response:
    try:
        content = image_storage_service.download_bytes(key)
    except ImageStorageError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    content_type = mimetypes.guess_type(key)[0] or "application/octet-stream"
    return Response(
        content=content,
        media_type=content_type,
        # Demo/catalog photos are effectively immutable once uploaded (a new upload gets
        # a new key in practice) -- safe for Meta/browsers to cache aggressively.
        headers={"Cache-Control": "public, max-age=604800"},
    )
