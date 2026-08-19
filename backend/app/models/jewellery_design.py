import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class JewelleryDesign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One bulk, tenant-scoped reference-catalog design image for the jewellery-only
    Material -> Category -> Design browsing carousel (see the carousel feature plan).

    Deliberately NOT `CatalogItem`/`Image`: those two are cloned per-tenant at
    business-creation time by `app/services/niche_provisioning.py::provision_from_template`
    (every niche template's `default_catalog` gets copied into each new business's own
    rows) and `Image` is built for a small, hand-curated admin gallery (see
    app/models/image.py's docstring -- one owner-CheckConstraint row per uploaded image,
    manually captioned/ordered by Super Admin). Jewellery design inventory is the
    opposite shape: potentially thousands of bulk, Unsplash-sourced designs per
    restaurant, downloaded and deduped by a script (not uploaded one-by-one), and never
    meant to be cloned into every new jewellery business at signup -- that would be an
    unbounded per-tenant storage explosion for what is really shared reference stock.
    This table follows the same tenant-isolation pattern as every other tenant-scoped
    model (`restaurant_id` FK + CASCADE + indexed, same as `CatalogItem`), it's just
    never run through the generic catalog/provisioning/Image pipeline.
    """

    __tablename__ = "jewellery_designs"
    __table_args__ = (
        Index(
            "ix_jewellery_designs_restaurant_material_category",
            "restaurant_id",
            "material",
            "category",
        ),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # e.g. "gold", "silver", "rose_gold", "platinum" -- indexed via the composite index
    # above (restaurant_id, material, category), not its own single-column index.
    material: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. "bangles", "rings", "necklaces", "earrings", "bridal"
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    design_code: Mapped[str | None] = mapped_column(String(50))
    # Relative key under the media root (LOCAL_MEDIA_DIR or the S3 bucket), matching
    # how every other stored-image reference in this codebase is addressed -- e.g.
    # "jewellery/gold/bangles/gold_bangles_001.jpg". Served via the existing passthrough
    # GET /media/{key:path} route, not a dedicated endpoint.
    image_key: Mapped[str] = mapped_column(String(500), nullable=False)
    thumbnail_key: Mapped[str | None] = mapped_column(String(500))
    # Always "unsplash" today (see the downloader script), kept as a free string rather
    # than a DB enum so a future manual/other-provider source doesn't need a migration.
    source: Mapped[str] = mapped_column(String(20), default="unsplash")
    # The Unsplash photo id this design was downloaded from -- used purely for
    # download-dedup by the asset downloader script (skip if a row with this source_id
    # already exists for the restaurant), not exposed to the bot/frontend.
    source_id: Mapped[str | None] = mapped_column(String(200))
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # The `retailer_id` this design was synced to under Restaurant.whatsapp_catalog_id in
    # Meta's Commerce Catalog (see app/services/meta_catalog_sync.py::sync_designs_to_catalog),
    # so a design already on Meta's side isn't resubmitted on a re-run and so
    # generic_flow_engine.py::_render_jewellery_gallery knows which designs on a page are
    # eligible for the native product_list carousel. NULL until synced -- every existing
    # (and every newly downloaded) design starts here, since no restaurant has a Commerce
    # Catalog connected yet; the sync function only ever sets this, nothing else does.
    meta_retailer_id: Mapped[str | None] = mapped_column(String(200))
