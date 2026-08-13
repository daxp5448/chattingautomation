"""The Super Admin / Business Admin "Bot Preview" simulator: drives the REAL
generic_flow_engine.py against a business's REAL, currently-live FlowDefinition/catalog/
messages -- never a separate fake preview engine or canned script. Every turn is a real
call into `process_inbound_message(..., dry_run=True)`, so editing a message, image, or
button in the Flow Builder / Messages screen and re-running the preview shows the change
immediately, with zero preview-specific caching anywhere in this file.

`dry_run=True` (see generic_flow_engine.py::_Engine.dry_run) guarantees a preview
conversation can never create a real Engagement, real payment link, real staff
notification, real analytics event, or real live-chat broadcast -- see that flag's
docstring for the exact mechanism. What a preview conversation DOES persist for real:
its own Customer/GenericConversationState/Message rows, scoped to a synthetic phone
number of the form "preview:<token>" that can never collide with a real WhatsApp number
(always all-digits) -- this is what lets a multi-turn preview keep its place between one
HTTP request and the next, using the exact same repositories/state machine a real
customer's conversation does, with no new state-storage concept invented for this
feature.
"""

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.customer import Customer
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.restaurant_repository import RestaurantRepository
from app.services.generic_flow_engine import GenericInteraction, preview_jump_to_step, process_inbound_message
from app.services.whatsapp_client import InMemoryWhatsAppSender

router = APIRouter(prefix="/restaurants/{restaurant_id}/flow/preview", tags=["flow-preview"])

# Same bar as every other flow-editing endpoint (flow_definitions.py::_MANAGE_FLOW) --
# previewing isn't itself destructive, but it's part of the same admin workflow
# (edit -> preview -> publish) and shouldn't be open to cashier/kitchen accounts.
_MANAGE_FLOW = require_roles(UserRole.OWNER, UserRole.MANAGER)

_PREVIEW_PHONE_PREFIX = "preview:"


class PreviewTurnRequest(BaseModel):
    # Omit on the very first turn ("Start Preview" / "Restart") to get a fresh
    # conversation; the response always echoes back the session_id in use, which the
    # frontend then sends on every subsequent turn to continue the same conversation.
    session_id: str | None = None
    kind: str = Field(description='"text" | "button_reply" | "location"')
    text: str | None = None
    reply_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class PreviewTurnResponse(BaseModel):
    session_id: str
    # Raw OutboundMessage.payload dicts, in send order -- Meta's own Graph API JSON
    # shape (see whatsapp_client.py::OutboundMessage), so the frontend renders exactly
    # what a real customer's WhatsApp would, with no translation layer to drift out of
    # sync with what actually gets sent in production.
    messages: list[dict]


class PreviewJumpRequest(BaseModel):
    session_id: str | None = None
    step_id: str


def _new_session_id() -> str:
    return secrets.token_hex(8)  # 16 hex chars -- fits Customer.phone's String(30) alongside the "preview:" prefix


@router.post("", response_model=PreviewTurnResponse)
async def preview_turn(
    restaurant_id: uuid.UUID, payload: PreviewTurnRequest, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await RestaurantRepository(db).get(tenant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    session_id = payload.session_id or _new_session_id()
    phone = f"{_PREVIEW_PHONE_PREFIX}{session_id}"

    sender = InMemoryWhatsAppSender()
    interaction = GenericInteraction(
        kind=payload.kind,
        text=payload.text,
        reply_id=payload.reply_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        profile_name="Preview Admin",
    )
    await process_inbound_message(db, sender, restaurant, phone, interaction, dry_run=True)

    return PreviewTurnResponse(session_id=session_id, messages=[m.payload for m in sender.sent])


@router.post("/jump", response_model=PreviewTurnResponse)
async def preview_jump(
    restaurant_id: uuid.UUID, payload: PreviewJumpRequest, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    """"Preview This Step" / "Preview From Here" -- jumps a preview session straight to
    one node's current rendering, bypassing every step that would normally precede it.
    Resets that session's context first (see generic_flow_engine.py::preview_jump_to_step),
    so any {{variable}} only real navigation would have captured renders empty rather
    than stale/wrong -- expected and visible, not silently faked."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await RestaurantRepository(db).get(tenant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")

    session_id = payload.session_id or _new_session_id()
    phone = f"{_PREVIEW_PHONE_PREFIX}{session_id}"
    sender = InMemoryWhatsAppSender()
    await preview_jump_to_step(db, sender, restaurant, phone, payload.step_id)
    return PreviewTurnResponse(session_id=session_id, messages=[m.payload for m in sender.sent])


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_preview(restaurant_id: uuid.UUID, db: DbSession, user: User = Depends(_MANAGE_FLOW), session_id: str | None = None):
    """Deletes one preview session's Customer row (cascades its
    GenericConversationState/Message rows) so "Restart"/"Clear Conversation" genuinely
    starts over rather than resuming stale context. Safe to skip calling this at all --
    an abandoned preview session is just a small, harmlessly orphaned, clearly-marked
    (phone starts with "preview:") row; nothing else in the product ever reads it."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    if not session_id:
        return
    phone = f"{_PREVIEW_PHONE_PREFIX}{session_id}"
    await db.execute(delete(Customer).where(Customer.restaurant_id == tenant_id, Customer.phone == phone))
    await db.commit()
