"""Minimal live-chat surface for the generic multi-niche engine's HUMAN_HANDOFF step
(app/services/generic_flow_engine.py) -- a smaller, generic-engine-aware sibling of the
legacy-only app/api/v1/routers/conversations.py (which is typed directly to the legacy
ConversationState/ConversationStep and has zero awareness of GenericConversationState).
Deliberately not extending that file -- see the approved plan for Phase 2 Item 3.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, DbSession, require_feature, resolve_tenant_id
from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.models.enums import MessageDirection, MessageSender
from app.models.message import Message
from app.models.restaurant import Restaurant
from app.repositories.customer_repository import CustomerRepository
from app.repositories.flow_definition_repository import FlowDefinitionRepository
from app.repositories.generic_conversation_repository import GenericConversationStateRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.schemas.conversation import ConversationSummary, MessageRead, StaffReplyCreate
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

router = APIRouter(prefix="/restaurants/{restaurant_id}/generic-conversations", tags=["generic-conversations"])

logger = logging.getLogger(__name__)

# Swap for InMemoryWhatsAppSender in tests, same module-level-singleton pattern as
# every other router this session that sends WhatsApp messages.
_sender = GraphAPIWhatsAppSender()


@router.get("", response_model=list[ConversationSummary])
async def list_handed_over_conversations(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    state_repo = GenericConversationStateRepository(db)
    message_repo = MessageRepository(db)
    customer_repo = CustomerRepository(db)

    states = await state_repo.list_handed_over(tenant_id)
    summaries = []
    for state in states:
        customer = await customer_repo.get(state.customer_id, tenant_id)
        messages = await message_repo.list_for_customer(tenant_id, state.customer_id)
        last = messages[-1] if messages else None
        summaries.append(
            ConversationSummary(
                customer_id=state.customer_id,
                customer_name=customer.name if customer else None,
                customer_phone=customer.phone if customer else "",
                last_message_at=last.created_at if last else None,
                last_message_preview=last.body[:100] if last else None,
            )
        )
    return summaries


@router.get("/{customer_id}/messages", response_model=list[MessageRead])
async def get_conversation_messages(restaurant_id: uuid.UUID, customer_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    return await MessageRepository(db).list_for_customer(tenant_id, customer_id)


@router.post("/{customer_id}/messages", response_model=MessageRead, status_code=status.HTTP_201_CREATED)
async def send_staff_reply(
    restaurant_id: uuid.UUID,
    customer_id: uuid.UUID,
    payload: StaffReplyCreate,
    db: DbSession,
    user: CurrentUser,
    _feature: None = Depends(require_feature("live_chat_handoff")),
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await RestaurantRepository(db).get(tenant_id)
    customer = await CustomerRepository(db).get(customer_id, tenant_id)
    if not restaurant or not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    # Inlined credential resolution (not app/services/generic_flow_engine.py::
    # send_generic_message) because that function always logs its own Message row as
    # sent_by=BOT -- reusing it here would both mislabel a staff reply and double-log it
    # alongside the correctly-labeled row created below. Same demo_sends_via_restaurant_id
    # routing as that function, for the same reason (a demo restaurant owns no real
    # WhatsApp number of its own).
    send_via = restaurant
    if restaurant.demo_sends_via_restaurant_id:
        send_via = await db.get(Restaurant, restaurant.demo_sends_via_restaurant_id)
    access_token = decrypt_secret(send_via.whatsapp_access_token_encrypted or "")
    try:
        await _sender.send(send_via.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, payload.body))
    except Exception:
        logger.warning("Generic live-chat: staff reply send failed for restaurant %s", tenant_id, exc_info=True)

    message = Message(
        restaurant_id=tenant_id, customer_id=customer_id, direction=MessageDirection.OUTBOUND,
        sent_by=MessageSender.STAFF, staff_user_id=user.id, body=payload.body[:4096],
    )
    message_repo = MessageRepository(db)
    message = await message_repo.create(message)
    await message_repo.commit()
    await ws_manager.broadcast(tenant_id, {"type": "generic_staff_reply", "customer_id": str(customer_id)})
    return message


@router.post("/{customer_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume_automation(restaurant_id: uuid.UUID, customer_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    state_repo = GenericConversationStateRepository(db)
    state = await state_repo.get_by_customer(customer_id, tenant_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    flow_def = await FlowDefinitionRepository(db).get_by_restaurant(tenant_id)
    state.current_step = flow_def.entry_step_id if flow_def else "welcome"
    state.context = {}
    state.is_handed_over = False
    await db.commit()
