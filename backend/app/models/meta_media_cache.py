import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class MetaMediaCache(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A pre-uploaded WhatsApp media_id for one (phone_number_id, image_url) pair -- lets
    a frequently-resent image (a catalog item/category/flow-step photo curated via the
    Universal Image Processing Pipeline, see app/models/image.py, or a restaurant's
    welcome banner) be sent as {"image": {"id": ...}} instead of {"link": ...}, which
    Meta can deliver near-instantly since it already has the bytes.

    Deliberately a SEPARATE generic cache table, not extra columns bolted onto `Image` or
    `Restaurant` directly: image_presenter.py's resolved `ItemImage` (the shape every
    gallery-sending code path actually works with) only ever exposes a plain `url` string
    -- not the underlying `Image` row -- and the legacy CatalogItem.images JSON
    string-list fallback path (pre-Universal-Image-Pipeline items) has no owning row at
    all to attach cache columns to either way. Keying by the URL itself works uniformly
    for both, and for a Restaurant's cover_image_url/logo_url, with no schema change
    needed if a new image source is ever added later.

    See app/services/meta_media_upload.py for the actual upload call and
    MEDIA_ID_FRESHNESS_DAYS' explanation of why `uploaded_at` matters (Meta's ids aren't
    guaranteed to stay valid forever) -- this table only ever stores what that module
    returns, it doesn't decide freshness itself (that's the caller's job, same as
    JewelleryDesign's own inline meta_media_id fields already do).
    """

    __tablename__ = "meta_media_cache"
    __table_args__ = (
        # A media_id is only ever valid for sends FROM the specific phone_number_id it
        # was uploaded through -- the same image resent via a different number needs its
        # own row, hence both columns in the uniqueness key, not just image_url alone.
        UniqueConstraint("phone_number_id", "image_url", name="uq_meta_media_cache_phone_url"),
    )

    # For cascade cleanup when a business is deleted -- not part of the lookup key above,
    # since the same image URL + phone_number_id pair is meaningful independent of which
    # restaurant's send triggered the original upload (e.g. every jewellery business's
    # welcome banner send goes through the one shared sentinel phone_number_id).
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_number_id: Mapped[str] = mapped_column(String(50), nullable=False)
    image_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    media_id: Mapped[str] = mapped_column(String(200), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
