"""The Universal Image Processing Pipeline's core logic: upload validation, variant
generation, and the async orchestration function the Celery task
(app/tasks/image_tasks.py) wraps.

Split into small, directly-testable pieces (validate_upload / generate_variant /
compute_resolution_warning / process_image) rather than one monolithic task body, so
each can be unit-tested without going through Celery -- same reasoning as
app/tasks/reconciliation.py's `_check_stuck_payments`/`check_stuck_payments` split.

"Smart crop" here means standard center-crop-to-fill (Pillow's ImageOps.fit) -- honest
naming: there's no content-aware/ML cropping in this pass, and this module doesn't claim
one.
"""

import io
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from PIL import Image as PILImage
from PIL import ImageOps

from app.db.session import AsyncSessionLocal
from app.repositories.image_repository import ImageRepository
from app.repositories.image_type_profile_repository import ImageTypeProfileRepository
from app.services import image_storage_service

logger = logging.getLogger(__name__)

# Checked BEFORE Pillow decodes any pixel data (Image.open() itself is lazy -- it only
# reads header/metadata -- so width/height are available pre-decode; this bound is
# enforced before .load()/any pixel access, as a decompression-bomb guard rather than
# relying solely on Pillow's own global Image.MAX_IMAGE_PIXELS default).
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_DECOMPRESSED_PIXELS = 40_000_000  # ~40 megapixels
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
_SMALL_FILE_WARNING_BYTES = 5 * 1024


class ImageValidationError(ValueError):
    """A rejected upload -- bad format, too large, corrupt, or a decompression-bomb-shaped
    file. Routers translate this into a 400, never a 500."""


@dataclass
class ValidatedUpload:
    pil_image: PILImage.Image
    format: str
    width: int
    height: int
    size_bytes: int


def validate_upload(raw_bytes: bytes, max_upload_size_bytes: int = MAX_UPLOAD_BYTES) -> ValidatedUpload:
    """Real content-sniffing via Pillow, never trusting a client-supplied Content-Type.
    Size and pixel-dimension caps are both enforced before any full decode.
    """
    if not raw_bytes:
        raise ImageValidationError("Uploaded file is empty")
    if len(raw_bytes) > max_upload_size_bytes:
        raise ImageValidationError(f"File exceeds the maximum allowed size of {max_upload_size_bytes} bytes")

    try:
        img = PILImage.open(io.BytesIO(raw_bytes))
        fmt = (img.format or "").upper()
        width, height = img.size  # available from header, no full decode yet
    except Exception as exc:
        raise ImageValidationError("File is not a readable image") from exc

    if fmt not in ALLOWED_FORMATS:
        raise ImageValidationError(f"Unsupported image format: {fmt or 'unknown'}")
    if width <= 0 or height <= 0:
        raise ImageValidationError("Image has invalid dimensions")
    if width * height > MAX_DECOMPRESSED_PIXELS:
        raise ImageValidationError("Image dimensions are too large to process")

    try:
        img.load()  # now safe to fully decode -- dimensions already vetted above
    except Exception as exc:
        raise ImageValidationError("File is corrupt or truncated") from exc

    img = ImageOps.exif_transpose(img) or img  # auto-orientation-correct
    return ValidatedUpload(pil_image=img, format=fmt, width=img.width, height=img.height, size_bytes=len(raw_bytes))


def generate_variant(pil_image: PILImage.Image, spec: dict[str, Any]) -> tuple[bytes, str, int, int]:
    """Renders one derivative per an ImageTypeProfile.variant_specs entry, always from the
    caller-supplied `pil_image` (the caller is responsible for that being derived from the
    untouched original, never from another derivative -- see process_image below).
    """
    width, height = int(spec["width"]), int(spec["height"])
    crop_mode = spec.get("crop_mode", "cover")
    fmt = str(spec.get("format", "webp")).upper()
    if fmt == "JPG":
        fmt = "JPEG"

    img = pil_image.copy()
    if crop_mode == "cover":
        img = ImageOps.fit(img, (width, height), method=PILImage.Resampling.LANCZOS)
    else:  # "contain" -- fit within bounds, preserving aspect ratio, no crop
        img.thumbnail((width, height), PILImage.Resampling.LANCZOS)

    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        # JPEG has no alpha channel -- flatten onto white rather than let Pillow raise.
        background = PILImage.new("RGB", img.size, (255, 255, 255))
        rgba = img.convert("RGBA")
        background.paste(rgba, mask=rgba.split()[-1])
        img = background
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    buffer = io.BytesIO()
    save_kwargs = {"quality": 85, "optimize": True} if fmt in ("JPEG", "WEBP") else {}
    img.save(buffer, format=fmt, **save_kwargs)
    data = buffer.getvalue()
    return data, fmt.lower(), img.width, img.height


