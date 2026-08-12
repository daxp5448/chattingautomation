"""Default ImageTypeProfile rows for the Universal Image Processing Pipeline -- the 10
image types named in the Business OS spec, each with sensible starting variant sizes per
usage context (whatsapp/thumbnail/banner/gallery/website).

Deliberately NOT seeded as migration data (unlike this project's earlier `niche_templates`
attempt would have been) -- app/tests/conftest.py's autouse `_fresh_schema` fixture builds
the test schema via `Base.metadata.create_all`, never by running Alembic migrations, so
migration-only seed data is invisible to the whole test suite. Instead this follows the
same explicit-sync pattern as app/services/niche_template_sync.py: `sync_default_profiles`
is idempotent (upsert-by-code) and callable from a deploy-time script
(app/scripts/seed_image_type_profiles.py), tests, or anywhere else that needs the defaults
present, rather than being baked into a migration only real deployments ever run.

Editable afterward via PATCH /image-type-profiles without another migration -- these are
starting defaults, not a permanent hardcoded list. Adding an 11th image type entirely is a
Super Admin POST, no code change needed.
"""

from sqlalchemy import select

from app.models.image_type_profile import ImageTypeProfile


def _spec(variant_name: str, target_context: str, width: int, height: int, crop_mode: str = "cover") -> dict:
    return {
        "variant_name": variant_name,
        "target_context": target_context,
        "width": width,
        "height": height,
        "crop_mode": crop_mode,
        "format": "webp",
    }


def _profile(code: str, label: str, specs: list[dict], max_bytes: int = 10 * 1024 * 1024) -> dict:
    return {"code": code, "label": label, "variant_specs": specs, "max_upload_size_bytes": max_bytes}


DEFAULT_PROFILES: list[dict] = [
    _profile("logo", "Logo", [
        _spec("thumbnail", "thumbnail", 200, 200, "cover"),
        _spec("whatsapp", "whatsapp", 640, 640, "contain"),
        _spec("website", "website", 400, 400, "contain"),
    ]),
    _profile("cover", "Cover Image", [
        _spec("thumbnail", "thumbnail", 400, 225, "cover"),
        _spec("banner", "banner", 1200, 630, "cover"),
        _spec("whatsapp", "whatsapp", 1200, 630, "cover"),
        _spec("website", "website", 1600, 900, "cover"),
    ]),
    _profile("banner", "Banner", [
        _spec("banner", "banner", 1200, 630, "cover"),
        _spec("whatsapp", "whatsapp", 1200, 630, "cover"),
        _spec("website", "website", 1920, 1080, "cover"),
    ]),
    _profile("category", "Category", [
        _spec("thumbnail", "thumbnail", 300, 300, "cover"),
        _spec("whatsapp", "whatsapp", 600, 400, "cover"),
        _spec("website", "website", 800, 600, "cover"),
    ]),
    _profile("product", "Product", [
        _spec("thumbnail", "thumbnail", 300, 300, "cover"),
        _spec("whatsapp", "whatsapp", 600, 400, "cover"),
        _spec("gallery", "gallery", 1000, 1000, "contain"),
        _spec("website", "website", 800, 800, "cover"),
    ]),
    _profile("gallery", "Gallery", [
        _spec("thumbnail", "thumbnail", 300, 300, "cover"),
        _spec("gallery", "gallery", 1200, 1200, "contain"),
        _spec("website", "website", 1000, 1000, "contain"),
    ]),
    _profile("service", "Service", [
        _spec("thumbnail", "thumbnail", 300, 300, "cover"),
        _spec("whatsapp", "whatsapp", 600, 400, "cover"),
        _spec("website", "website", 800, 600, "cover"),
    ]),
    _profile("staff", "Staff", [
        _spec("thumbnail", "thumbnail", 200, 200, "cover"),
        _spec("whatsapp", "whatsapp", 400, 400, "cover"),
        _spec("website", "website", 400, 400, "cover"),
    ]),
    _profile("property", "Property", [
        _spec("thumbnail", "thumbnail", 300, 225, "cover"),
        _spec("whatsapp", "whatsapp", 800, 600, "cover"),
        _spec("gallery", "gallery", 1200, 800, "cover"),
        _spec("website", "website", 1200, 800, "cover"),
    ], max_bytes=15 * 1024 * 1024),
    _profile("vehicle", "Vehicle", [
        _spec("thumbnail", "thumbnail", 300, 225, "cover"),
        _spec("whatsapp", "whatsapp", 800, 600, "cover"),
        _spec("gallery", "gallery", 1200, 800, "cover"),
        _spec("website", "website", 1200, 800, "cover"),
    ], max_bytes=15 * 1024 * 1024),
]


async def sync_default_profiles(session) -> list[str]:
    """Idempotent upsert-by-code, same shape as niche_template_sync.py's
    sync_niche_templates: a never-customized existing row's variant_specs/label/max size
    are updated in place (so re-running after a code change picks up new defaults), but a
    row a Super Admin has PATCHed (`ImageTypeProfile.is_customized=True`, set by
    app/api/v1/routers/image_type_profiles.py) is skipped entirely -- previously this
    function unconditionally overwrote every row on every re-run, which would have
    silently reverted any admin edit the next time the seed script ran (a normal,
    repeatable deploy step, not one-time bootstrap); caught during design review of the
    sibling Niche & Flow Management feature and fixed here too.
    """
    synced = []
    for defaults in DEFAULT_PROFILES:
        result = await session.execute(select(ImageTypeProfile).where(ImageTypeProfile.code == defaults["code"]))
        row = result.scalar_one_or_none()
        if row is not None and row.is_customized:
            continue
        if row is None:
            row = ImageTypeProfile(code=defaults["code"])
            session.add(row)
        row.label = defaults["label"]
        row.variant_specs = defaults["variant_specs"]
        row.max_upload_size_bytes = defaults["max_upload_size_bytes"]
        synced.append(defaults["code"])
    await session.commit()
    return synced
