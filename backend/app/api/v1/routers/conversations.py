import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, require_feature, resolve_tenant_id
from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.models.conversation_state import ConversationState
from app.models.enums import ConversationStep, MessageDirection, MessageSender
from app.models.message import Message
from app.repositories.customer_repository import CustomerRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.schemas.conversation import ConversationSummary, MessageRead, StaffReplyCreate
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage

router = APIRouter(prefix="/restaurants/{restaurant_id}/conversations", tags=["conversations"])

logger = logging.getLogger(__name__)

_sender = GraphAPIWhatsAppSender()


@router.get("", response_model=list[ConversationSummary])
async def list_handed_over_conversations(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    message_repo = MessageRepository(db)
    states = await message_repo.list_handed_over_conversations(tenant_id)

    summaries = []
    for state in states:
        messages = await message_repo.list_for_customer(tenant_id, state.customer_id)
        last = messages[-1] if messages else None
        summaries.append(
            ConversationSummary(
                customer_id=state.customer_id,
                customer_name=state.customer.name if state.customer else None,
                customer_phone=state.customer.phone if state.customer else "",
                last_message_at=last.created_at if last else None,
                last_message_preview=last.body[:100] if last else None,
            )
        )
    return summaries


@router.get("/{customer_id}/messages", response_model=list[MessageRead])
async def get_conversation_messages(restaurant_id: uuid.UUID, customer_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    message_repo = MessageRepository(db)
    return await message_repo.list_for_customer(tenant_id, customer_id)


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
    restaurant_repo = RestaurantRepository(db)
    customer_repo = CustomerRepository(db)
    message_repo = MessageRepository(db)

    restaurant = await restaurant_repo.get(tenant_id)
    customer = await customer_repo.get(customer_id, tenant_id)
    if not restaurant or not customer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
    try:
        await _sender.send(
            restaurant.whatsapp_phone_number_id or "", access_token, OutboundMessage.text(customer.phone, payload.body)
        )
    except Exception:
        # Matches app/api/v1/routers/generic_conversations.py's own send_staff_reply --
        # a WhatsApp delivery failure (expired/invalid token, Meta outage, etc.) shouldn't
        # crash the whole request and lose the staff's reply. It's still recorded below so
        # the dashboard reflects what staff sent, even if the customer never received it.
        logger.warning("Legacy live-chat: staff reply send failed for restaurant %s", tenant_id, exc_info=True)

    message = Message(
        restaurant_id=tenant_id,
        customer_id=customer_id,
        direction=MessageDirection.OUTBOUND,
        sent_by=MessageSender.STAFF,
        staff_user_id=user.id,
        body=payload.body[:4096],
    )
    message = await message_repo.create(message)
    await message_repo.commit()
    await ws_manager.broadcast(tenant_id, {"type": "staff_reply", "customer_id": str(customer_id)})
    return message


@router.post("/{customer_id}/resolve", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_conversation(restaurant_id: uuid.UUID, customer_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    result = await db.execute(
        select(ConversationState).where(
            ConversationState.restaurant_id == tenant_id, ConversationState.customer_id == customer_id
        )
    )
    state = result.scalar_one_or_none()
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    state.current_step = ConversationStep.WELCOME
    state.context = {}
    state.assigned_staff_id = None
    await db.commit()
