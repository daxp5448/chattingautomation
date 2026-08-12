import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import TemplateCategory, TemplateStatus


class WhatsAppTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A restaurant's own WhatsApp Message Template (Meta's mechanism for business-
    initiated messages outside the 24-hour customer-service window) -- restaurant-scoped,
    not a shared/global catalog like NicheTemplate/ImageTypeProfile, because Meta approves
    a template against one specific WhatsApp Business Account
    (Restaurant.whatsapp_business_account_id), which is itself per-restaurant.

    `body_text`/`category`/`language`/`variable_examples` are only editable while `status`
    is DRAFT or REJECTED (enforced by the router, see app/api/v1/routers/
    whatsapp_templates.py) -- Meta doesn't support editing a PENDING/APPROVED template's
    content in place; "changing" one means creating a new template row with a new `name`.
    """

    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "name", name="uq_whatsapp_template_restaurant_name"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Meta's template name: lowercase + underscores only, validated at the schema level
    # (app/schemas/whatsapp_template.py) before ever calling Meta's API.
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[TemplateCategory] = mapped_column(nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    # Positional {{1}}, {{2}}, ... placeholders only for this pass -- see module docstring
    # in whatsapp_template_client.py for the scope cut (no header/footer/buttons/named vars).
    body_text: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Meta requires an example value per placeholder at submission time.
    variable_examples: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Set once POST .../submit succeeds.
    meta_template_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[TemplateStatus] = mapped_column(default=TemplateStatus.DRAFT, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(1000))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bookkeeping for the status-polling task (app/tasks/whatsapp_template_status_sync.py).
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
