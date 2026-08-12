import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status

from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import AsyncSessionLocal
from app.models.enums import RestaurantStatus
from app.repositories.restaurant_repository import RestaurantRepository
from app.services.demo_bot_service import handle_demo_inbound
from app.services.flow_engine import InboundInteraction, process_inbound_message, send_unavailable_notice
from app.services.generic_flow_engine import GenericInteraction
from app.services.generic_flow_engine import process_inbound_message as process_generic_inbound_message
from app.services.whatsapp_client import GraphAPIWhatsAppSender

# A restaurant in either of these states doesn't take orders -- see
# app/models/enums.py::RestaurantStatus for what each one means. ONBOARDING is
# deliberately not in this set: a restaurant being configured for the first time can
# still receive real test messages before its owner flips it to ACTIVE.
_BLOCKED_STATUSES = {RestaurantStatus.SUSPENDED, RestaurantStatus.CANCELLED}

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])

# Swap for InMemoryWhatsAppSender in tests / local dev without real Meta credentials.
_sender = GraphAPIWhatsAppSender()


def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.WHATSAPP_APP_SECRET:
        if settings.ENVIRONMENT == "development":
            # No app secret configured yet (credentials not issued) -- allow through so
            # local onboarding can be exercised with simulated payloads before a real
            # WhatsApp App Secret is issued. This path must never be reachable outside
            # development: it accepts any unsigned payload.
            logger.warning(
                "WHATSAPP_APP_SECRET is not configured; accepting UNSIGNED webhook payload "
                "because ENVIRONMENT=development. This is unsafe outside local dev."
            )
            return True
        # Fail closed everywhere else: an unconfigured secret must never be treated as
        # "accept anything".
        logger.error("WHATSAPP_APP_SECRET is not configured; rejecting webhook request (fail closed).")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def _extract_generic_interaction(message: dict, profile_name: str | None) -> GenericInteraction | None:
    """Same payload-shape parsing as _extract_interaction, for a generic-engine
    business -- kept as a separate function (not a shared helper returning a common base)
    since the two interaction dataclasses intentionally belong to fully independent
    engines (see generic_flow_engine.py's module docstring)."""
    msg_type = message.get("type")
    if msg_type == "text":
        return GenericInteraction(kind="text", text=message.get("text", {}).get("body"), profile_name=profile_name)
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "list_reply":
            reply = interactive["list_reply"]
            return GenericInteraction(kind="list_reply", reply_id=reply.get("id"), text=reply.get("title"), profile_name=profile_name)
        if interactive_type == "button_reply":
            reply = interactive["button_reply"]
            return GenericInteraction(kind="button_reply", reply_id=reply.get("id"), text=reply.get("title"), profile_name=profile_name)
    if msg_type == "location":
        loc = message.get("location", {})
        return GenericInteraction(
            kind="location",
            text=loc.get("name") or loc.get("address"),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
            profile_name=profile_name,
        )
    return None


def _extract_interaction(message: dict) -> InboundInteraction | None:
    msg_type = message.get("type")
    if msg_type == "text":
        return InboundInteraction(kind="text", text=message.get("text", {}).get("body"))
    if msg_type == "interactive":
        interactive = message.get("interactive", {})
        interactive_type = interactive.get("type")
        if interactive_type == "list_reply":
            reply = interactive["list_reply"]
            return InboundInteraction(kind="list_reply", reply_id=reply.get("id"), text=reply.get("title"))
        if interactive_type == "button_reply":
            reply = interactive["button_reply"]
            return InboundInteraction(kind="button_reply", reply_id=reply.get("id"), text=reply.get("title"))
    if msg_type == "location":
        loc = message.get("location", {})
        return InboundInteraction(
            kind="location",
            text=loc.get("name") or loc.get("address"),
            latitude=loc.get("latitude"),
            longitude=loc.get("longitude"),
        )
    return None


@router.get("")
async def verify_webhook(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hmac.compare_digest(hub_verify_token, settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")


@router.post("")
# Generous ceiling: Meta calls this from a small, fixed set of their own IPs carrying
# real customer traffic for every restaurant on the platform, so this exists to block
# abuse/flood (a spoofed/misbehaving caller hammering the endpoint), not to throttle
# normal volume.
@limiter.limit("60/minute")
async def receive_webhook(request: Request, x_hub_signature_256: str | None = Header(default=None)):
    raw_body = await request.body()
    if not _verify_signature(raw_body, x_hub_signature_256):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")
            messages = value.get("messages", [])
            if not phone_number_id or not messages:
                continue  # status/delivery-receipt events, or malformed payload -- ignore

            async with AsyncSessionLocal() as session:
                repo = RestaurantRepository(session)
                restaurant = await repo.get_by_whatsapp_phone_number_id(phone_number_id)
                if not restaurant:
                    logger.warning("Webhook received for unknown phone_number_id=%s", phone_number_id)
                    continue

                if restaurant.status in _BLOCKED_STATUSES:
                    # Suspended (subscription lapsed) or cancelled (left the platform) --
                    # the bot stops taking orders, but nothing about the restaurant's
                    # config/history is touched, so reactivating just flips the status
                    # back. Reply once per inbound message rather than the customer
                    # getting silence, but skip process_inbound_message entirely: no
                    # ConversationState, no order, no side effect of any kind.
                    from_phone = messages[0].get("from") if messages else None
                    if from_phone:
                        await send_unavailable_notice(_sender, restaurant, from_phone)
                    continue

                if restaurant.is_demo:
                    # The one Demo Bot number -- see app/services/demo_bot_service.py for
                    # why this can't just be `process_generic_inbound_message` directly
                    # (one real WhatsApp number, but N independent niche demos behind it).
                    # Same interaction-parsing as any other generic-engine business: a
                    # demo restaurant is an ordinary uses_generic_engine=True row.
                    profile_name = None
                    contacts = value.get("contacts") or []
                    if contacts:
                        profile_name = contacts[0].get("profile", {}).get("name")
                    for message in messages:
                        generic_interaction = _extract_generic_interaction(message, profile_name)
                        if generic_interaction is None:
                            continue
                        from_phone = message.get("from")
                        if not from_phone:
                            continue
                        await handle_demo_inbound(
                            session, _sender, restaurant, from_phone, generic_interaction, wa_message_id=message.get("id")
                        )
                    continue

                if restaurant.uses_generic_engine:
                    # WhatsApp includes the sender's profile display name once per
                    # webhook `value`, not per message -- captured here so the "auto-pull
                    # name, editable" steps (see generic_flow_engine.py) have something
                    # real to seed from instead of a placeholder claim.
                    profile_name = None
                    contacts = value.get("contacts") or []
                    if contacts:
                        profile_name = contacts[0].get("profile", {}).get("name")
                    for message in messages:
                        generic_interaction = _extract_generic_interaction(message, profile_name)
                        if generic_interaction is None:
                            continue
                        from_phone = message.get("from")
                        if not from_phone:
                            continue
                        await process_generic_inbound_message(
                            session, _sender, restaurant, from_phone, generic_interaction, wa_message_id=message.get("id")
                        )
                    continue

                for message in messages:
                    interaction = _extract_interaction(message)
                    if interaction is None:
                        continue
                    from_phone = message.get("from")
                    if not from_phone:
                        continue
                    wa_message_id = message.get("id")
                    await process_inbound_message(
                        session, _sender, restaurant, from_phone, interaction, wa_message_id=wa_message_id
                    )

    return {"status": "ok"}
