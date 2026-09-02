from typing import Any

from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import EngagementType


class NicheTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Super-Admin-authored starting point for a new business: default catalog
    (categories + sample items), default flow (see FlowDefinition), default terminology,
    and default module flags. Copied into a business's own rows at creation time (see
    app/services/niche_provisioning.py) -- editing a template afterward never retroactively
    changes a business that already picked it, same as any "template you start from, not
    a locked-in choice" design.
    """

    __tablename__ = "niche_templates"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[EngagementType] = mapped_column(nullable=False)
    icon: Mapped[str | None] = mapped_column(String(10))

    welcome_message: Mapped[str] = mapped_column(String(2000), nullable=False)
    welcome_banner_image: Mapped[str | None] = mapped_column(String(1000))
    welcome_buttons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # [{name, icon_image, items: [{name, description, price, price_type, attributes,
    #   images}]}, ...] -- consumed only by app/services/niche_provisioning.py to seed a
    # new business's real catalog_categories/catalog_items rows; not read at conversation
    # time (the business's own rows are, so an admin editing their catalog afterward is
    # never fighting a template default).
    default_catalog: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # See app/models/flow_definition.py for the step-list shape this seeds.
    default_flow_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # Visual-builder node positions for default_flow_steps -- see
    # FlowDefinition.ui_layout's docstring for why this is a separate field, not a key on
    # each step. Copied alongside default_flow_steps at provisioning time (see
    # app/services/niche_provisioning.py) so a newly-provisioned business's builder opens
    # to the template author's own layout instead of an unlaid-out graph.
    default_ui_layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # {"status_labels": {"confirmed": "Preparing", ...}, "catalog_label": "Menu",
    #  "category_label": "Category", "item_label": "Item", "staff_label": "Staff"} --
    # purely display copy, read by the admin UI and by notify_business(); the underlying
    # EngagementStatus/generic model never changes per niche.
    terminology: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # {"tone": "premium_elegant", "language": "hinglish", "emoji_level": "low",
    #  "response_length": "short", "business_personality": "jeweller"} -- this niche's
    # default conversational style, merged onto a newly-provisioned business's own
    # Restaurant.conversation_settings (see niche_provisioning.py, same merge-never-
    # clobber pattern as default_modules), then freely editable per-business afterward.
    # Same JSON-dict shape as Restaurant.conversation_settings by design.
    default_personality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # {"staff_selection": true, "deposit_payment": false, ...} -- default module flags
    # copied onto the business at creation; independently toggleable after via the
    # business's own settings, same pattern as Restaurant.payment_methods today.
    default_modules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Set the moment a Super Admin PATCHes this row (see app/api/v1/routers/niche_templates.py).
    # app/services/niche_template_sync.py's seed sync skips a customized row entirely on
    # re-run instead of overwriting it -- without this flag, running the seed script again
    # (a normal, repeatable deploy step, not a one-time bootstrap) would silently revert
    # any admin edit back to the code-defined defaults.
    is_customized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
