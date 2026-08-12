"""Shared helper so every niche seed file's demo image base URL comes from one place
(settings.PUBLIC_MEDIA_BASE_URL) -- switching from local-only MinIO to a publicly
tunnelled URL or a real bucket is then a single .env change + one
`sync_niche_templates` re-run, not an edit to all 12 niche files. See
backend/scripts/demo_asset_upload.py for the matching upload-side helper and
app/api/v1/routers/media.py for the passthrough route this can point at.
"""

from app.core.config import settings


def demo_image_base(niche_code: str) -> str:
    return f"{settings.PUBLIC_MEDIA_BASE_URL}/demo/{niche_code}"
