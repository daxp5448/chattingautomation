"""Dispatcher for the Demo Bot's one WhatsApp number (Phase 1 Item 4): "Hi" -> select
industry -> run a complete demo of that niche -> try another industry.

Architecture: the webhook only ever resolves ONE Restaurant per real WhatsApp number
(Restaurant.whatsapp_phone_number_id is DB-unique -- see app/api/v1/routers/webhook.py),
but the demo needs N independent niche flows behind that one number, with real isolation
between two prospects demoing concurrently. Resolved by giving every niche its own
ordinary demo Restaurant (auto-provisioned by app/services/demo_restaurant_sync.py, full
reuse of the real generic-engine machinery -- Customer/GenericConversationState/Engagement
are already restaurant_id-scoped, so two different phone numbers on the same niche get two
independent Customer rows and never collide), and this module's only job is remembering,
per real phone number, which niche's demo restaurant is currently active (DemoSession) and
handing every message that isn't "show me the picker" straight to the UNMODIFIED
generic_flow_engine.process_inbound_message -- this file contains no flow-walking logic
of its own.
"""

import logging
import re

from sqlalchemy import select

from app.models.demo_session import DemoSession
from app.models.enums import MessageDirection, MessageSender
from app.models.message import Message
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.repositories.customer_repository import CustomerRepository
from app.repositories.demo_session_repository import DemoSessionRepository
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.services.generic_flow_engine import (
    GenericInteraction,
    process_inbound_message,
    send_generic_message,
    send_generic_messages_batch,
)
from app.services.whatsapp_client import OutboundMessage, WhatsAppSender

logger = logging.getLogger(__name__)

# Explicit "leave this niche's demo and go back to the industry picker" signal. Plain "hi"
# typed WHILE inside an active niche demo is deliberately NOT included here -- it falls
# through to the engine's own existing greeting-reset behavior (generic_flow_engine.py's
# _looks_like_greeting), which just restarts that same niche, the more natural "this is
# what a real customer would experience" behavior for a demo.
_LEAVE_TO_PICKER_WORDS = {"menu", "industries", "industry", "other industry", "switch"}
_PICK_PREFIX = "demo:pick:"
_MENU_REPLY_ID = "demo:menu"


async def _already_processed(session, wa_message_id: str | None) -> bool:
    if not wa_message_id:
        return False
    result = await session.execute(select(Message).where(Message.wa_message_id == wa_message_id))
    return result.scalar_one_or_none() is not None


async def _log_inbound(session, sentinel_restaurant: Restaurant, customer_id, from_phone: str, interaction: GenericInteraction, wa_message_id: str | None) -> None:
    body = interaction.text or interaction.reply_id or "[unsupported message]"
    session.add(
        Message(
            restaurant_id=sentinel_restaurant.id,
            customer_id=customer_id,
            direction=MessageDirection.INBOUND,
            sent_by=MessageSender.CUSTOMER,
            body=body[:4096],
            wa_message_id=wa_message_id,
        )
    )
    await session.flush()


async def _active_niche_templates(session, sentinel_restaurant: Restaurant) -> list[NicheTemplate]:
    """The filtered, ordered niche list both _send_industry_picker (what a customer is
    shown, numbered) and _resolve_free_text_pick (what a numeric reply resolves against)
    must agree on -- shared here so the Nth item shown is always the Nth item a reply of
    "N" picks. demo_enabled_niche_codes narrows the picker to a Super Admin's own selection
    (see app/models/restaurant.py -- used both by demo-mode-toggled real businesses like
    Prince Corner and, in principle, the sentinel Demo Bot restaurant itself). None means
    "no restriction configured" -- every niche with a synced template shows.
    """
    templates = await NicheTemplateRepository(session).list_all()
    enabled_codes = sentinel_restaurant.demo_enabled_niche_codes
    if enabled_codes is not None:
        templates = [t for t in templates if t.code in set(enabled_codes)]
    return templates


def _resolve_free_text_pick(templates: list[NicheTemplate], text: str) -> str | None:
    """Meta caps a WhatsApp interactive list at 10 rows TOTAL (not per section), and the
    platform already has 12+ niches -- a tap-to-select list would either silently drop
    niches past the 10th or force paging across multiple messages (both tried before, both
    rejected: see git history). _send_industry_picker instead sends every niche as one
    plain numbered text message, so picking one has to work via free-text reply: a bare
    number ("3"), or the niche's own name/code, matched case-insensitively.

    Deliberately word-boundary-prefix matching ("jewel" -> a word in "Jewellers" starts
    with it), NEVER a bare substring-anywhere search -- a naive `"hi" in name.lower()`
    check once matched the plain greeting "hi" against "Education & Coa*chi*ng" and
    silently hijacked every ordinary "hi" into auto-picking that niche instead of ever
    showing the picker. The len>=3 floor is extra insurance against short common words
    (greetings, "ok", "no") ever resolving to a pick by accident.
    """
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        idx = int(text)
        return templates[idx - 1].code if 1 <= idx <= len(templates) else None
    text_lower = text.lower()
    for t in templates:
        if text_lower == t.name.lower() or text_lower == t.code.lower():
            return t.code
    if len(text_lower) < 3:
        return None
    for t in templates:
        words = [w for w in re.split(r"[^a-z0-9]+", t.name.lower()) if w]
        if any(w.startswith(text_lower) for w in words):
            return t.code
    return None


