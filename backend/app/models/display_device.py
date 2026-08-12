import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class DisplayDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A read-only POS/kitchen-display link for a restaurant. The raw bearer token is
    shown to the owner exactly once at creation time; only its hash is persisted here,
    so the token can be verified on every request but never re-displayed or leaked via
    the API. Revoking sets `revoked_at` (soft revoke) so device history is kept."""

    __tablename__ = "display_devices"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
