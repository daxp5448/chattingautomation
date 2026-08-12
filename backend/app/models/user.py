import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import UserRole


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # One-time account-setup flow (see POST /restaurants and POST /auth/setup): a newly
    # created owner account has no usable password until setup completes, so it can't be
    # logged into via /auth/login by anyone who doesn't hold this token. Nullable/unused
    # once setup is complete (or for users created directly via /auth/register, which
    # never populates these).
    setup_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    setup_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    # Null for super_admin (platform-wide); scoped to one restaurant otherwise.
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )

    restaurant = relationship("Restaurant", back_populates="users")
