"""Downloads a seed set of jewellery reference-design images from Unsplash and inserts one
`JewelleryDesign` row per newly-downloaded image, for the Material -> Category -> Design
WhatsApp browsing carousel (see the carousel feature plan).

Safe to re-run: for every (material, category) combo this first counts how many
JewelleryDesign rows already exist for that restaurant+material+category and only tops up
the shortfall, then for each Unsplash search result skips it if either (a) a row with that
`source_id` already exists for this restaurant (the authoritative dedup key), or (b) the
deterministic destination file already exists on disk. A second run against an
already-fully-seeded restaurant downloads nothing new.

Originals are saved under LOCAL_MEDIA_DIR at
    jewellery/{material}/{category}/{material}_{category}_{index:03d}.jpg
and thumbnails (400x400 cover-cropped webp, via the existing
image_pipeline.generate_variant()) at
    jewellery/{material}/{category}/thumbnails/{material}_{category}_{index:03d}.webp
-- these relative keys become JewelleryDesign.image_key / .thumbnail_key respectively, and
are served through the existing GET /media/{key:path} passthrough (same as every other
stored image in this codebase), never a dedicated endpoint.

Requires UNSPLASH_ACCESS_KEY (see app/core/config.py) to be set -- no working default, and
this script refuses to silently no-op if it's unset (unlike e.g. SMTP_HOST's "not
configured" no-op pattern elsewhere): a jewellery restaurant with zero designs is a
broken-looking bot, so a missing key is a loud, immediate failure here instead.

Usage:
    python -m app.scripts.jewellery.download_jewellery_assets --restaurant-id <uuid>
    python -m app.scripts.jewellery.download_jewellery_assets --restaurant-id <uuid> --dry-run
"""

import argparse
import asyncio
import logging
import sys
import uuid
from pathlib import Path

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.jewellery_design import JewelleryDesign
from app.models.restaurant import Restaurant
from app.repositories.jewellery_design_repository import JewelleryDesignRepository
from app.services import image_storage_service
from app.services.image_pipeline import ImageValidationError, generate_variant, validate_upload

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"

# Same variant spec shape image_pipeline.generate_variant() already expects (see e.g.
# ImageTypeProfile.variant_specs entries) -- a 400x400 cover-cropped webp thumbnail, the
# same "thumbnail"-class size used elsewhere in this pipeline.
THUMBNAIL_SPEC = {"width": 400, "height": 400, "crop_mode": "cover", "format": "webp"}

MATERIALS = ["gold", "silver", "rose_gold", "platinum"]
MATERIAL_DISPLAY = {"gold": "Gold", "silver": "Silver", "rose_gold": "Rose Gold", "platinum": "Platinum"}

# Product-style, close-up, clean-background search queries per category (product spec
# section 9's pattern -- material display name + category noun, "jewellery" appended
# where the bare category word would otherwise be too ambiguous on Unsplash, e.g. plain
# "gold bangles" also returns fashion/lifestyle shots).
CATEGORY_QUERY_TEMPLATES = {
    "bangles": "{material} bangles jewellery",
    "bridal": "{material} bridal jewellery",
    "necklaces": "{material} necklace jewellery",
    "earrings": "{material} earrings jewellery",
    "rings": "{material} ring jewellery",
}

# ~8-12 is realistic for a narrow product-style query against Unsplash's real inventory --
# this does not force a fixed count, see _process_combo below, which only downloads up to
# however many distinct, non-duplicate results actually come back.
TARGET_COUNT_PER_COMBO = 10

# (material, category, search_query, target_count) -- the 4x5 = 20 combo seed set.
COMBOS: list[tuple[str, str, str, int]] = [
    (material, category, template.format(material=MATERIAL_DISPLAY[material].lower()), TARGET_COUNT_PER_COMBO)
    for material in MATERIALS
    for category, template in CATEGORY_QUERY_TEMPLATES.items()
]

# Politeness delay between outbound HTTP calls (search + each image download) -- no need
# for anything fancier at this scale (~20 searches + ~200 downloads max per full run).
REQUEST_DELAY_SECONDS = 0.2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download jewellery design reference images from Unsplash and seed "
        "JewelleryDesign rows for one restaurant."
    )
    parser.add_argument("--restaurant-id", required=True, help="UUID of the restaurant these designs belong to")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do everything except writing files to disk and inserting/committing DB rows",
    )
    return parser.parse_args(argv)


async def _search_unsplash(client: httpx.AsyncClient, query: str, per_page: int) -> list[dict]:
    response = await client.get(
        UNSPLASH_SEARCH_URL,
        params={"query": query, "per_page": min(per_page, 30), "orientation": "squarish"},
        headers={"Authorization": f"Client-ID {settings.UNSPLASH_ACCESS_KEY}"},
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json().get("results", [])


async def _download_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, timeout=30.0)
    response.raise_for_status()
    return response.content


async def _existing_source_ids(session, restaurant_id: uuid.UUID, material: str, category: str) -> set[str]:
    stmt = select(JewelleryDesign.source_id).where(
        JewelleryDesign.restaurant_id == restaurant_id,
        JewelleryDesign.source == "unsplash",
        JewelleryDesign.material == material,
        JewelleryDesign.category == category,
    )
    result = await session.execute(stmt)
    return {row for row in result.scalars().all() if row is not None}


