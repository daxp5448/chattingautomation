import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import EngagementType


class FlowDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The actual, currently-active step sequence for one business on the generic
    engine -- copied from a NicheTemplate.default_flow_steps at business-creation time,
    then independently editable per business from that point on (editing a template
    afterward never touches a business that already copied from it).

    `steps` is a list of dicts, each shaped:
        step_id: str                          -- unique within this flow
        type: FlowStepType value
        prompt_key: str                        -- app/services/template_engine.py key
        buttons_from: str | None               -- a fixed data-provider name (see
                                                   generic_flow_engine.py::DATA_PROVIDERS)
        static_options: [{"id", "title", "emoji"}] | None   -- used when buttons_from
                                                   is "static" (e.g. cart actions, yes/no)
        capture_key: str | None                -- context key the selected value is
                                                   stored under
        next: str | None                       -- default next step_id
        routes: {reply_id_or_prefix: step_id} | None  -- overrides `next` for specific
                                                   replies (checked prefix-first, then
                                                   exact match, before falling back to next)
        action: str | None                     -- an action verb (see ACTION_VERBS) run
                                                   when this step's input is processed
        back_target: str | None                -- step_id the __back__ reply returns to;
                                                   None only for the welcome step
        allow_skip: bool                       -- shows a Skip button alongside a
                                                   free_text_input step
        show_image: bool                       -- prepend the relevant banner/category/
                                                   item image before this step's text
        skip_if_module_off: str | None         -- a business.modules key; if false,
                                                   this step is bypassed straight to `next`
        terminal: bool                         -- true only on the flow's final step
                                                   (no back-navigation is offered after it)

    Phase 2 Item 3 (Drag & Drop Flow Builder) additions, all on steps whose `type` is one
    of the 5 new FlowStepType values -- see generic_flow_engine.py's module docstring:
        condition: {context_key, operator, value} | None  -- CONDITION steps only
        then_step / else_step: str | None      -- CONDITION steps only
        delay_seconds: int | None              -- DELAY steps only
        endpoint_id: str | None                -- API_CALL steps only, an ApiEndpoint id
        message: str | None                    -- HUMAN_HANDOFF steps only, shown to the
                                                   customer once handed off
    """

    __tablename__ = "flow_definitions"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    niche_code: Mapped[str] = mapped_column(nullable=False)
    # The single source of truth for what create_engagement produces -- read directly by
    # generic_flow_engine.py::_Engine._create_engagement rather than re-derived from
    # niche_code, so a business that ever needs a custom action_type isn't blocked.
    action_type: Mapped[EngagementType] = mapped_column(nullable=False)
    entry_step_id: Mapped[str] = mapped_column(nullable=False, default="welcome")
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # {step_id: {"x": float, "y": float}} -- the visual builder's node positions.
    # Deliberately NOT a key on each step dict above: keeps the engine's step-shape
    # contract (everything generic_flow_engine.py actually reads) free of UI-only
    # concerns, matching app/services/flow_shape_validation.py's stated philosophy that
    # flow-shape and UI-editing are distinct concerns. The engine never reads this column.
    ui_layout: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
