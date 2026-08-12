"""One-off helper: upload a local file to the configured S3/MinIO bucket and return a
PERMANENT public URL (not a presigned one) -- used for demo-niche welcome banners/catalog
images baked directly into NicheTemplate.default_catalog / welcome_banner_image JSON,
which must stay valid indefinitely (WhatsApp re-fetches the URL every time a message
referencing it is sent, potentially months later). Deliberately NOT reusing
app/services/image_storage_service.py::public_url (30-day presigned, meant for re-fetchable
Image-table rows) or app/services/storage_service.py::upload_bytes (7-day presigned, meant
for ephemeral invoice PDFs) -- this content's lifetime doesn't match either of those.
Requires the bucket to have a public-read policy (set once, see setup notes).

Usage: python -m scripts.demo_asset_upload <local_path> <s3_key>
"""

import sys

from app.core.config import settings
from app.services.image_storage_service import upload_bytes


def public_url(key: str) -> str:
    # Same setting app/niche_seeds/_media.py::demo_image_base reads -- one place to
    # switch from local MinIO to a public tunnel/bucket URL for every demo asset at once.
    return f"{settings.PUBLIC_MEDIA_BASE_URL}/{key}"


def upload_file(local_path: str, key: str) -> str:
    with open(local_path, "rb") as f:
        content = f.read()
    content_type = "image/png" if key.lower().endswith(".png") else "image/jpeg"
    upload_bytes(key, content, content_type)
    return public_url(key)


if __name__ == "__main__":
    local_path, key = sys.argv[1], sys.argv[2]
    print(upload_file(local_path, key))
