import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class BotMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Editable, template-substituted copy per restaurant, keyed by a well-known slug
    (welcome, order_confirmed, payment_success, ...). Rendered by app.services.template_engine.
    """

    __tablename__ = "bot_messages"
    __table_args__ = (UniqueConstraint("restaurant_id", "key", name="uq_bot_message_restaurant_key"),)

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(String(2000), nullable=False)

    restaurant = relationship("Restaurant", back_populates="bot_messages")


class BotButton(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "bot_buttons"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str | None] = mapped_column(String(10))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    next_flow: Mapped[str | None] = mapped_column(String(100))
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    restaurant = relationship("Restaurant", back_populates="bot_buttons")