def compute_resolution_warning(
    original_width: int, original_height: int, original_size_bytes: int, variant_specs: list[dict[str, Any]]
) -> tuple[bool, str | None]:
    """An honest heuristic flag, NOT a scored quality metric -- see Image.resolution_warning's
    docstring for why quality_score was deliberately cut from this pass."""
    if variant_specs:
        largest = max(variant_specs, key=lambda s: int(s["width"]) * int(s["height"]))
        if original_width < int(largest["width"]) or original_height < int(largest["height"]):
            return True, "below_target_resolution"
    if original_size_bytes < _SMALL_FILE_WARNING_BYTES:
        return True, "unusually_small_filesize"
    return False, None


async def enqueue_processing(image_id: uuid.UUID) -> None:
    """Dispatches the Celery task for a newly-uploaded (or re-cropped) image -- a thin,
    monkeypatchable seam. Production: `Task.delay(...)` is a non-blocking message publish
    (no event loop involved), so this needs no `await` of its own in that path; declared
    `async def` anyway so tests can monkeypatch it to `await process_image(image_id)`
    directly instead, since no real Celery broker/worker runs in the test environment --
    that keeps everything on the caller's existing event loop rather than nesting a
    second one via asyncio.run() (the exact trap app/tasks/reconciliation.py's docstring
    warns about). See app/tasks/image_tasks.py for the real Celery task this dispatches
    to in production.
    """
    from app.tasks.image_tasks import generate_image_variants  # local import: avoids a
    # celery_app import at module load time for callers (e.g. plain service-layer tests)
    # that never need Celery at all.

    generate_image_variants.delay(str(image_id))


async def process_image(image_id: uuid.UUID) -> None:
    """Generates every derivative variant for one Image row -- the function the Celery
    task (app/tasks/image_tasks.py) wraps, and what a manual crop re-runs. Opens its own
    session (matches app/tasks/reconciliation.py's pattern) so it works identically
    whether called directly (tests, a synchronous retry) or via .delay().

    Always re-derives every variant from `image.original_key` -- never from another
    variant -- so repeated crops never compound quality loss and "restore original"
    always has a pristine source to regenerate from.
    """
    async with AsyncSessionLocal() as session:
        repo = ImageRepository(session)
        image = await repo.get(image_id)
        if image is None or image.status != "processing":
            return

        try:
            raw_bytes = image_storage_service.download_bytes(image.original_key)
            profile = await ImageTypeProfileRepository(session).get_by_code(image.image_type)
            variant_specs = profile.variant_specs if profile else []

            pil_image = PILImage.open(io.BytesIO(raw_bytes))
            pil_image.load()
            pil_image = ImageOps.exif_transpose(pil_image) or pil_image

            if image.crop_box:
                box = image.crop_box
                pil_image = pil_image.crop(
                    (box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])
                )

            variants: dict[str, Any] = {}
            for spec in variant_specs:
                data, fmt, w, h = generate_variant(pil_image, spec)
                key = f"images/{image.id}/derived/{spec['variant_name']}.{fmt}"
                image_storage_service.upload_bytes(key, data, f"image/{fmt}")
                variants[spec["variant_name"]] = {"key": key, "format": fmt, "width": w, "height": h, "size_bytes": len(data)}

            warning, reason = compute_resolution_warning(
                image.original_width, image.original_height, image.original_size_bytes, variant_specs
            )
            image.variants = variants
            image.resolution_warning = warning
            image.low_quality_reason = reason
            image.status = "ready"
            image.failure_reason = None
            await session.commit()
        except Exception:
            logger.warning("Image processing failed for image %s", image_id, exc_info=True)
            await session.rollback()
            # Separate, minimal update: a failure inside variant generation must not also
            # prevent the failure itself from being recorded (session.rollback() above
            # discards the failed in-progress changes, so this re-fetches a clean object).
            failed_image = await repo.get(image_id)
            if failed_image is not None:
                failed_image.status = "failed"
                failed_image.failure_reason = "processing_error"
                await session.commit()
