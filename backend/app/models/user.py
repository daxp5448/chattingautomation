import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
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

    # Self-serve signup email verification (see POST /signup, POST /signup/verify-otp).
    # A self-signed-up owner is created with a REAL, usable hashed_password (unlike the
    # admin-invite setup-token flow above, whose password is an unusable random hash) but
    # is_active=False until this OTP is verified -- get_current_user's is_active check
    # blocks login/API access until then. Nullable/unused once verified (or for users
    # created through any other path, which never populate these). otp_attempts resets to
    # 0 on each new code issuance (wrong-guess lockout for THIS code); otp_resend_count
    # persists for the whole pending-verification lifetime (lifetime cap on how many codes
    # get sent, independent of guess attempts).
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    otp_resend_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Null for super_admin (platform-wide); scoped to one restaurant otherwise.
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    branch_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("branches.id", ondelete="SET NULL"), nullable=True
    )

    restaurant = relationship("Restaurant", back_populates="users")
