"""Unit tests for app/services/image_pipeline.py's directly-testable pieces
(validate_upload / generate_variant / compute_resolution_warning / process_image),
following the same "test the async function directly, not the Celery wrapper" pattern
app/tests/test_reconciliation.py uses for _check_stuck_payments.
"""

import io
import uuid

import pytest
from PIL import Image as PILImage
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.image import Image
from app.models.image_type_profile import ImageTypeProfile
from app.models.restaurant import Restaurant
from app.services import image_storage_service
from app.services.image_pipeline import (
    MAX_DECOMPRESSED_PIXELS,
    ImageValidationError,
    compute_resolution_warning,
    generate_variant,
    process_image,
    validate_upload,
)


def _make_jpeg_bytes(width: int, height: int, color=(200, 50, 50)) -> bytes:
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_png_bytes(width: int, height: int) -> bytes:
    img = PILImage.new("RGBA", (width, height), color=(10, 200, 10, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- validate_upload ----------------------------------------------------------------


def test_validate_upload_accepts_real_jpeg():
    raw = _make_jpeg_bytes(800, 600)
    result = validate_upload(raw)
    assert result.format == "JPEG"
    assert result.width == 800
    assert result.height == 600
    assert result.size_bytes == len(raw)


def test_validate_upload_rejects_empty_file():
    with pytest.raises(ImageValidationError, match="empty"):
        validate_upload(b"")


def test_validate_upload_rejects_oversized_file():
    raw = _make_jpeg_bytes(100, 100)
    with pytest.raises(ImageValidationError, match="maximum allowed size"):
        validate_upload(raw, max_upload_size_bytes=10)  # smaller than the real file


def test_validate_upload_rejects_non_image_bytes():
    with pytest.raises(ImageValidationError, match="not a readable image"):
        validate_upload(b"this is definitely not an image, just plain text bytes")


def test_validate_upload_rejects_decompression_bomb_shaped_dimensions():
    # A real PNG whose *declared* dimensions alone exceed the pixel cap -- validate_upload
    # must reject based on header-reported width*height before ever decoding pixel data.
    huge_side = int(MAX_DECOMPRESSED_PIXELS**0.5) + 1000
    img = PILImage.new("1", (huge_side, huge_side))  # 1-bit mode keeps this cheap to construct
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    with pytest.raises(ImageValidationError, match="too large"):
        validate_upload(buf.getvalue(), max_upload_size_bytes=100 * 1024 * 1024)


def test_validate_upload_rejects_unsupported_format():
    img = PILImage.new("RGB", (100, 100))
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    with pytest.raises(ImageValidationError, match="Unsupported image format"):
        validate_upload(buf.getvalue())


def test_validate_upload_auto_corrects_exif_orientation():
    img = PILImage.new("RGB", (200, 100), color=(0, 0, 255))
    exif = PILImage.Exif()
    exif[0x0112] = 6  # "Rotate 270 CW" orientation tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    result = validate_upload(buf.getvalue())
    # Orientation 6 swaps width/height once corrected.
    assert result.width == 100
    assert result.height == 200


# --- generate_variant -----------------------------------------------------------------


def test_generate_variant_cover_crop_produces_exact_target_dimensions():
    pil_image = PILImage.new("RGB", (1000, 400), color=(1, 2, 3))
    data, fmt, w, h = generate_variant(pil_image, {"width": 300, "height": 300, "crop_mode": "cover", "format": "webp"})
    assert fmt == "webp"
    assert (w, h) == (300, 300)
    assert PILImage.open(io.BytesIO(data)).size == (300, 300)


def test_generate_variant_contain_preserves_aspect_ratio_without_cropping():
    pil_image = PILImage.new("RGB", (1000, 500), color=(1, 2, 3))
    data, fmt, w, h = generate_variant(pil_image, {"width": 300, "height": 300, "crop_mode": "contain", "format": "webp"})
    assert w <= 300 and h <= 300
    assert w == 300 and h == 150  # 2:1 aspect ratio preserved, fit within 300x300


def test_generate_variant_flattens_alpha_onto_white_for_jpeg():
    pil_image = PILImage.new("RGBA", (100, 100), color=(255, 0, 0, 128))
    data, fmt, w, h = generate_variant(pil_image, {"width": 50, "height": 50, "crop_mode": "cover", "format": "jpeg"})
    assert fmt == "jpeg"
    result = PILImage.open(io.BytesIO(data))
    assert result.mode == "RGB"  # no alpha channel survives into a JPEG


# --- compute_resolution_warning --------------------------------------------------------


def test_compute_resolution_warning_flags_below_target_resolution():
    specs = [{"width": 1000, "height": 1000}]
    warning, reason = compute_resolution_warning(200, 200, 50_000, specs)
    assert warning is True
    assert reason == "below_target_resolution"


def test_compute_resolution_warning_flags_unusually_small_filesize():
    specs = [{"width": 100, "height": 100}]
    warning, reason = compute_resolution_warning(2000, 2000, 100, specs)
    assert warning is True
    assert reason == "unusually_small_filesize"


def test_compute_resolution_warning_clean_image_has_no_warning():
    specs = [{"width": 300, "height": 300}]
    warning, reason = compute_resolution_warning(2000, 2000, 500_000, specs)
    assert warning is False
    assert reason is None


# --- process_image (the real async orchestration function, called directly) -----------


@pytest.fixture
async def _catalog_item(db_session):
    restaurant = Restaurant(
        name="Image Pipeline Test Biz",
        slug="image-pipeline-test-biz",
        whatsapp_phone_number_id="IMG_TEST_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    category = CatalogCategory(restaurant_id=restaurant.id, name="Test Category")
    db_session.add(category)
    await db_session.flush()

    item = CatalogItem(restaurant_id=restaurant.id, category_id=category.id, name="Test Item", images=[])
    db_session.add(item)

    profile = ImageTypeProfile(
        code="product",
        label="Product",
        variant_specs=[
            {"variant_name": "thumbnail", "target_context": "thumbnail", "width": 100, "height": 100, "crop_mode": "cover", "format": "webp"},
            {"variant_name": "website", "target_context": "website", "width": 400, "height": 400, "crop_mode": "cover", "format": "webp"},
        ],
        max_upload_size_bytes=10 * 1024 * 1024,
    )
    db_session.add(profile)
    await db_session.commit()
    return restaurant, item


async def test_process_image_generates_every_variant_and_marks_ready(db_session, _catalog_item):
    restaurant, item = _catalog_item
    raw = _make_jpeg_bytes(800, 800)
    image = Image(
        restaurant_id=restaurant.id,
        image_type="product",
        catalog_item_id=item.id,
        original_key=f"images/test/original.jpeg",
        original_format="jpeg",
        original_width=800,
        original_height=800,
        original_size_bytes=len(raw),
        status="processing",
    )
    db_session.add(image)
    await db_session.commit()
    image_id = image.id  # captured before expire_all() below invalidates the object
    image_storage_service.upload_bytes(image.original_key, raw, "image/jpeg")

    await process_image(image_id)

    db_session.expire_all()
    result = await db_session.execute(select(Image).where(Image.id == image_id))
    refreshed = result.scalars().first()
    assert refreshed.status == "ready"
    assert set(refreshed.variants.keys()) == {"thumbnail", "website"}
    assert refreshed.variants["thumbnail"]["width"] == 100
    assert refreshed.variants["website"]["width"] == 400
    assert refreshed.resolution_warning is False


async def test_process_image_marks_failed_when_original_missing_from_storage(db_session, _catalog_item):
    restaurant, item = _catalog_item
    image = Image(
        restaurant_id=restaurant.id,
        image_type="product",
        catalog_item_id=item.id,
        original_key="images/does-not-exist/original.jpeg",
        original_format="jpeg",
        original_width=800,
        original_height=800,
        original_size_bytes=12345,
        status="processing",
    )
    db_session.add(image)
    await db_session.commit()
    image_id = image.id
    # Deliberately never uploaded to the fake store -- simulates a storage-layer
    # inconsistency (e.g. the original upload succeeded but its key was lost).

    await process_image(image_id)

    db_session.expire_all()
    result = await db_session.execute(select(Image).where(Image.id == image_id))
    refreshed = result.scalars().first()
    assert refreshed.status == "failed"
    assert refreshed.failure_reason == "processing_error"


async def test_process_image_is_a_no_op_for_a_non_processing_image(db_session, _catalog_item):
    """Prevents a redelivered/duplicate task from reprocessing an already-ready image."""
    restaurant, item = _catalog_item
    image = Image(
        restaurant_id=restaurant.id,
        image_type="product",
        catalog_item_id=item.id,
        original_key="images/already-ready/original.jpeg",
        original_format="jpeg",
        original_width=800,
        original_height=800,
        original_size_bytes=12345,
        status="ready",
        variants={"thumbnail": {"key": "x", "format": "webp", "width": 100, "height": 100, "size_bytes": 1}},
    )
    db_session.add(image)
    await db_session.commit()
    image_id = image.id

    await process_image(image_id)

    db_session.expire_all()
    result = await db_session.execute(select(Image).where(Image.id == image_id))
    refreshed = result.scalars().first()
    assert refreshed.status == "ready"
    assert list(refreshed.variants.keys()) == ["thumbnail"]  # untouched, not regenerated


async def test_process_image_missing_row_is_a_safe_no_op():
    await process_image(uuid.uuid4())  # must not raise