async def _process_combo(
    client: httpx.AsyncClient,
    session,
    restaurant_id: uuid.UUID,
    material: str,
    category: str,
    query: str,
    target_count: int,
    dry_run: bool,
) -> dict[str, int]:
    """Tops up one (material, category) combo up to target_count and returns per-combo
    counters (downloaded / skipped_dedup / skipped_exists / zero_results)."""
    stats = {"downloaded": 0, "skipped_dedup": 0, "skipped_exists": 0, "zero_results": 0}

    existing_ids = await _existing_source_ids(session, restaurant_id, material, category)
    existing_count = len(existing_ids)
    needed = max(0, target_count - existing_count)
    if needed == 0:
        logger.info("%s/%s already has %d designs (target %d) -- nothing to do", material, category, existing_count, target_count)
        return stats

    logger.info('%s/%s: searching Unsplash for "%s" (need %d more)', material, category, query, needed)
    photos = await _search_unsplash(client, query, per_page=target_count)
    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    if not photos:
        logger.warning("%s/%s: zero Unsplash results for query %r", material, category, query)
        stats["zero_results"] = 1
        return stats

    media_root = Path(settings.LOCAL_MEDIA_DIR).resolve()
    combo_dir = f"jewellery/{material}/{category}"
    next_index = existing_count + 1
    downloaded_this_combo = 0

    for photo in photos:
        if downloaded_this_combo >= needed:
            break

        source_id = photo.get("id")
        if not source_id or source_id in existing_ids:
            stats["skipped_dedup"] += 1
            continue

        index = next_index + downloaded_this_combo
        image_key = f"{combo_dir}/{material}_{category}_{index:03d}.jpg"
        thumbnail_key = f"{combo_dir}/thumbnails/{material}_{category}_{index:03d}.webp"

        # Deterministic-path check -- a secondary idempotency guard alongside the
        # source_id dedup above (e.g. a previous run's DB commit failed after the file was
        # already written to disk).
        if (media_root / image_key).exists():
            stats["skipped_exists"] += 1
            continue

        image_url = (photo.get("urls") or {}).get("regular")
        if not image_url:
            stats["skipped_dedup"] += 1
            continue

        try:
            raw_bytes = await _download_bytes(client, image_url)
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
            validated = validate_upload(raw_bytes)
        except (httpx.HTTPError, ImageValidationError) as exc:
            logger.warning("%s/%s: failed to download/validate photo %s: %s", material, category, source_id, exc)
            continue

        design_code = f"{material}_{category}_{index:03d}"
        name = f"{MATERIAL_DISPLAY[material]} {category.replace('_', ' ').title()} Design {index:03d}"

        if dry_run:
            logger.info("[dry-run] would save %s + %s and insert JewelleryDesign(%s)", image_key, thumbnail_key, design_code)
            downloaded_this_combo += 1
            stats["downloaded"] += 1
            continue

        thumbnail_bytes, thumb_format, _w, _h = generate_variant(validated.pil_image, THUMBNAIL_SPEC)

        # Original is stored as-downloaded (Unsplash's "regular" rendition is effectively
        # always a JPEG) -- validate_upload() above is the sniff/corruption/decompression-
        # bomb guard and the source of the PIL image used for the thumbnail, not a
        # re-encode step for the original.
        image_storage_service.upload_bytes(image_key, raw_bytes, "image/jpeg")
        image_storage_service.upload_bytes(thumbnail_key, thumbnail_bytes, f"image/{thumb_format}")

        design = JewelleryDesign(
            restaurant_id=restaurant_id,
            material=material,
            category=category,
            name=name,
            design_code=design_code,
            image_key=image_key,
            thumbnail_key=thumbnail_key,
            source="unsplash",
            source_id=source_id,
            display_order=index,
            is_active=True,
        )
        await JewelleryDesignRepository(session).create(design)

        downloaded_this_combo += 1
        stats["downloaded"] += 1
        existing_ids.add(source_id)

    if not dry_run and downloaded_this_combo:
        await session.commit()

    return stats


async def main() -> None:
    args = parse_args()

    if not settings.UNSPLASH_ACCESS_KEY:
        logger.error(
            "UNSPLASH_ACCESS_KEY is not set -- refusing to silently download nothing. "
            "Set it in backend/.env (see app/core/config.py) before running this script."
        )
        sys.exit(1)

    try:
        restaurant_id = uuid.UUID(args.restaurant_id)
    except ValueError:
        logger.error("Invalid --restaurant-id %r -- must be a UUID", args.restaurant_id)
        sys.exit(1)

    totals = {"combos": 0, "downloaded": 0, "skipped_dedup": 0, "skipped_exists": 0, "zero_result_combos": []}

    async with AsyncSessionLocal() as session:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            logger.error("No restaurant found with id %s", restaurant_id)
            sys.exit(1)

        async with httpx.AsyncClient() as client:
            for material, category, query, target_count in COMBOS:
                stats = await _process_combo(
                    client, session, restaurant_id, material, category, query, target_count, args.dry_run
                )
                totals["combos"] += 1
                totals["downloaded"] += stats["downloaded"]
                totals["skipped_dedup"] += stats["skipped_dedup"]
                totals["skipped_exists"] += stats["skipped_exists"]
                if stats["zero_results"]:
                    totals["zero_result_combos"].append(f"{material}/{category}")

    logger.info(
        "%sDone -- combos=%d downloaded=%d skipped_dedup=%d skipped_exists=%d zero_result_combos=%s",
        "[dry-run] " if args.dry_run else "",
        totals["combos"],
        totals["downloaded"],
        totals["skipped_dedup"],
        totals["skipped_exists"],
        totals["zero_result_combos"] or "none",
    )


if __name__ == "__main__":
    asyncio.run(main())
