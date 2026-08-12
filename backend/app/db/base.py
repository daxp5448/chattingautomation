import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db.types import GUID


class Base(DeclarativeBase):
    pass


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        GUID(), primary_key=True, default=uuid.uuid4
    )


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    # Python-side defaults, not server_default/onupdate=func.now(): a server-computed
    # onupdate value isn't known to the ORM after an UPDATE flush, so accessing it
    # triggers an implicit lazy-refresh -- which isn't awaitable outside the async
    # greenlet context and crashes response serialization right after any PATCH.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