def _welcome_banner_messages(sentinel_restaurant: Restaurant, from_phone: str) -> list[OutboundMessage]:
    """KelvionTech branding shown before the industry picker -- deliberately read from the
    sentinel restaurant's existing logo_url/cover_image_url fields (same ones editable on
    its own Settings page) rather than hardcoded here, so changing the demo's branding is
    an admin-panel edit, not a code deploy. Either/both being unset (e.g. before an admin
    has configured them) just skips that image -- never blocks the picker from showing.
    Returns the messages to send rather than sending them itself, so the caller can batch
    them together with the picker text via send_generic_messages_batch, which guarantees
    every image here arrives before the text (sequential dispatch, not concurrent -- see
    that function's own docstring for why).
    """
    messages = []
    if sentinel_restaurant.logo_url:
        messages.append(OutboundMessage.image(from_phone, sentinel_restaurant.logo_url, "👋 Welcome to KelvionTech!"))
    if sentinel_restaurant.cover_image_url:
        messages.append(OutboundMessage.image(
            from_phone, sentinel_restaurant.cover_image_url,
            "One WhatsApp Business OS, any industry -- pick yours below to get started 👇",
        ))
    return messages


async def _send_industry_picker(session, sender: WhatsAppSender, sentinel_restaurant: Restaurant, customer_id, from_phone: str) -> None:
    banner_messages = _welcome_banner_messages(sentinel_restaurant, from_phone)
    templates = await _active_niche_templates(session, sentinel_restaurant)
    if not templates:
        await send_generic_messages_batch(
            session, sender, sentinel_restaurant, customer_id, from_phone,
            [*banner_messages, OutboundMessage.text(from_phone, "No industries are configured yet -- please check back soon.")],
        )
        return
    # One plain-text message, every niche in it -- see _resolve_free_text_pick's docstring
    # for why this isn't a tap-to-select interactive list (Meta's 10-row cap).
    lines = [f"{i}. {t.icon + ' ' if t.icon else ''}{t.name}" for i, t in enumerate(templates, start=1)]
    body = (
        "👋 *Welcome to the KelvionTech Business OS!*\n"
        "Reply with a *number* to explore that industry's WhatsApp bot:\n\n"
        + "\n".join(lines)
    )
    await send_generic_messages_batch(
        session, sender, sentinel_restaurant, customer_id, from_phone,
        [*banner_messages, OutboundMessage.text(from_phone, body)],
    )


async def _get_demo_restaurant_by_niche(session, niche_code: str) -> Restaurant | None:
    result = await session.execute(
        select(Restaurant).where(Restaurant.niche_type == niche_code, Restaurant.is_demo.is_(True))
    )
    return result.scalar_one_or_none()


