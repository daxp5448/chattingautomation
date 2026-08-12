import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import ConversationStep


class ConversationState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversation_states"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    current_step: Mapped[ConversationStep] = mapped_column(default=ConversationStep.WELCOME, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    customer = relationship("Customer", back_populates="conversation_state")
