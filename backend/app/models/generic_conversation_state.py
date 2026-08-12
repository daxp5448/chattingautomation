import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID


class GenericConversationState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Generic-engine equivalent of app/models/conversation_state.py. A genuinely
    separate table, not a repurposed column on the legacy one: the legacy table's
    `current_step` is typed to the fixed ConversationStep enum, which can't hold an
    arbitrary niche-defined step_id string without weakening that type for every
    existing (legacy) row too. Reuses Customer as-is (already niche-agnostic).
    """

    __tablename__ = "generic_conversation_states"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    current_step: Mapped[str] = mapped_column(nullable=False, default="welcome")
    # MutableDict, not a plain JSON column: the engine's whole "get context, mutate a key
    # in place, reassign to the same attribute" pattern (see generic_flow_engine.py --
    # every _process_input/_run_action branch does this) needs SQLAlchemy to detect an
    # in-place `dict.__setitem__` as a real change. A plain JSON column's dirty-tracking
    # compares the new value against the loaded snapshot by reference/equality; since no
    # copy is ever made, an in-place-mutated-then-reassigned dict can appear identical to
    # its own "before" state and silently get dropped from the UPDATE -- confirmed by
    # direct reproduction against a real SQLite file DB across separate sessions (i.e.
    # the actual "one webhook request = one session" shape), not just a theoretical
    # concern. MutableDict intercepts item assignment directly and flags the parent
    # object dirty itself, which is unconditional and doesn't depend on this timing at
    # all. (The legacy app/models/conversation_state.py::ConversationState.context has
    # the identical plain-JSON pattern and, on inspection, the identical latent bug --
    # it isn't touched here since it demonstrably works in the current test suite, most
    # likely because flow_engine.py's `_log_message` happens to call `session.flush()`
    # between most context mutations, incidentally resetting SQLAlchemy's comparison
    # baseline. That's fragile, not a real fix, and is called out as a separate finding
    # rather than changed in this pass, since editing the legacy engine's files wasn't
    # part of what was asked for or reviewed here.)
    context: Mapped[dict[str, Any]] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    assigned_staff_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Set by a HUMAN_HANDOFF step (see generic_flow_engine.py::_render_step) and checked
    # as the very first statement of _Engine.handle -- while True, every automated
    # branch (greeting-reset, back-nav, normal input processing) is skipped entirely;
    # inbound messages are still logged (already done before handle() is ever called)
    # but never advance the flow. Cleared only by a staff "resume automation" action via
    # app/api/v1/routers/generic_conversations.py.
    is_handed_over: Mapped[bool] = mapped_column(default=False, nullable=False)