async def handle_demo_inbound(
    session,
    sender: WhatsAppSender,
    sentinel_restaurant: Restaurant,
    from_phone: str,
    interaction: GenericInteraction,
    wa_message_id: str | None = None,
) -> None:
    if await _already_processed(session, wa_message_id):
        return

    demo_session = await DemoSessionRepository(session).get_or_create_for_update(from_phone)

    reply_id = interaction.reply_id or ""
    text_norm = (interaction.text or "").strip().lower()
    is_leave_signal = reply_id == _MENU_REPLY_ID or text_norm in _LEAVE_TO_PICKER_WORDS
    is_button_pick = reply_id.startswith(_PICK_PREFIX)
    # Free-text pick ("3", "Jewellery") only makes sense while no niche is active yet and
    # the message isn't itself a leave-signal word -- never attempted mid-niche (that
    # branch is further below, untouched) so ordinary conversation text inside a niche
    # (e.g. answering "3" to "how many would you like?") is never misread as a re-pick.
    text_pick_code: str | None = None
    if demo_session.active_restaurant_id is None and not is_leave_signal and not is_button_pick:
        active_templates = await _active_niche_templates(session, sentinel_restaurant)
        text_pick_code = _resolve_free_text_pick(active_templates, interaction.text or "")
    is_pick = is_button_pick or text_pick_code is not None

    if demo_session.active_restaurant_id is None or is_leave_signal or is_pick:
        # None of these three branches ever delegates the REAL wa_message_id into
        # process_inbound_message (a fresh pick synthesizes its own separate, unlogged
        # "hi" below) -- so this is the one place responsible for logging + deduping the
        # actual inbound webhook message, under a Customer scoped to the sentinel
        # restaurant (Message.customer_id is NOT NULL and there's no niche restaurant to
        # scope it to yet).
        sentinel_customer = await CustomerRepository(session).get_or_create(sentinel_restaurant.id, from_phone)
        await _log_inbound(session, sentinel_restaurant, sentinel_customer.id, from_phone, interaction, wa_message_id)

        if is_pick:
            niche_code = reply_id.removeprefix(_PICK_PREFIX) if is_button_pick else text_pick_code
            demo_restaurant = await _get_demo_restaurant_by_niche(session, niche_code)
            if demo_restaurant is None:
                logger.warning("Demo Bot: unknown/stale niche code in pick niche_code=%s", niche_code)
                await _send_industry_picker(session, sender, sentinel_restaurant, sentinel_customer.id, from_phone)
                await session.commit()
                return

            # The clean template name ("Retail & Fashion"), not demo_restaurant.name (which
            # is literally "Demo — Retail & Fashion" -- see demo_restaurant_sync.py) --
            # that internal naming is fine for the Super Admin's own restaurant list, but
            # would leak the word "Demo" straight into this customer-facing message
            # regardless of how the picker itself is worded.
            niche_template = await NicheTemplateRepository(session).get_by_code(niche_code)
            display_name = niche_template.name if niche_template else demo_restaurant.name

            demo_session.active_restaurant_id = demo_restaurant.id
            if demo_restaurant.demo_sends_via_restaurant_id != sentinel_restaurant.id:
                # Self-heals demo_sends_via_restaurant_id (see
                # app/services/demo_restaurant_sync.py) to whichever real number this
                # customer actually entered through -- necessary now that a demo restaurant
                # can be reached via more than one sentinel over its lifetime (the original
                # sentinel Demo Bot restaurant, or any real business toggled into Demo Mode
                # via demo_mode_enabled). Without this, send_generic_message would keep
                # resolving credentials off whichever sentinel provisioned this niche
                # first, and outbound messages would silently fail to send through a
                # different, currently-active number. Known narrow tradeoff: if two
                # different real numbers are BOTH actively demoing the same niche to two
                # different prospects at the same moment, whichever one sends last "wins"
                # credential routing for that niche until the other's next turn re-flips
                # it back -- not reachable today (only one number is ever in Demo Mode at
                # a time in practice), flagged here rather than silently accepted.
                demo_restaurant.demo_sends_via_restaurant_id = sentinel_restaurant.id
            await session.flush()
            await send_generic_message(
                session, sender, sentinel_restaurant, sentinel_customer.id, from_phone,
                OutboundMessage.text(
                    from_phone,
                    f"🌐 Welcome to *{display_name}*! Type *menu* anytime to explore another industry.",
                ),
            )
            await session.commit()
            # Rides the engine's own existing greeting-reset behavior to render this
            # niche's entry step -- see the cross-reference comment on
            # generic_flow_engine.py::_looks_like_greeting. wa_message_id=None: the real
            # inbound message was already logged+deduped above under the sentinel scope.
            await process_inbound_message(
                session, sender, demo_restaurant, from_phone, GenericInteraction(kind="text", text="hi"), wa_message_id=None
            )
            return

        # A fresh session (never picked anything) or an explicit "menu"/"industries" leave
        # signal -- either way, no niche is active until the next pick. Clearing this
        # explicitly (rather than leaving a stale pointer in place) makes a plain "hi"
        # typed after seeing the picker but before picking re-show the picker again,
        # instead of silently resuming whatever niche was active before "menu" was typed.
        demo_session.active_restaurant_id = None
        await _send_industry_picker(session, sender, sentinel_restaurant, sentinel_customer.id, from_phone)
        await session.commit()
        return

    demo_restaurant = await session.get(Restaurant, demo_session.active_restaurant_id)
    if demo_restaurant is None:
        # Dangling pointer -- shouldn't happen (demo restaurants are never deleted by this
        # feature), but fall back to the picker rather than erroring on a stale session.
        demo_session.active_restaurant_id = None
        sentinel_customer = await CustomerRepository(session).get_or_create(sentinel_restaurant.id, from_phone)
        await _log_inbound(session, sentinel_restaurant, sentinel_customer.id, from_phone, interaction, wa_message_id)
        await _send_industry_picker(session, sender, sentinel_restaurant, sentinel_customer.id, from_phone)
        await session.commit()
        return

    # Already mid-demo, not a leave signal -- delegate straight into the real engine,
    # completely unmodified. It does its own inbound Message logging (scoped to this
    # niche's own demo restaurant/customer) and its own wa_message_id dedup check.
    await process_inbound_message(session, sender, demo_restaurant, from_phone, interaction, wa_message_id)
