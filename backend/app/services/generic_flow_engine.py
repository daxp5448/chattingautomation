"""The niche-agnostic WhatsApp conversation engine every business on the generic
platform runs (Restaurant.uses_generic_engine=True) -- see app/models/flow_definition.py
for the exact shape a flow's `steps` list is stored in, and the architecture review's
Part E for the design rationale.

This file is completely independent of app/services/flow_engine.py (the original,
restaurant-only engine): no shared imports of restaurant-specific models (Product,
Order, ConversationStep), no shared state table. A business either runs entirely on the
legacy path or entirely on this one (app/api/v1/routers/webhook.py's routing switch),
never both -- see Restaurant.uses_generic_engine's docstring for why.

## The step types (FlowStepType)
The original five -- everything every niche needs, built from just these:
  - message: pure informational render, no input expected (used for terminal
    confirmation steps only -- everything else that shows text also offers buttons/lists,
    so it's a menu_select with a single option, not a bare message).
  - menu_select: render a list/buttons from a data source, capture the tapped option.
    The visual Flow Builder's "buttons" and "list" nodes are BOTH this type -- see
    _send_options's <=3-vs->3 threshold; which rendering Meta gets is option-count-driven,
    not a distinct step type.
  - quantity_input: 1/2/3/Custom buttons; "Custom" prompts a one-off numeric reply (the
    one quantity-specific exception to "no bare free text" -- there's no reasonable
    button set for an arbitrary quantity).
  - free_text_input: a genuinely optional note (cooking instructions, inquiry message,
    vehicle number) -- always paired with a Skip button per the global rule.
  - confirm_action: the step that actually creates the Engagement. The visual Flow
    Builder's "payment" node is ALSO this type with `action: "create_engagement_paid"` --
    that verb is currently identical code to plain "create_engagement" (see _run_action);
    presenting it as a distinct node is a UI/naming layer only, not a runtime behavior
    split, since real payment-vs-not is already driven by cart/total state.

Phase 2 Item 3 (Drag & Drop Flow Builder) additions -- see _AUTO_ADVANCE_TYPES and
_advance_and_render for how the first four of these run without waiting for customer
input:
  - condition: evaluate {context_key, operator, value} against state.context, branch to
    then_step or else_step. `operator` is a closed whitelist, never eval().
  - delay: sleep up to a shared, chain-wide budget (see _MAX_TOTAL_BLOCKING_SECONDS) then
    continue to `next` -- an in-turn pause, not a real-world "wait a day" (that would need
    background-scheduled resumption, out of scope here).
  - api_call: call a Super-Admin-curated ApiEndpoint (see app/models/api_endpoint.py /
    app/services/api_endpoint_client.py), capture the response, continue to `next`.
  - ai_response: a placeholder until the AI Knowledge Base item ships -- sends a graceful
    "not configured yet" message and continues to `next`.
  - human_handoff: sets GenericConversationState.is_handed_over, pausing all automation
    until staff resume it via app/api/v1/routers/generic_conversations.py -- terminal for
    the engine, not auto-advancing.

## Images: a real WhatsApp API constraint, handled honestly
Meta's interactive list/button messages are text-only per row -- there is no per-row
image field in the Graph API. "Every category and item shows an image" is satisfied
within that real constraint by sending one IMAGE message (the category's or first
item's photo, captioned with every option's name + price) immediately before the
selection list/buttons -- see `_send_options`. A single-item DETAIL view (already just
one thing, not a list) sends that item's own image directly with no compromise needed.

## Back-navigation
Every step in a flow carries an explicit `back_target`. The reserved reply id
`__back__` is intercepted before normal dispatch, jumps `current_step` to that target,
and re-renders it through the exact same `_render_step` forward-navigation uses --
never a special "undo" code path. Context is only ever overwritten, never popped, so
prior selections survive a back-and-forth.
"""

import asyncio
import logging
import random
import re
import string
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from cachetools import TTLCache
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.models.customer import Customer
from app.models.engagement import Engagement, EngagementItem
from app.models.enums import EngagementStatus, EngagementType, MessageDirection, MessageSender
from app.models.jewellery_design import JewelleryDesign
from app.models.message import Message
from app.models.restaurant import Restaurant
from app.repositories.catalog_repository import CatalogCategoryRepository, CatalogItemRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.engagement_repository import EngagementRepository
from app.repositories.flow_definition_repository import FlowDefinitionRepository
from app.services import analytics, conversation_lexicon
from app.services.conversational_intent import _best_phrase_score, _normalize as _normalize_for_intent, resolve_interaction
from app.services.conversational_style import humanize
from app.repositories.generic_conversation_repository import GenericConversationStateRepository
from app.repositories.jewellery_design_repository import JewelleryDesignRepository
from app.repositories.meta_media_cache_repository import MetaMediaCacheRepository
from app.repositories.staff_member_repository import StaffMemberRepository
from app.services.image_presenter import (
    resolve_category_images,
    resolve_category_images_bulk,
    resolve_item_images,
    resolve_item_images_bulk,
    resolve_step_images,
)
from app.services.meta_media_upload import MEDIA_ID_FRESHNESS_DAYS, schedule_background_upload
from app.services.notification_service import notify_business
from app.services.template_engine import render_template
from app.services.whatsapp_client import GraphAPIWhatsAppSender, OutboundMessage, WhatsAppSender

logger = logging.getLogger(__name__)

BACK_REPLY_ID = "__back__"
SKIP_REPLY_ID = "__skip__"
# Jewellery-only carousel feature (Material -> Category -> paginated Design gallery, see
# JewelleryDesignRepository / _render_jewellery_gallery below): the one new reserved
# control id, handled the same way BACK_REPLY_ID is -- intercepted in handle() before
# normal _process_input dispatch, since "load the next page" isn't a catalog option any
# step's _resolve_options would ever return. Every other niche's flow never emits this
# id, so this is a no-op for them.
JEWELLERY_LOAD_MORE_REPLY_ID = "__jewellery_more__"

# interaction.kind="unhandled_media" (see GenericInteraction.media_kind and handle()) --
# a polite, context-appropriate acknowledgement instead of the total silence these message
# types got before this existed. Never advances/resets state: the customer stays exactly
# where they were and can keep going. Unrecognized media_kind values (a WhatsApp message
# type not in this map) fall back to _MEDIA_FALLBACK_DEFAULT.
_MEDIA_FALLBACK_MESSAGES = {
    "image": "📸 We received your image. An executive will review it shortly!",
    "video": "🎥 We received your video. An executive will review it shortly!",
    "audio": "🎤 We received your voice note. An executive will review it shortly!",
    "document": "📄 We received your document. An executive will review it shortly!",
    "sticker": "😄 Thanks for the sticker! Type *menu* any time to see our options.",
    "order": "🛒 We received your order request. Our team will confirm the details with you shortly!",
}
_MEDIA_FALLBACK_DEFAULT = "We received your message. Type *menu* any time to see our options."

# "menu" used to be in this set and was a real bug: a restaurant (or any niche's)
# customer mid-conversation who typed "menu" wanting to see options/the food menu again
# -- an entirely ordinary thing to type -- had their whole conversation silently reset to
# welcome instead, discarding an in-progress cart/order/enquiry. Only words that are
# essentially never a plausible mid-conversation utterance with some OTHER meaning stay
# here.
_GREETING_WORDS = {"hi", "hello", "hey", "heyy", "hii", "hola", "halo", "start", "yo", "sup", "namaste"}
# Fuzzy-typo tolerance is deliberately an explicit, hand-picked list, NOT everything in
# _GREETING_WORDS above length 4 -- e.g. "start" is excluded on purpose: at edit-distance
# 1 it also matches "smart"/"stark"/"stare", real words a customer could plausibly type
# (a niche selling "smart" devices, say), and this file has already been bitten once by
# an accidental-reset regression from an over-eager greeting match (see "menu" above).
# "hello"/"namaste" are distinctive enough that a distance-1 neighbor is essentially
# always a genuine typo, not real content.
_FUZZY_GREETING_WORDS = {"hello", "namaste"}


def _levenshtein_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    previous_row = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current_row = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            current_row[j] = min(
                previous_row[j] + 1,  # deletion
                current_row[j - 1] + 1,  # insertion
                previous_row[j - 1] + (ca != cb),  # substitution
            )
        previous_row = current_row
    return previous_row[-1]

# The manually-built "quick customize" WhatsApp Flow's own hardcoded dropdown options
# (see Restaurant.whatsapp_quick_customize_flow_id's docstring) -- it's a single static
# screen with fixed generic choices, not dynamic per-catalog-item data, so this mapping
# is the Flow's actual, verified content (fetched directly from Meta's Graph API), not a
# guess. Used only to turn the submitted "ITEM_1"/"ITEM_2"/"ITEM_3" id into a readable
# {{quick_customize_item_label}} for a niche's own confirmation prompt template.
_QUICK_CUSTOMIZE_ITEM_LABELS = {
    "ITEM_1": "Standard Option",
    "ITEM_2": "Premium Option",
    "ITEM_3": "Custom Option",
}
_PLACEHOLDER_IMAGE = "https://placehold.co/600x400?text={label}"
# Photo-burst ceiling (see _photo_burst_urls / _send_options): a category can override
# via step["photo_burst_max"] (a plain flow-step field, already editable via Flow
# Builder/default_flow_steps like any other step property -- nothing new to build for
# that knob). Kept low by default so a large catalog doesn't spam a customer with N
# image messages before they even see the picker.
_PHOTO_BURST_MAX_DEFAULT = 6

# --- Phase 2 Item 3 (Drag & Drop Flow Builder): auto-advancing step types --------------
# These 4 step types run without waiting for customer input -- see _advance_and_render,
# the single chokepoint every render call site (there are 4: handle()'s greeting-reset,
# handle()'s __back__ handling, _process_input's unrecognized-input fallback, and
# _advance's forward-navigation) goes through, so a back_target/entry-step pointing at
# one of these is handled correctly too, not just the common forward-navigation path.
# Kept in sync with app/services/flow_shape_validation.py's own copy of this set.
_AUTO_ADVANCE_TYPES = {"condition", "delay", "api_call", "ai_response"}
_MAX_AUTO_ADVANCE_HOPS = 10
# Shared budget across every DELAY sleep AND API_CALL timeout within ONE auto-advance
# chain (not a per-step cap) -- process_inbound_message holds a FOR UPDATE lock on
# GenericConversationState (and a pooled DB connection) for the whole webhook request,
# so this bounds how long a chain can hold that lock/connection to a small, predictable
# window rather than a rare long-tail stall. See flow_shape_validation.py's
# MAX_DELAY_SECONDS_PER_STEP for the complementary per-step sanity ceiling checked at
# save time.
_MAX_TOTAL_BLOCKING_SECONDS = 5.0

# In-memory fast-path for redelivered wa_message_ids -- Meta redelivers a webhook when it
# doesn't see our 200 fast enough, so the exact-duplicate case is common, not rare. This
# is purely an ADDITIONAL fast path in front of the real dedup below (the DB SELECT +
# Message.wa_message_id's actual unique constraint, which remains the source of truth):
# a cache miss just falls through to that unchanged existing check, so losing this cache
# entirely (process restart, eviction) can never cause a duplicate send, only a slightly
# slower rejection of a dupe. maxsize bounds memory under sustained traffic; ttl only
# needs to outlast Meta's redelivery window (a small number of seconds in practice).
_recent_wa_message_ids: TTLCache = TTLCache(maxsize=10_000, ttl=300)

# EngagementType -> the funnel event _create_engagement fires at the start/success of a
# confirm_action, per app/services/analytics.py's vocabulary. ORDER has no distinct
# *_COMPLETED event (FLOW_COMPLETED, fired from _render_step's terminal-step check,
# covers it) -- see analytics.py's module docstring for the full reasoning.
_STARTED_EVENT_BY_ENGAGEMENT_TYPE = {
    EngagementType.ORDER: analytics.CHECKOUT_STARTED,
    EngagementType.APPOINTMENT: analytics.BOOKING_STARTED,
    EngagementType.BOOKING: analytics.BOOKING_STARTED,
    EngagementType.INQUIRY: analytics.LEAD_STARTED,
}
_COMPLETED_EVENT_BY_ENGAGEMENT_TYPE = {
    EngagementType.APPOINTMENT: analytics.BOOKING_COMPLETED,
    EngagementType.BOOKING: analytics.BOOKING_COMPLETED,
    EngagementType.INQUIRY: analytics.LEAD_COMPLETED,
}


def _to_number(value: Any) -> float:
    return float(value)


_CONDITION_OPERATORS = {
    # Deliberately a closed whitelist, not a general expression/eval() language -- see
    # app/models/flow_definition.py's docstring for the exact {context_key, operator,
    # value} shape a CONDITION step's `condition` field carries.
    "equals": lambda a, b: a == b,
    "not_equals": lambda a, b: a != b,
    "greater_than": lambda a, b: _to_number(a) > _to_number(b),
    "less_than": lambda a, b: _to_number(a) < _to_number(b),
    "contains": lambda a, b: a is not None and b in a,
}


# app/services/demo_bot_service.py relies on this treating "hi" as a reset-to-entry-step
# signal: it synthesizes a fake "hi" GenericInteraction to render a niche's entry step
# right after a demo customer picks that niche, rather than duplicating a "just render
# the entry step" code path. Changing this word list/logic affects that too.
def _looks_like_greeting(text: str) -> bool:
    # Bug fixed here: stripping non-letter characters before checking for emptiness used
    # to mean ANY reply with no Latin letters at all -- a bare number ("5", typed as a
    # custom quantity), an emoji, or text in a non-Latin script -- normalized down to "",
    # which `if not normalized: return True` then treated as "looks like a greeting" and
    # reset the WHOLE conversation back to the entry step. That's the exact mechanism
    # behind "I typed a custom quantity number and it restarted from the beginning" --
    # reproducible on every niche, since this check runs unconditionally on every inbound
    # text message before any per-step handling. Only a genuinely blank/whitespace-only
    # message counts as empty now; a message with real content but no Latin letters falls
    # through to per-step processing like it always should have.
    if not text or not text.strip():
        return True
    normalized = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    if not normalized:
        return False
    words = normalized.split()
    if len(words) <= 2 and all(w in _GREETING_WORDS for w in words):
        return True
    # Typo tolerance -- deliberately scoped to a single-word message only (not the <=2
    # word case above): a genuine two-word reply with one accidentally-fuzzy-matching
    # word is far more likely to be real content ("start budget"?) than a typo'd
    # greeting, so only a lone word gets the fuzzy check.
    if len(words) == 1 and len(words[0]) >= 4:
        return any(_levenshtein_distance(words[0], w) <= 1 for w in _FUZZY_GREETING_WORDS)
    return False


def _looks_like_restart(text: str) -> bool:
    """"start again"/"restart"/"shuru se" etc (conversation_lexicon.RESTART_PHRASES) --
    a SEPARATE check from _looks_like_greeting (not folded into it) so this module's
    only other caller, demo_bot_service.py, is completely unaffected: it imports
    _looks_like_greeting specifically for its own "hi mid-niche restarts that niche"
    behavior, which must not gain this new phrase set as a side effect."""
    if not text or not text.strip():
        return False
    normalized = _normalize_for_intent(text)
    return bool(normalized) and _best_phrase_score(normalized, conversation_lexicon.RESTART_PHRASES) >= conversation_lexicon.INTENT_MATCH_THRESHOLD


@dataclass
class GenericInteraction:
    kind: str  # "text" | "list_reply" | "button_reply" | "location" | "flow_reply" | "unhandled_media"
    text: str | None = None
    reply_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    profile_name: str | None = None
    # kind="flow_reply" only -- the parsed `response_json` object from a static WhatsApp
    # Flow's `nfm_reply` webhook message (see webhook.py's nfm_reply handling and
    # Restaurant.whatsapp_quick_customize_flow_id's docstring for which Flow shape this
    # is). Whatever field names/values the Flow's own "on-click-action" payload defines --
    # this engine doesn't assume specific keys beyond what the send_quick_customize_flow
    # step type itself reads.
    flow_response: dict[str, Any] | None = None
    # kind="unhandled_media" only -- the raw WhatsApp message `type` (see webhook.py's
    # _extract_generic_interaction), e.g. "image"/"video"/"audio"/"document"/"sticker"/
    # "order". Before this field existed, any of these message types fell through
    # _extract_generic_interaction returning None and the webhook silently dropped them --
    # a customer sending a photo or voice note got no reply at all. See handle()'s
    # _MEDIA_FALLBACK_MESSAGES for the acknowledgement sent instead.
    media_kind: str | None = None


def _reference_number(restaurant: Restaurant, engagement_type: EngagementType) -> str:
    prefix = "".join(ch for ch in restaurant.slug.upper() if ch.isalnum())[:4] or "BIZ"
    type_code = engagement_type.value[:3].upper()
    date_part = datetime.now(timezone.utc).strftime("%y%m%d")
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{prefix}-{type_code}-{date_part}-{suffix}"


async def process_inbound_message(
    session,
    sender: WhatsAppSender,
    restaurant: Restaurant,
    from_phone: str,
    interaction: GenericInteraction,
    wa_message_id: str | None = None,
    dry_run: bool = False,
) -> None:
    """Entry point called by webhook.py for every generic-engine business's inbound
    message -- the direct counterpart of flow_engine.py::process_inbound_message.

    `dry_run=True` is used exclusively by the Super Admin Bot Preview simulator (see
    app/api/v1/routers/flow_preview.py) -- runs every real step/message/catalog/variable
    lookup through this exact function (never a separate fake preview engine), but never
    creates a real Engagement/payment/staff-notification and never records a real
    analytics event or live-chat broadcast (see `_Engine.dry_run`). The preview's own
    Customer/GenericConversationState/Message rows ARE real and persisted (so a
    multi-turn preview conversation has somewhere to keep its place between HTTP
    requests) -- they simply belong to a synthetic, never-a-real-phone-number customer
    the router creates, so they can never collide with or be mistaken for real traffic.
    """
    message_repo = _GenericMessageRepo(session)
    if wa_message_id:
        if wa_message_id in _recent_wa_message_ids:
            # Fast path hit -- skip the DB round-trip entirely for a redelivery we've
            # already durably recorded. A miss here (cold cache, evicted, different
            # process) just falls through to the exact same check as before.
            return
        existing = await message_repo.get_by_wa_message_id(wa_message_id)
        if existing is not None:
            return

    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_or_create(restaurant.id, from_phone)
    if interaction.profile_name and not customer.name:
        # Seeds a default the "auto-pull name, editable" steps show -- never overwrites a
        # name the customer or staff already set.
        customer.name = interaction.profile_name

    state_repo = GenericConversationStateRepository(session)
    # Locks the row for the duration of this transaction -- same reasoning as
    # flow_engine.py's ConversationState lock: two concurrent/redelivered webhook events
    # for the same customer serialize instead of both advancing the same pre-transition step.
    state = await state_repo.get_for_update_by_customer(customer.id)
    flow_repo = FlowDefinitionRepository(session)
    flow_def = await flow_repo.get_by_restaurant(restaurant.id)
    if state is None:
        from app.models.generic_conversation_state import GenericConversationState

        state = GenericConversationState(
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            current_step=flow_def.entry_step_id if flow_def else "welcome",
            context={},
        )
        session.add(state)
        await session.flush()
        if not dry_run:
            analytics.record_event(
                session, restaurant.id, analytics.FLOW_STARTED,
                customer_id=customer.id, niche_code=flow_def.niche_code if flow_def else restaurant.niche_type,
            )

    inbound_body = interaction.text or interaction.reply_id or "[unsupported message]"
    session.add(
        Message(
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            direction=MessageDirection.INBOUND,
            sent_by=MessageSender.CUSTOMER,
            body=inbound_body[:4096],
            wa_message_id=wa_message_id,
        )
    )
    if wa_message_id:
        # Closes the race the plain existence-check above (line ~183) can't: two workers
        # racing to process a genuinely-concurrent redelivery of the SAME wa_message_id
        # can both pass that SELECT before either has inserted a row. Message.wa_message_id
        # is a real unique DB constraint, so the loser's flush raises IntegrityError here --
        # caught and treated as "someone else already claimed this inbound message" (the
        # same outcome as the early-return above), rather than an unhandled 500 AND,
        # crucially, BEFORE engine.handle() below has sent a single outbound message, so
        # the loser can never produce a duplicate customer-visible send.
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            logger.info("Duplicate concurrent wa_message_id=%s -- another worker already claimed it", wa_message_id)
            return
    else:
        await session.flush()

    if flow_def is None:
        await send_generic_message(session, sender, restaurant, customer.id, from_phone, OutboundMessage.text(
            from_phone, "This business hasn't finished setting up its WhatsApp bot yet. Please check back soon."
        ))
        await session.commit()
        if wa_message_id:
            _recent_wa_message_ids[wa_message_id] = True
        return

    engine = _Engine(session, sender, dry_run=dry_run)
    await engine.handle(restaurant, customer, state, from_phone, flow_def, interaction)
    await session.commit()
    if wa_message_id:
        # Marked only after a successful commit -- if anything above raised/rolled back,
        # the DB genuinely never recorded this id, so a real redelivery must still be
        # allowed through (this cache is a fast path, never a substitute for the DB
        # constraint that's the actual source of truth).
        _recent_wa_message_ids[wa_message_id] = True


async def preview_jump_to_step(session, sender: WhatsAppSender, restaurant: Restaurant, from_phone: str, step_id: str) -> None:
    """The Bot Preview simulator's "Preview This Step" action (see
    app/api/v1/routers/flow_preview.py) -- renders one step's CURRENT message/image/
    buttons directly, without walking the customer through every step that would
    normally precede it. Always dry_run (this exists only for the admin to sanity-check
    one node's presentation, never to create real data), and always resets the given
    preview session's state/context first, since a step reached this way has none of the
    context a real conversation would have built up (no captured category/item/etc) --
    render_template leaves any {{variable}} it can't resolve as an empty string (see
    template_engine.py) rather than raising, so this is safe even for a step deep in a
    niche's flow, just visibly incomplete for variables only real navigation would fill in.

    Reuses `_Engine._render_step` directly -- the exact function every real render (and
    the ordinary preview_turn path above) goes through -- rather than any separate
    preview-only rendering logic.
    """
    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_or_create(restaurant.id, from_phone)
    state_repo = GenericConversationStateRepository(session)
    state = await state_repo.get_for_update_by_customer(customer.id)
    flow_repo = FlowDefinitionRepository(session)
    flow_def = await flow_repo.get_by_restaurant(restaurant.id)
    if flow_def is None:
        return
    steps_by_id = {s["step_id"]: s for s in flow_def.steps}
    step = steps_by_id.get(step_id)
    if step is None:
        return

    if state is None:
        from app.models.generic_conversation_state import GenericConversationState

        state = GenericConversationState(restaurant_id=restaurant.id, customer_id=customer.id, current_step=step_id, context={})
        session.add(state)
    else:
        state.current_step = step_id
        state.context = {}
        state.is_handed_over = False
    await session.flush()

    engine = _Engine(session, sender, dry_run=True)
    engine.flow_id = flow_def.id
    await engine._render_step(restaurant, customer, state, from_phone, step, steps_by_id)
    await session.commit()


class _GenericMessageRepo:
    """Thin wrapper so this file doesn't import the legacy MessageRepository's
    ConversationState-typed handover query -- only the one method actually needed here."""

    def __init__(self, session):
        self.session = session

    async def get_by_wa_message_id(self, wa_message_id: str) -> Message | None:
        from sqlalchemy import select

        result = await self.session.execute(select(Message).where(Message.wa_message_id == wa_message_id))
        return result.scalar_one_or_none()


async def send_generic_message(session, sender: WhatsAppSender, restaurant: Restaurant, customer_id: uuid.UUID, to: str, message: OutboundMessage) -> None:
    await send_generic_messages_batch(session, sender, restaurant, customer_id, to, [message])


async def send_generic_messages_batch(
    session, sender: WhatsAppSender, restaurant: Restaurant, customer_id: uuid.UUID, to: str, messages: list[OutboundMessage]
) -> None:
    """Same per-message behavior as send_generic_message, for a whole list at once.

    Sent SEQUENTIALLY, in list order -- NOT concurrently. This used to fire every message
    at once via asyncio.gather for speed, but that broke ordering in practice: Meta must
    fetch and validate an image's URL before accepting an image message, which takes
    measurably longer than accepting a plain text/interactive message, so a text/options
    message dispatched at the same instant as an image reliably WINS the race and arrives
    to the customer first -- confirmed live (an interactive list showed up before its own
    accompanying image). Since arrival order can't actually be controlled once two sends
    are in flight concurrently, and image-before-options is the real requirement, this
    goes back to sequential -- awaiting each in order guarantees the image's API call has
    already returned before the next one is even issued. This is still fast: the earlier
    ~10s stacking was from GraphAPIWhatsAppSender opening a brand new TCP+TLS connection
    per call (see its docstring), not from sequential awaiting itself -- with a persistent,
    reused connection, two or three sequential sends are a fraction of a second apart.

    Credential resolution (the one session-bound read here) happens once up front, and DB
    logging happens only after every send has returned.

    A per-niche demo restaurant owns no real WhatsApp number of its own (see
    app/models/restaurant.py::demo_sends_via_restaurant_id) -- it sends through the one
    sentinel Demo Bot restaurant's real credentials instead. NULL for every real
    restaurant, so this is a no-op lookup and behavior is byte-for-byte unchanged for
    them. Resolved here (not mutated onto `restaurant` itself) because this function
    commits mid-request elsewhere in the call chain -- writing real credentials onto a
    demo restaurant's own in-memory row would risk them being flushed to that row
    permanently, which is exactly what this avoids.
    """
    if not messages:
        return
    send_via = restaurant
    if restaurant.demo_sends_via_restaurant_id:
        send_via = await session.get(Restaurant, restaurant.demo_sends_via_restaurant_id)
    access_token = decrypt_secret(send_via.whatsapp_access_token_encrypted or "")
    phone_number_id = send_via.whatsapp_phone_number_id or ""

    async def _send_one(message: OutboundMessage) -> None:
        try:
            await sender.send(phone_number_id, access_token, message)
        except Exception:
            logger.warning("Generic-engine WhatsApp send failed for restaurant %s", restaurant.id, exc_info=True)

    for message in messages:
        await _send_one(message)

    for message in messages:
        body = message.payload.get("text", {}).get("body") or message.payload.get("image", {}).get("caption") or "[message]"
        session.add(
            Message(
                restaurant_id=restaurant.id,
                customer_id=customer_id,
                direction=MessageDirection.OUTBOUND,
                sent_by=MessageSender.BOT,
                body=body[:4096],
            )
        )


class _Engine:
    def __init__(self, session, sender: WhatsAppSender, dry_run: bool = False):
        self.session = session
        self.sender = sender
        self.category_repo = CatalogCategoryRepository(session)
        self.item_repo = CatalogItemRepository(session)
        self.staff_repo = StaffMemberRepository(session)
        self.engagement_repo = EngagementRepository(session)
        # True only for the Super Admin Bot Preview simulator (see
        # app/api/v1/routers/flow_preview.py) -- runs every real step/message/catalog/
        # variable lookup through this exact class (never a separate fake preview
        # engine), but never writes an Engagement/payment/staff-notification, never
        # records a real analytics event, and never broadcasts a live-chat websocket
        # signal for what is, by construction, not a real customer.
        self.dry_run = dry_run
        # Set by handle()/preview_jump_to_step (the only two entry points that construct
        # an _Engine) before any rendering happens -- lets _step_gallery resolve curated
        # per-step images (app/services/image_presenter.py::resolve_step_images) without
        # threading flow_def through every render/send helper's signature.
        self.flow_id: uuid.UUID | None = None

    def _record_event(self, restaurant_id, event_type, **kwargs) -> None:
        if self.dry_run:
            return
        analytics.record_event(self.session, restaurant_id, event_type, **kwargs)

    async def _broadcast(self, restaurant_id, payload: dict) -> None:
        if self.dry_run:
            return
        await ws_manager.broadcast(restaurant_id, payload)

    # --- top-level dispatch ----------------------------------------------------------

    async def handle(self, restaurant, customer, state, from_phone, flow_def, interaction: GenericInteraction) -> None:
        self.flow_id = flow_def.id
        # A HUMAN_HANDOFF step (see _render_step) sets this -- while True, every
        # automated branch below is skipped entirely. The inbound Message row is already
        # written by process_inbound_message before handle() is ever called, so "log but
        # don't advance" falls out for free; this just broadcasts a live-update signal so
        # staff watching the handed-off conversation see the new message arrive.
        if state.is_handed_over:
            await self._broadcast(restaurant.id, {"type": "generic_inbound_while_handed_off", "customer_id": str(customer.id)})
            return

        if interaction.kind == "unhandled_media":
            # Never touches state.current_step/context -- the customer stays exactly
            # where they were and can keep going once they send a real reply.
            body = _MEDIA_FALLBACK_MESSAGES.get(interaction.media_kind or "", _MEDIA_FALLBACK_DEFAULT)
            await send_generic_message(
                self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, body)
            )
            return

        steps_by_id = {s["step_id"]: s for s in flow_def.steps}

        if interaction.kind == "text" and (_looks_like_greeting(interaction.text or "") or _looks_like_restart(interaction.text or "")):
            state.context = {}
            self._record_event(restaurant.id, analytics.FLOW_STARTED, customer_id=customer.id, niche_code=flow_def.niche_code)
            await self._advance_and_render(restaurant, customer, state, from_phone, steps_by_id[flow_def.entry_step_id], steps_by_id)
            return

        current = steps_by_id.get(state.current_step) or steps_by_id[flow_def.entry_step_id]

        # Rule-based (no LLM) free-text intent resolution -- see conversational_intent.py.
        # Rewrites/annotates `interaction` so every branch below (including the existing
        # BACK_REPLY_ID check right below) sees something it already knows how to handle;
        # never niche-specific, driven only by `current`'s own generic FlowDefinition data
        # plus restaurant.conversation_settings. A real button/list tap (reply_id already
        # set) always passes through resolve_interaction untouched.
        resolved_options = await self._resolve_options(restaurant, state, current) if current.get("buttons_from") else []
        resolved = resolve_interaction(interaction, resolved_options, state.context, restaurant)
        if resolved.is_bot_query:
            await self._send_bot_disclosure(restaurant, customer, state, from_phone, current, steps_by_id)
            return
        if resolved.ambiguous_candidates:
            await self._send_disambiguation(restaurant, customer, from_phone, resolved.ambiguous_candidates)
            return
        if resolved.signal in ("cheaper", "show_more"):
            handled = await self._apply_refinement_signal(
                restaurant, customer, state, from_phone, current, steps_by_id, resolved_options, resolved.signal
            )
            if handled:
                return
        elif resolved.signal == "change_qty":
            target_step = self._find_nearest_quantity_step(current, steps_by_id)
            if target_step is not None:
                await self._advance_and_render(restaurant, customer, state, from_phone, target_step, steps_by_id)
                return
        elif resolved.signal == "back":
            interaction.reply_id = BACK_REPLY_ID
        elif resolved.synthetic_reply_id:
            interaction.reply_id = resolved.synthetic_reply_id

        if interaction.reply_id == BACK_REPLY_ID:
            target = current.get("back_target")
            target_step = steps_by_id.get(target) if target else None
            if target_step is not None:
                await self._advance_and_render(restaurant, customer, state, from_phone, target_step, steps_by_id)
            else:
                await self._advance_and_render(restaurant, customer, state, from_phone, current, steps_by_id)
            return

        if interaction.reply_id == JEWELLERY_LOAD_MORE_REPLY_ID and current["type"] == "jewellery_design_gallery":
            context = state.context
            context["jewellery_page"] = int(context.get("jewellery_page", 0)) + 1
            state.context = context
            await self._render_step(restaurant, customer, state, from_phone, current, steps_by_id)
            return

        await self._process_input(restaurant, customer, state, from_phone, current, steps_by_id, interaction)

    # --- conversational-intent helpers (see conversational_intent.py) ------------------

    async def _send_bot_disclosure(self, restaurant, customer, state, from_phone, current, steps_by_id) -> None:
        """Spec requirement: never pretend to be human. One fixed, honest line -- never
        an LLM-generated one, so it can never accidentally claim something untrue -- then
        the current step is simply re-rendered so the conversation carries on normally."""
        await send_generic_message(
            self.session, self.sender, restaurant, customer.id, from_phone,
            OutboundMessage.text(
                from_phone,
                f"Yep, I'm the virtual assistant for *{restaurant.name}* 🙂 I can help with products, orders, and enquiries.",
            ),
        )
        await self._render_step(restaurant, customer, state, from_phone, current, steps_by_id)

    async def _send_disambiguation(self, restaurant, customer, from_phone, candidates: list[dict]) -> None:
        """2-3 real, already-resolved options (never invented) the free text scored close
        to -- state.current_step is deliberately left untouched, so the customer's next
        tap on one of these (already-valid) ids flows through the completely normal,
        existing menu_select matching in _process_input; no new rendering machinery."""
        buttons = [{"id": c["id"], "title": c["title"][:20]} for c in candidates]
        await send_generic_message(
            self.session, self.sender, restaurant, customer.id, from_phone,
            OutboundMessage.interactive_buttons(from_phone, "Just to confirm -- did you mean one of these?", buttons),
        )

    def _find_nearest_quantity_step(self, current: dict, steps_by_id: dict) -> dict | None:
        """"change quantity" typed as free text -- walks the existing back_target chain
        (never a hardcoded step id) looking for the nearest quantity_input step, same
        generic navigation data BACK_REPLY_ID already uses. Bounded hop count so a
        malformed/cyclic flow graph can never hang this."""
        step = current
        for _ in range(6):
            target_id = step.get("back_target")
            if not target_id:
                return None
            step = steps_by_id.get(target_id)
            if step is None:
                return None
            if step.get("type") == "quantity_input":
                return step
        return None

    async def _apply_refinement_signal(
        self, restaurant, customer, state, from_phone, current, steps_by_id, options: list[dict], signal: str
    ) -> bool:
        """"anything cheaper?"/"show more" on a step whose options are already resolved --
        operates only on that already-fetched, real data (re-sorting/re-paginating it),
        never invents an item. Returns False (caller falls through to normal processing)
        when the current step doesn't support this signal, rather than silently no-oping."""
        if signal == "show_more" and current.get("type") == "jewellery_design_gallery":
            context = state.context
            context["jewellery_page"] = int(context.get("jewellery_page", 0)) + 1
            state.context = context
            await self._render_step(restaurant, customer, state, from_phone, current, steps_by_id)
            return True

        if signal == "cheaper" and current.get("buttons_from") == "items" and options:
            category_id = state.context.get(current.get("category_context_key", "category_id"))
            if not category_id:
                return False
            items = await self.item_repo.list_by_category(uuid.UUID(category_id), restaurant.id)
            items_by_price = sorted(items, key=lambda i: float(i.price or 0))
            images_by_item = await resolve_item_images_bulk(self.session, items_by_price, restaurant.id)
            sorted_options = [
                {
                    "id": f"item:{i.id}",
                    "title": i.name,
                    "description": _price_label(restaurant, i, include_attributes=True),
                    "image_url": next((img.url for img in images_by_item.get(i.id, [])), None),
                }
                for i in items_by_price
            ]
            await self._send_options(
                restaurant, customer, from_phone, "Sure -- here they are, lowest price first:", sorted_options,
                bool(current.get("back_target")), current, state.context,
            )
            return True

        return False

    # --- per-step-type input processing -----------------------------------------------

    async def _process_input(self, restaurant, customer, state, from_phone, step, steps_by_id, interaction: GenericInteraction) -> None:
        step_type = step["type"]
        context = state.context

        if step_type == "free_text_input" and step.get("accepts_location") and interaction.kind == "location":
            capture_key = step.get("capture_key", "note")
            context[capture_key] = interaction.text or f"{interaction.latitude:.4f}, {interaction.longitude:.4f}"
            context[f"{capture_key}_coords"] = {"lat": interaction.latitude, "lng": interaction.longitude}
            state.context = context
            await self._advance(restaurant, customer, state, from_phone, self._resolve_next(step, None), steps_by_id)
            return

        if step_type == "menu_select":
            options = await self._resolve_options(restaurant, state, step)
            matched = next((o for o in options if o["id"] == interaction.reply_id), None)
            if matched is None:
                await self._render_step(restaurant, customer, state, from_phone, step, steps_by_id, invalid=True)
                return
            self._record_event(
                restaurant.id, analytics.BUTTON_CLICKED,
                customer_id=customer.id, step_id=step.get("step_id"), niche_code=restaurant.niche_type,
                details={"reply_id": matched["id"]},
            )
            if step.get("capture_key"):
                # Store the raw id (after the "namespace:" prefix -- "category:<uuid>",
                # "date:<iso>", "staff:<uuid>"/"staff:any"), not the full prefixed
                # option id: every consumer (category/item/staff/date lookups below)
                # expects a bare uuid/iso-date string it can parse directly. `routes`
                # matching (see _resolve_next) still uses the full prefixed
                # `matched["id"]`, unaffected by this.
                _, _, raw_value = matched["id"].partition(":")
                context[step["capture_key"]] = raw_value or matched["id"]
                context[f"{step['capture_key']}_label"] = matched.get("title", "")
                if step["capture_key"] == "item_id":
                    # Friendlier aliases for message-template authors -- {{service_name}}
                    # reads naturally in an appointment niche's copy, {{product_name}} in
                    # an order/inquiry niche's, both point at the same captured value.
                    context["service_name"] = matched.get("title", "")
                    context["product_name"] = matched.get("title", "")
            state.context = context
            if step.get("action"):
                await self._run_action(restaurant, customer, state, from_phone, step["action"], matched, context)
            await self._advance(restaurant, customer, state, from_phone, self._resolve_next(step, matched["id"]), steps_by_id)
            return

        if step_type == "quantity_input":
            reply_id = interaction.reply_id or ""
            text = (interaction.text or "").strip()
            if context.get("_awaiting_custom_qty"):
                if not text.isdigit() or int(text) <= 0:
                    await self._render_step(restaurant, customer, state, from_phone, step, steps_by_id, invalid=True)
                    return
                qty = int(text)
                context.pop("_awaiting_custom_qty", None)
            elif reply_id.startswith("qty:"):
                raw = reply_id.split(":", 1)[1]
                if raw == "custom":
                    context["_awaiting_custom_qty"] = True
                    state.context = context
                    await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, "Please enter the quantity as a number:"))
                    return
                qty = int(raw)
            else:
                await self._render_step(restaurant, customer, state, from_phone, step, steps_by_id, invalid=True)
                return
            context["quantity"] = str(qty)
            state.context = context
            if step.get("action"):
                await self._run_action(restaurant, customer, state, from_phone, step["action"], {"qty": qty}, context)
            await self._advance(restaurant, customer, state, from_phone, self._resolve_next(step, None), steps_by_id)
            return

        if step_type == "free_text_input":
            if interaction.reply_id == SKIP_REPLY_ID:
                context[step.get("capture_key", "note")] = None
            else:
                text = (interaction.text or "").strip()
                if not text:
                    await self._render_step(restaurant, customer, state, from_phone, step, steps_by_id, invalid=True)
                    return
                context[step.get("capture_key", "note")] = text
                if step.get("capture_key") == "delivery_address":
                    # {{address}} alias -- delivery_address is the one free_text_input
                    # capture_key name that "address" naturally refers to across niches.
                    context["address"] = text
            state.context = context
            await self._advance(restaurant, customer, state, from_phone, self._resolve_next(step, None), steps_by_id)
            return

        if step_type == "send_quick_customize_flow":
            if interaction.kind != "flow_reply":
                # Customer typed/tapped something other than completing the Flow --
                # same "please pick one of the options below" re-render every other
                # step type already uses for unrecognized input, not a hard error.
                await self._render_step(restaurant, customer, state, from_phone, step, steps_by_id, invalid=True)
                return
            response = interaction.flow_response or {}
            # This specific Flow's own field names (item_id/qty/notes -- see
            # Restaurant.whatsapp_quick_customize_flow_id's docstring) mapped onto the
            # SAME context keys quantity_input/free_text_input already populate, so a
            # niche's own confirmation prompt can reuse {{quantity}}/{{note}} naturally
            # instead of needing brand-new template variable names.
            item_id = response.get("item_id")
            context["quick_customize_item_id"] = item_id
            context["quick_customize_item_label"] = _QUICK_CUSTOMIZE_ITEM_LABELS.get(item_id, item_id or "your selection")
            if response.get("qty"):
                context["quantity"] = str(response["qty"])
            if response.get("notes"):
                context["note"] = response["notes"]
            state.context = context
            await self._advance(restaurant, customer, state, from_phone, self._resolve_next(step, None), steps_by_id)
            return

        if step_type == "confirm_action":
            if step.get("action"):
                ok = await self._run_action(restaurant, customer, state, from_phone, step["action"], {}, context)
                if ok is False:
                    # Action failed (e.g. an item sold out between add-to-cart and
                    # confirm) -- a customer-facing message was already sent by the
                    # action itself; stay on this step rather than advancing to a
                    # terminal "confirmed" step for an engagement that was never
                    # created.
                    return
            await self._advance(restaurant, customer, state, from_phone, self._resolve_next(step, None), steps_by_id)
            return

        # "message"/human_handoff/etc. steps expect no input (terminal); an inbound
        # message here is treated as wanting to start over.
        state.context = {}
        await self._advance_and_render(restaurant, customer, state, from_phone, steps_by_id.get("welcome", step), steps_by_id)

    def _resolve_next(self, step: dict, matched_id: str | None) -> str | None:
        routes = step.get("routes") or {}
        if matched_id:
            if matched_id in routes:
                return routes[matched_id]
            for prefix, target in routes.items():
                if prefix.endswith("*") and matched_id.startswith(prefix[:-1]):
                    return target
        return step.get("next")

    async def _advance(self, restaurant, customer, state, from_phone, next_id, steps_by_id) -> None:
        while next_id and next_id in steps_by_id:
            next_step = steps_by_id[next_id]
            module_flag = next_step.get("skip_if_module_off")
            if module_flag and not (restaurant.loyalty_settings or {}).get("modules", {}).get(module_flag, True):
                next_id = next_step.get("next")
                continue
            await self._advance_and_render(restaurant, customer, state, from_phone, next_step, steps_by_id)
            return
        # No next step configured -- nothing more to render (shouldn't normally happen
        # for a well-formed flow; every non-terminal step has a `next`).

    async def _advance_and_render(self, restaurant, customer, state, from_phone, step, steps_by_id, invalid: bool = False) -> None:
        """Single chokepoint for landing on and rendering a step. Auto-advances through
        non-interactive step types (see _AUTO_ADVANCE_TYPES) -- evaluating a condition,
        sleeping out a delay, making an API call, or generating a placeholder AI
        response -- until landing on an interactive type (menu_select/quantity_input/
        free_text_input) or a terminal message/human_handoff/confirm_action state, then
        renders once and stops. For every step type that predates this feature, the loop
        condition is false on the very first check, so this is byte-for-byte identical to
        the old single `_render_step` call -- see module docstring / FlowStepType's
        docstring for why this is provably a no-op for every pre-existing niche/business.

        Every call site that SETS state.current_step to a step it's about to render goes
        through this (handle()'s greeting-reset and __back__ handling, _process_input's
        fallback, _advance's forward-navigation) -- never call _render_step directly for
        a step transition, only for re-rendering the CURRENT step in place (e.g. an
        "invalid input, try again" re-render), which is always already a non-auto-
        advancing type by construction (this function never sets current_step to one).
        """
        total_blocking_seconds = 0.0
        also_skip_module_off = restaurant.loyalty_settings or {}

        for _hop in range(_MAX_AUTO_ADVANCE_HOPS):
            module_flag = step.get("skip_if_module_off")
            if module_flag and not also_skip_module_off.get("modules", {}).get(module_flag, True):
                next_id = step.get("next")
                if not next_id or next_id not in steps_by_id:
                    return
                step = steps_by_id[next_id]
                continue

            step_type = step.get("type")
            if step_type not in _AUTO_ADVANCE_TYPES:
                state.current_step = step["step_id"]
                await self._render_step(restaurant, customer, state, from_phone, step, steps_by_id, invalid=invalid)
                return
            invalid = False  # only ever applies to the very first render attempt

            next_id: str | None
            if step_type == "condition":
                next_id = self._evaluate_condition(step, state.context)
            elif step_type == "delay":
                remaining = max(_MAX_TOTAL_BLOCKING_SECONDS - total_blocking_seconds, 0.0)
                delay_seconds = min(float(step.get("delay_seconds") or 0), remaining)
                total_blocking_seconds += delay_seconds
                if delay_seconds > 0:
                    await asyncio.sleep(delay_seconds)
                next_id = step.get("next")
            elif step_type == "api_call":
                from app.services.api_endpoint_client import call_api_endpoint

                # Conservative accounting: charges the full allowed timeout against the
                # chain budget regardless of actual elapsed time (a fast response still
                # counts as its worst case) -- simpler and safer than measuring real
                # elapsed time, and never lets the budget go negative.
                remaining = max(_MAX_TOTAL_BLOCKING_SECONDS - total_blocking_seconds, 0.5)
                total_blocking_seconds += remaining
                try:
                    result = await call_api_endpoint(self.session, step.get("endpoint_id"), state.context, timeout_override=remaining)
                    if step.get("capture_key"):
                        context = state.context
                        context[step["capture_key"]] = result
                        state.context = context
                except Exception:
                    logger.warning(
                        "Generic engine: api_call step %s failed for restaurant %s", step.get("step_id"), restaurant.id, exc_info=True
                    )
                next_id = step.get("next")
            else:  # "ai_response" -- placeholder until the AI Knowledge Base item ships
                await send_generic_message(
                    self.session, self.sender, restaurant, customer.id, from_phone,
                    OutboundMessage.text(from_phone, "🤖 AI responses aren't configured for this business yet."),
                )
                next_id = step.get("next")

            if not next_id or next_id not in steps_by_id:
                logger.warning(
                    "Generic engine: auto-advance chain from step %s (restaurant %s) has no valid next step",
                    step.get("step_id"), restaurant.id,
                )
                await send_generic_message(
                    self.session, self.sender, restaurant, customer.id, from_phone,
                    OutboundMessage.text(from_phone, "Sorry, something went wrong. Please type *hi* to start over."),
                )
                return
            step = steps_by_id[next_id]

        logger.error(
            "Generic engine: auto-advance chain for restaurant %s exceeded %d hops -- failing safely",
            restaurant.id, _MAX_AUTO_ADVANCE_HOPS,
        )
        await send_generic_message(
            self.session, self.sender, restaurant, customer.id, from_phone,
            OutboundMessage.text(from_phone, "Sorry, something went wrong. Please type *hi* to start over."),
        )

    def _evaluate_condition(self, step: dict, context: dict) -> str | None:
        condition = step.get("condition") or {}
        operator = condition.get("operator")
        op_fn = _CONDITION_OPERATORS.get(operator)
        result = False
        if op_fn is not None:
            try:
                result = bool(op_fn(context.get(condition.get("context_key")), condition.get("value")))
            except (TypeError, ValueError):
                result = False
        return step.get("then_step") if result else step.get("else_step")

    # --- rendering ---------------------------------------------------------------------

    async def _render_step(self, restaurant, customer, state, from_phone, step, steps_by_id, invalid: bool = False) -> None:
        prompt = await self._prompt_text(restaurant, customer, step, state.context)
        if invalid:
            prompt = "Sorry, please pick one of the options below.\n\n" + prompt

        # Outbound phrasing layer (see conversational_style.py) -- wraps the ALREADY fully
        # composed prompt (real catalog data/{{variables}} already substituted, and any
        # invalid-input prefix already applied above) with a tone-appropriate
        # acknowledgement/emoji-level/length adjustment; a true no-op for any restaurant
        # that hasn't configured conversation_settings. "welcome" is every niche's own
        # entry_step_id (see each app/niche_seeds/*.py TEMPLATE) -- used here only to skip
        # an acknowledgement on the very first message of a session, never a niche branch.
        prompt = humanize(
            prompt, restaurant, f"{customer.id}:{step.get('step_id')}",
            is_reprompt=invalid, is_entry_step=step.get("step_id") == "welcome",
        )

        show_back = bool(step.get("back_target"))

        # NODE_VIEWED fires for every step actually shown to a customer, including an
        # invalid-input re-render of the same step -- it's still a real view of that
        # node. See app/services/analytics.py's module docstring for the event vocabulary.
        self._record_event(
            restaurant.id, analytics.NODE_VIEWED,
            customer_id=customer.id, step_id=step.get("step_id"), niche_code=restaurant.niche_type,
            details={"step_type": step["type"], "invalid": invalid},
        )
        if step.get("terminal"):
            self._record_event(
                restaurant.id, analytics.FLOW_COMPLETED,
                customer_id=customer.id, step_id=step.get("step_id"), niche_code=restaurant.niche_type,
            )

        if step["type"] in ("message",):
            # A pure "message" step (welcome text, a standalone gallery step, etc.) has no
            # options to burst/gallery through _send_options -- so curated per-step images
            # (see _step_gallery) are sent here directly. All dispatched CONCURRENTLY via
            # send_generic_messages_batch (image(s) listed first, text last) rather than
            # awaited one-by-one -- same reasoning as _send_options: each is a real network
            # round-trip to Meta, so sequential awaiting visibly stacks up.
            messages = []
            if step.get("show_image", True):
                for img in await self._step_gallery(restaurant, step):
                    messages.append(await self._media_message(restaurant, img.url, (img.caption or prompt)[:1024], from_phone))
            messages.append(OutboundMessage.text(from_phone, prompt))
            await send_generic_messages_batch(self.session, self.sender, restaurant, customer.id, from_phone, messages)
            return

        if step["type"] == "human_handoff":
            handoff_message = prompt or "🧑‍💼 Connecting you with our team -- someone will reply here shortly."
            await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, handoff_message))
            state.is_handed_over = True
            self._record_event(
                restaurant.id, analytics.HUMAN_HANDOFF,
                customer_id=customer.id, step_id=step.get("step_id"), niche_code=restaurant.niche_type,
            )
            await self._broadcast(restaurant.id, {"type": "generic_handover", "customer_id": str(customer.id)})
            return

        if step["type"] == "free_text_input":
            buttons = []
            if step.get("allow_skip"):
                buttons.append({"id": SKIP_REPLY_ID, "title": "Skip"})
            if show_back:
                buttons.append({"id": BACK_REPLY_ID, "title": "⬅ Back"})
            if buttons:
                await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.interactive_buttons(from_phone, prompt, buttons))
            else:
                await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, prompt))
            if step.get("accepts_location"):
                # A native "Send location" prompt can't carry extra custom buttons of its
                # own (it's a single-purpose WhatsApp interactive type) -- sent as a
                # second message right after, so typing an address, tapping Back, and
                # native location-share are all live options at once.
                await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.location_request(from_phone, "Or share your live location:"))
            return

        if step["type"] == "send_whatsapp_flow":
            # Opt-in per restaurant (whatsapp_flow_order_id set via
            # POST .../whatsapp-flow/enable) -- see the approved "WhatsApp Flows for
            # Ordering" plan. A niche whose step routes here but whose restaurant hasn't
            # enabled it falls back to `fallback_next` (defaulting to `next`, the same
            # field every other step already has), so this is safe to route to
            # unconditionally from a niche's welcome step without a per-business branch
            # in the flow graph itself.
            if not restaurant.whatsapp_flow_order_id:
                fallback = steps_by_id.get(step.get("fallback_next") or step.get("next") or "")
                if fallback:
                    await self._advance_and_render(restaurant, customer, state, from_phone, fallback, steps_by_id)
                return
            # Local import -- whatsapp_flow_order_service.py itself imports _Engine/
            # _price_label from this module (to reuse _create_engagement rather than
            # duplicating order-creation logic), so a module-level import here would be
            # circular. Resolved lazily at call time instead, a standard way to break this
            # specific shape of two-way dependency.
            from app.services.whatsapp_flow_order_service import initial_screen_data
            data = await initial_screen_data(self.session, restaurant)
            await send_generic_message(
                self.session, self.sender, restaurant, customer.id, from_phone,
                OutboundMessage.flow(
                    from_phone, prompt, restaurant.whatsapp_flow_order_id, from_phone,
                    step.get("cta") or "Order Now", "CATEGORY_SCREEN", data,
                ),
            )
            return

        if step["type"] == "send_quick_customize_flow":
            # A SECOND, independent WhatsApp Flow slot -- see
            # Restaurant.whatsapp_quick_customize_flow_id's docstring for how this differs
            # from send_whatsapp_flow above (single static screen, no data-exchange, reply
            # arrives as an nfm_reply webhook message -- see handle() below and
            # webhook.py's nfm_reply parsing). Resolved from whichever restaurant actually
            # sends (demo_sends_via_restaurant_id-aware, same pattern _media_message
            # already uses) since a demo niche restaurant never carries this field itself
            # -- only the sentinel it sends through does.
            send_via = restaurant
            if restaurant.demo_sends_via_restaurant_id:
                send_via = await self.session.get(Restaurant, restaurant.demo_sends_via_restaurant_id)
            if not send_via.whatsapp_quick_customize_flow_id:
                fallback = steps_by_id.get(step.get("fallback_next") or step.get("next") or "")
                if fallback:
                    await self._advance_and_render(restaurant, customer, state, from_phone, fallback, steps_by_id)
                return
            await send_generic_message(
                self.session, self.sender, restaurant, customer.id, from_phone,
                OutboundMessage.flow(
                    from_phone, prompt, send_via.whatsapp_quick_customize_flow_id, from_phone,
                    step.get("cta") or "Customize & Select Qty", "ORDER_SCREEN",
                    # Meta rejects a genuinely empty {} here with error 131009 ("data in
                    # flow_action_payload for CTA flow must be of type dynamic_object") --
                    # confirmed via a direct Graph API call. ORDER_SCREEN has no real
                    # fields to prefill, so this is a harmless non-empty placeholder, not
                    # data the screen actually reads.
                    {"placeholder": "placeholder"},
                    mode="draft" if send_via.whatsapp_quick_customize_flow_draft_mode else None,
                ),
            )
            return

        if step["type"] == "quantity_input":
            options = [
                {"id": "qty:1", "title": "1"},
                {"id": "qty:2", "title": "2"},
                {"id": "qty:3", "title": "3"},
                {"id": "qty:custom", "title": "Custom"},
            ]
            await self._send_options(restaurant, customer, from_phone, prompt, options, show_back, step, state.context)
            return

        if step["type"] == "jewellery_design_gallery":
            await self._render_jewellery_gallery(restaurant, customer, state, from_phone, step, show_back)
            return

        # menu_select / confirm_action -- both render as a selectable option set.
        options = await self._resolve_options(restaurant, state, step)
        await self._send_options(restaurant, customer, from_phone, prompt, options, show_back, step, state.context)

    async def _prompt_text(self, restaurant: Restaurant, customer: Customer, step: dict, context: dict) -> str:
        # human_handoff steps store their text under "message" rather than "prompt" (see
        # the niche seed files) -- falls back to it so handoff copy gets the same
        # {{business_name}}/{{customer_name}}/etc. substitution as every other step type,
        # instead of being sent to the customer with the raw, unrendered placeholders.
        template = step.get("prompt") or step.get("message") or ""
        # customer_name prefers an explicit override the customer typed at an "Edit Name"
        # step (context["customer_name_override"], if a niche's flow captures one) over
        # the WhatsApp-profile-seeded Customer.name, which itself may still be empty for
        # a first-time contact whose profile has no display name set.
        customer_name = context.get("customer_name_override") or customer.name or ""
        # {{date}}/{{time}} are today's-server-clock convenience variables for generic
        # copy ("we're open until {{time}}") -- distinct from an appointment/booking's
        # own captured {{date_label}}/{{time_label}}, which come from context and always
        # win below since **context is spread after these two.
        now = datetime.now(timezone.utc)
        return render_template(
            template,
            {
                # business_name is the forward-looking variable name (matches the
                # Super-Admin message-override convention the platform is moving
                # towards); restaurant_name is kept working for any existing content.
                "restaurant_name": restaurant.name,
                "business_name": restaurant.name,
                "currency": restaurant.currency,
                "customer_name": customer_name,
                "date": now.strftime("%d %b %Y"),
                "time": now.strftime("%I:%M %p"),
                **context,
            },
        )

    def _photo_burst_urls(self, restaurant: Restaurant, options: list[dict]) -> list[str] | None:
        """All-or-nothing gate: fires only when EVERY option carries its own genuine,
        mutually-distinct photo -- not missing, not the restaurant's generic cover/logo/
        placeholder fallback, not reused by any other option in the set. A partially-
        photographed category (some items on a real photo, the rest still on a shared
        fallback) deliberately returns None here rather than bursting a mismatched mix --
        see the approved design review that flagged exactly this case as worse UX than
        the single combo-image it would replace."""
        fallbacks = {restaurant.cover_image_url, restaurant.logo_url, _PLACEHOLDER_IMAGE.format(label=restaurant.name.replace(" ", "+"))}
        urls = [o.get("image_url") for o in options]
        if any(not u or u in fallbacks for u in urls):
            return None
        if len(set(urls)) != len(urls):
            return None
        return urls

    async def _send_options(self, restaurant, customer, from_phone, body, options, show_back, step, context) -> None:
        all_options = list(options)
        if show_back:
            all_options.append({"id": BACK_REPLY_ID, "title": "⬅ Back"})

        show_images = step.get("show_image", True)
        is_menu_select = step["type"] == "menu_select" and step.get("buttons_from") in ("categories", "items")

        burst_urls = None
        if show_images and is_menu_select and options and len(options) <= step.get("photo_burst_max", _PHOTO_BURST_MAX_DEFAULT):
            burst_urls = self._photo_burst_urls(restaurant, options)

        # Every image for this step (one, many, or none) is collected here -- ALWAYS sent
        # via send_generic_messages_batch with every image FIRST and the options message
        # (built further down) always LAST, dispatched sequentially so that order is
        # guaranteed (see send_generic_messages_batch's docstring: concurrent dispatch was
        # tried and reverted, since Meta accepts a plain text/interactive message faster
        # than it accepts an image -- concurrently, the options message reliably arrived
        # BEFORE its own image).
        image_messages: list[OutboundMessage] = []

        if burst_urls:
            # Every option gets its own photo -- a real "album" browse instead of one
            # representative image + a text list. See _photo_burst_urls for the strict
            # gate that decides whether this path runs at all. No separate intro text here
            # -- the final options_message below already carries this same `body` text as
            # its own message body, so a leading plain-text copy of it would both violate
            # images-before-options and be a redundant repeat of the same line.
            for option, url in zip(options, burst_urls):
                caption = option["title"] + (f" - {option['description']}" if option.get("description") else "")
                image_messages.append(await self._media_message(restaurant, url, caption[:1024], from_phone))
        elif show_images and step.get("item_context_key"):
            # An "item detail" step (e.g. "Ring Details") keyed on a previously-selected
            # item -- every active image Super Admin has curated for that item, each with
            # its own caption, in display_order. WhatsApp has no native multi-image
            # carousel for a plain text/interactive message, so individual image messages
            # are the actual supported mechanism (see the burst path above, same idea for
            # a list of options).
            gallery = await self._item_gallery(restaurant, context.get(step["item_context_key"]))
            if gallery:
                for img in gallery:
                    image_messages.append(await self._media_message(restaurant, img.url, (img.caption or body)[:1024], from_phone))
            else:
                image_url = await self._image_for_step(restaurant, step, context)
                if image_url:
                    image_messages.append(await self._media_message(restaurant, image_url, body[:1024], from_phone))
        elif show_images and (step_gallery := await self._step_gallery(restaurant, step)):
            # Curated per-step images (e.g. a dedicated gallery step, or a welcome step
            # with more than one banner) -- same mechanism as _item_gallery above, just
            # sourced from the step itself rather than a selected catalog item.
            for img in step_gallery:
                image_messages.append(await self._media_message(restaurant, img.url, (img.caption or body)[:1024], from_phone))
        elif show_images:
            image_url = await self._image_for_step(restaurant, step, context)
            if image_url:
                caption_lines = [body]
                if is_menu_select:
                    # Include the description (items already carry price/duration in
                    # "description" via _price_label -- see _resolve_options) so the image
                    # caption is a real menu/catalog preview, not just a bare name list.
                    caption_lines += [
                        f"• {o['title']}" + (f" - {o['description']}" if o.get("description") else "")
                        for o in options[:10]
                    ]
                image_messages.append(await self._media_message(restaurant, image_url, "\n".join(caption_lines)[:1024], from_phone))

        # Meta caps interactive-button messages at 3 total buttons; use a list (cap 10)
        # whenever that would be exceeded, so Back always has room instead of getting
        # silently dropped.
        if len(all_options) <= 3:
            options_message = OutboundMessage.interactive_buttons(
                from_phone, body, [{"id": o["id"], "title": o["title"][:20]} for o in all_options]
            )
        else:
            rows = [{"id": o["id"], "title": o["title"][:24], "description": o.get("description", "")[:72]} for o in all_options]
            options_message = OutboundMessage.interactive_list(from_phone, body, "Select", rows, step.get("section_title", "Options"))

        await send_generic_messages_batch(
            self.session, self.sender, restaurant, customer.id, from_phone, [*image_messages, options_message]
        )

    async def _render_jewellery_gallery(self, restaurant, customer, state, from_phone, step, show_back) -> None:
        """Layer 3 of the jewellery-only carousel: material_select (capture_key
        "material") -> jewellery_category_select (capture_key "jewellery_category") ->
        this step, which pages through JewelleryDesign rows for that (material, category)
        pair. Deliberately its OWN step type and rendering path, not a menu_select variant
        of _send_options -- design images aren't tappable catalog options (nothing in a
        real WhatsApp chat lets a customer "select" one of several images at once), the
        page cursor lives in state.context["jewellery_page"] (advanced only by
        JEWELLERY_LOAD_MORE_REPLY_ID, intercepted in handle() before this is ever called
        again for the same page), and the image count per send is bounded by page_size --
        unlike every other gallery path in this file, which sends every active image
        unconditionally. This isolation is intentional: nothing here touches
        _send_options/_item_gallery/_step_gallery, so their behavior for every other niche
        (and jewellery's own existing category_select/item_select/piece_details flow) is
        provably unchanged.

        Groundwork for the real native WhatsApp Multi-Product Message carousel: when
        restaurant.whatsapp_catalog_id is set AND this page has at least one design
        already synced into that catalog (see app/services/meta_catalog_sync.py), this
        delegates to _render_jewellery_gallery_native instead. Every restaurant today has
        whatsapp_catalog_id NULL (no Meta Commerce Catalog connected yet), so this branch
        is currently unreachable in practice and every line below is exercised exactly as
        before.
        """
        if restaurant.whatsapp_catalog_id:
            if await self._render_jewellery_gallery_native(restaurant, customer, state, from_phone, step, show_back):
                return
            # Catalog is configured but nothing on this page has a meta_retailer_id yet
            # (sync hasn't run) -- fall through to the exact same sequential-image path
            # used when no catalog is configured at all, rather than sending nothing.

        context = state.context
        material = context.get("material")
        category = context.get("jewellery_category")
        page = int(context.get("jewellery_page", 0) or 0)
        page_size = int(step.get("page_size", 10))

        back_button = {"id": BACK_REPLY_ID, "title": "⬅ Back"}

        if not material or not category:
            # Shouldn't normally happen (this step is only reachable after both prior
            # selections capture into context) -- graceful fallback rather than a crash.
            buttons = [back_button] if show_back else []
            await send_generic_message(
                self.session, self.sender, restaurant, customer.id, from_phone,
                OutboundMessage.interactive_buttons(from_phone, "Please pick a material and category first.", buttons)
                if buttons else OutboundMessage.text(from_phone, "Please pick a material and category first."),
            )
            return

        repo = JewelleryDesignRepository(self.session)
        total = await repo.count_designs(restaurant.id, material, category)
        designs = await repo.list_designs(restaurant.id, material, category, offset=page * page_size, limit=page_size)

        material_label = material.replace("_", " ").title()
        category_label = category.replace("_", " ").title()

        if not designs:
            # Empty-state per spec: a clean message, not a broken/empty carousel, then
            # Back is still available so the customer can pick a different category.
            body = (
                step.get("empty_message")
                or f"No designs available in {material_label} {category_label} yet.\nPlease explore another jewellery type."
            )
            buttons = [back_button] if show_back else []
            if buttons:
                await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.interactive_buttons(from_phone, body, buttons))
            else:
                await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, body))
            return

        messages: list[OutboundMessage] = []
        for design in designs:
            caption = f"{design.name}\n{material_label} • {category_label}"
            messages.append(await self._design_image_message(restaurant, design, caption[:1024], from_phone))

        shown_so_far = page * page_size + len(designs)
        has_more = shown_so_far < total
        body = f"{material_label} {category_label} -- showing {shown_so_far} of {total} designs"

        buttons = []
        if has_more:
            buttons.append({"id": JEWELLERY_LOAD_MORE_REPLY_ID, "title": "Load More"})
        if show_back:
            buttons.append(back_button)
        messages.append(OutboundMessage.interactive_buttons(from_phone, body, buttons))

        await send_generic_messages_batch(self.session, self.sender, restaurant, customer.id, from_phone, messages)

    async def _media_message(self, restaurant: Restaurant, url: str, caption: str, from_phone: str) -> OutboundMessage:
        """The generic-image counterpart of _design_image_message below -- same
        pre-uploaded-media_id-with-link-fallback behavior, for any catalog item/category/
        flow-step image (from image_presenter.py's ItemImage.url, or a restaurant's
        cover_image_url/logo_url welcome banner) rather than a JewelleryDesign row
        specifically. Cached generically by (phone_number_id, url) in MetaMediaCache
        (see that model's docstring for why a separate table, not more columns bolted
        onto `Image` -- ItemImage only ever exposes a url string, not the owning Image
        row, and the legacy CatalogItem.images plain-URL fallback has no row at all).
        Every caller keeps working exactly as before on any failure/miss -- this never
        raises, and dry_run (Bot Preview) never makes a real Meta API call.

        On a cache miss, the CURRENT send always goes out via `link` immediately -- the
        upload is scheduled as a fire-and-forget background task (see
        meta_media_upload.py::schedule_background_upload) that only pre-warms the cache
        for next time, never adding upload latency to the reply the customer is actually
        waiting on right now.
        """
        if self.dry_run:
            return OutboundMessage.image(from_phone, url, caption)

        send_via = restaurant
        if restaurant.demo_sends_via_restaurant_id:
            send_via = await self.session.get(Restaurant, restaurant.demo_sends_via_restaurant_id)
        phone_number_id = send_via.whatsapp_phone_number_id or ""
        if not phone_number_id:
            return OutboundMessage.image(from_phone, url, caption)

        cache_repo = MetaMediaCacheRepository(self.session)
        cached = await cache_repo.get(phone_number_id, url)
        fresh_cutoff = datetime.utcnow() - timedelta(days=MEDIA_ID_FRESHNESS_DAYS)
        if cached and cached.uploaded_at > fresh_cutoff:
            return OutboundMessage.image_by_id(from_phone, cached.media_id, caption)

        if isinstance(self.sender, GraphAPIWhatsAppSender):
            access_token = decrypt_secret(send_via.whatsapp_access_token_encrypted or "")
            restaurant_id = restaurant.id

            async def _persist(session, media_id: str) -> None:
                await MetaMediaCacheRepository(session).upsert(restaurant_id, phone_number_id, url, media_id, datetime.utcnow())

            schedule_background_upload(self.sender._client, phone_number_id, access_token, url, _persist)

        return OutboundMessage.image(from_phone, url, caption)

    async def _design_image_message(self, restaurant: Restaurant, design, caption: str, from_phone: str) -> OutboundMessage:
        """A design's image, sent by pre-uploaded Meta media_id when a fresh one is
        cached for the phone_number_id this restaurant actually sends through, falling
        back to the plain `link` form (which already works correctly today) in every
        other case: dry_run (Bot Preview never makes real Meta API calls), no cached id
        yet, a cached id for a DIFFERENT phone_number_id (e.g. this design was last shown
        via a different demo routing), a stale one past MEDIA_ID_FRESHNESS_DAYS, or the
        lazy upload attempt itself failing for any reason. A design's meta_media_id is
        only ever set here, lazily, on first use that needs it -- never eagerly for the
        whole catalogue at once.
        """
        link = f"{settings.PUBLIC_MEDIA_BASE_URL}/{design.image_key}"
        if self.dry_run:
            return OutboundMessage.image(from_phone, link, caption)

        send_via = restaurant
        if restaurant.demo_sends_via_restaurant_id:
            send_via = await self.session.get(Restaurant, restaurant.demo_sends_via_restaurant_id)
        phone_number_id = send_via.whatsapp_phone_number_id or ""

        fresh_cutoff = datetime.utcnow() - timedelta(days=MEDIA_ID_FRESHNESS_DAYS)
        has_fresh_id = (
            design.meta_media_id
            and design.meta_media_id_phone_number_id == phone_number_id
            and design.meta_media_id_uploaded_at
            and design.meta_media_id_uploaded_at > fresh_cutoff
        )
        if has_fresh_id:
            return OutboundMessage.image_by_id(from_phone, design.meta_media_id, caption)

        if isinstance(self.sender, GraphAPIWhatsAppSender) and phone_number_id:
            access_token = decrypt_secret(send_via.whatsapp_access_token_encrypted or "")
            design_id = design.id

            async def _persist(session, media_id: str) -> None:
                # Re-fetched by id in this fresh (background-task-owned) session -- the
                # `design` row from the request's own session is out of scope by the time
                # this runs, since the request already returned its `link`-based reply
                # before this task's upload even starts.
                fresh_design = await session.get(JewelleryDesign, design_id)
                if fresh_design is not None:
                    fresh_design.meta_media_id = media_id
                    fresh_design.meta_media_id_phone_number_id = phone_number_id
                    fresh_design.meta_media_id_uploaded_at = datetime.utcnow()

            schedule_background_upload(self.sender._client, phone_number_id, access_token, design.image_key, _persist)

        return OutboundMessage.image(from_phone, link, caption)

    async def _render_jewellery_gallery_native(self, restaurant, customer, state, from_phone, step, show_back) -> bool:
        """Native "Multi-Product Message" branch of _render_jewellery_gallery -- a real
        swipeable WhatsApp product carousel pulled from restaurant.whatsapp_catalog_id,
        built from ONLY the current page's designs that already have a
        JewelleryDesign.meta_retailer_id (i.e. have actually been synced into Meta's
        Commerce Catalog by app/services/meta_catalog_sync.py::sync_designs_to_catalog).
        Designs on the page without one yet are quietly excluded from the section's
        product_items -- never a crash, never a partially-broken carousel.

        Returns False (send nothing, caller falls back to the sequential-image path)
        when there are zero eligible designs on this page, e.g. the catalog is
        configured but this page hasn't been synced yet -- so a restaurant mid-migration
        to the native carousel never sends a guaranteed-to-fail empty product_list
        instead of just showing the images it already has.
        """
        context = state.context
        material = context.get("material")
        category = context.get("jewellery_category")
        page = int(context.get("jewellery_page", 0) or 0)
        page_size = int(step.get("page_size", 10))

        if not material or not category:
            return False

        repo = JewelleryDesignRepository(self.session)
        total = await repo.count_designs(restaurant.id, material, category)
        designs = await repo.list_designs(restaurant.id, material, category, offset=page * page_size, limit=page_size)
        eligible = [d for d in designs if d.meta_retailer_id]
        if not eligible:
            return False

        material_label = material.replace("_", " ").title()
        category_label = category.replace("_", " ").title()
        shown_so_far = page * page_size + len(designs)
        has_more = shown_so_far < total
        body = f"{material_label} {category_label} -- showing {shown_so_far} of {total} designs"

        product_message = OutboundMessage.product_list(
            from_phone,
            catalog_id=restaurant.whatsapp_catalog_id,
            header=f"{material_label} {category_label}",
            body=body,
            retailer_ids=[d.meta_retailer_id for d in eligible],
        )

        back_button = {"id": BACK_REPLY_ID, "title": "⬅ Back"}
        buttons = []
        if has_more:
            buttons.append({"id": JEWELLERY_LOAD_MORE_REPLY_ID, "title": "Load More"})
        if show_back:
            buttons.append(back_button)

        messages: list[OutboundMessage] = [product_message]
        if buttons:
            messages.append(OutboundMessage.interactive_buttons(from_phone, body, buttons))

        await send_generic_messages_batch(self.session, self.sender, restaurant, customer.id, from_phone, messages)
        return True

    async def _item_gallery(self, restaurant: Restaurant, item_id: str | None):
        """Every active image curated for one specific item (see
        app/services/image_presenter.py), already ordered and caption-bearing -- the data
        source for an "item detail" step's photo gallery. Empty list (not an error) when
        item_id is unset/unresolvable or the item has no images yet."""
        if not item_id:
            return []
        item = await self.item_repo.get(uuid.UUID(item_id), restaurant.id)
        if not item:
            return []
        return await resolve_item_images(self.session, item, restaurant.id)

    async def _step_gallery(self, restaurant: Restaurant, step: dict):
        """Every active image curated directly on this flow step (see
        app/services/image_presenter.py::resolve_step_images) -- distinct from an item's
        or category's own images, which a step only shows indirectly via `buttons_from`/
        `item_context_key`. Empty list (not an error) when self.flow_id is unset (should
        never happen once handle()/preview_jump_to_step have run) or nothing's curated."""
        if self.flow_id is None:
            return []
        step_id = step.get("step_id")
        if not step_id:
            return []
        return await resolve_step_images(self.session, self.flow_id, step_id, restaurant.id)

    async def _image_for_step(self, restaurant: Restaurant, step: dict, context: dict) -> str | None:
        source = step.get("buttons_from")
        if source == "categories":
            categories = await self.category_repo.list_visible(restaurant.id)
            for c in categories:
                images = await resolve_category_images(self.session, c, restaurant.id)
                if images:
                    return images[0].url
        elif source == "items":
            category_id = context.get(step.get("category_context_key", "category_id"))
            if category_id:
                items = await self.item_repo.list_by_category(uuid.UUID(category_id), restaurant.id)
                for item in items:
                    # Prefers Image-table (Universal Image Processing Pipeline) URLs when
                    # they exist for this item, falling back to the legacy images JSON
                    # list otherwise -- see image_presenter.py's module docstring.
                    images = await resolve_item_images(self.session, item, restaurant.id)
                    if images:
                        return images[0].url
        elif step.get("item_context_key"):
            # An "item detail" step (e.g. "Ring Details") sends its FULL image gallery via
            # _send_options's own item_context_key branch (_item_gallery), which calls
            # this function only as ITS OWN fallback when that item has zero images --
            # falls through to the restaurant-level fallback below in that case, rather
            # than silently sending nothing.
            pass
        if step.get("step_id") == "welcome" or source == "welcome":
            return restaurant.cover_image_url or restaurant.logo_url
        return restaurant.cover_image_url or _PLACEHOLDER_IMAGE.format(label=restaurant.name.replace(" ", "+"))

    # --- data providers ----------------------------------------------------------------

    async def _resolve_options(self, restaurant, state, step: dict) -> list[dict[str, Any]]:
        source = step.get("buttons_from")
        context = state.context

        if source == "static":
            # `visible` (default True) and `icon` are optional, additive fields on each
            # option (see app/services/flow_shape_validation.py and the home-buttons
            # endpoint, app/api/v1/routers/flow_definitions.py, which is what writes
            # them) -- this is the ONLY read site for static_options in the codebase, so
            # filtering a hidden option out here makes it genuinely untappable (it falls
            # into _process_input's existing `matched is None` -> re-render-as-invalid
            # path below), not just visually hidden. Options without a `visible` key
            # (every pre-existing niche config) are unaffected -- default True.
            return [o for o in (step.get("static_options") or []) if o.get("visible", True)]

        if source == "categories":
            categories = await self.category_repo.list_visible(restaurant.id)
            # Batched (one query for every category) rather than resolve_category_images
            # per category -- same reasoning as the "items" branch below; every option
            # needs its own image up front for photo-burst gating, not just the first hit
            # _image_for_step used to stop at. Falls back to the legacy image_url string
            # column inside resolve_category_images_bulk itself when a category has no
            # curated Image rows yet.
            images_by_category = await resolve_category_images_bulk(self.session, categories, restaurant.id)
            return [
                {
                    "id": f"category:{c.id}",
                    "title": c.name,
                    "image_url": next((img.url for img in images_by_category.get(c.id, [])), None),
                }
                for c in categories
            ]

        if source == "items":
            category_id = context.get(step.get("category_context_key", "category_id"))
            if not category_id:
                return []
            items = await self.item_repo.list_by_category(uuid.UUID(category_id), restaurant.id)
            # Batched (one query for the whole category) rather than resolve_item_images
            # per item -- see image_presenter.py::resolve_item_images_bulk's docstring;
            # every option needs its own image up front for photo-burst gating, not just
            # the first hit _image_for_step used to stop at.
            images_by_item = await resolve_item_images_bulk(self.session, items, restaurant.id)
            return [
                {
                    "id": f"item:{i.id}",
                    "title": i.name,
                    "description": _price_label(restaurant, i, include_attributes=True),
                    "image_url": next((img.url for img in images_by_item.get(i.id, [])), None),
                }
                for i in items
            ]

        if source == "staff":
            staff = await self.staff_repo.list_active(restaurant.id)
            options = [{"id": f"staff:{s.id}", "title": s.name} for s in staff]
            return [{"id": "staff:any", "title": "Any Available"}] + options

        if source == "cart_lines":
            cart = context.get("cart", [])
            return [{"id": f"cart:line:{idx}", "title": f"{c['name']} x{c['qty']}"} for idx, c in enumerate(cart)]

        if source == "dates":
            min_offset = 0
            if step.get("after_context_key"):
                checkin_iso = context.get(step["after_context_key"])
                if checkin_iso:
                    checkin = date.fromisoformat(checkin_iso)
                    min_offset = (checkin - date.today()).days + 1
            return _date_options(min_offset)

        if source == "time_slots":
            return await self._time_slot_options(restaurant, context)

        if source == "jewellery_materials":
            # Layer 1 of the jewellery-only carousel (see module docstring addendum below
            # _render_jewellery_gallery) -- distinct materials actually present in this
            # tenant's JewelleryDesign rows, not a hardcoded list, so a new material shows
            # up automatically the next time the downloader script runs for it.
            repo = JewelleryDesignRepository(self.session)
            materials = await repo.list_materials(restaurant.id)
            return [{"id": f"material:{m}", "title": m.replace("_", " ").title()} for m in materials]

        if source == "jewellery_categories":
            # Layer 2 -- categories available for the material captured by the preceding
            # material_select step (capture_key "material", see jewellers.py's
            # material_select step). Empty list (no options) if a customer somehow lands
            # here without a material in context -- same "nothing to show" shape every
            # other source returns for an unmet precondition (e.g. "items" above with no
            # category_id yet).
            material = context.get("material")
            if not material:
                return []
            repo = JewelleryDesignRepository(self.session)
            categories = await repo.list_categories(restaurant.id, material)
            return [{"id": f"jewellery_category:{c}", "title": c.replace("_", " ").title()} for c in categories]

        return []

    # --- action verbs --------------------------------------------------------------------

    async def _run_action(self, restaurant, customer, state, from_phone, verb: str, matched: dict, context: dict) -> bool | None:
        """Returns False only when the action failed in a way that must block
        advancing to the step's `next` (currently: create_engagement's sold-out
        rejection). None/True (the default for every other verb) means proceed as
        normal -- see the confirm_action branch of _process_input, the only caller that
        inspects this."""
        if verb == "add_to_cart":
            pending = context.get("pending_item")
            if not pending:
                return
            cart = context.get("cart", [])
            cart_was_empty = len(cart) == 0
            cart.append({**pending, "qty": matched.get("qty", 1)})
            context["cart"] = cart
            context.pop("pending_item", None)
            self._refresh_cart_summary(restaurant, context)
            if cart_was_empty:
                self._record_event(restaurant.id, analytics.CART_STARTED, customer_id=customer.id, niche_code=restaurant.niche_type)
            self._record_event(
                restaurant.id, analytics.PRODUCT_ADDED,
                customer_id=customer.id, niche_code=restaurant.niche_type, details={"item_id": pending.get("item_id")},
            )
            return

        if verb == "capture_pending_item":
            item_id = matched["id"].split(":", 1)[1]
            item = await self.item_repo.get(uuid.UUID(item_id), restaurant.id)
            if item:
                context["pending_item"] = {"item_id": str(item.id), "name": item.name, "price": float(item.price or 0)}
                # Flat, template-addressable mirror of the two fields a "how many?"
                # quantity_input prompt typically wants to show -- render_template only
                # does flat {{var}} substitution (see template_engine.py), so the nested
                # pending_item dict itself isn't directly renderable.
                context["pending_item_name"] = item.name
                context["pending_item_price"] = _price_label(restaurant, item, include_attributes=True)
                # Friendlier aliases for message-template authors, same reasoning as the
                # item_id capture-key aliasing in _process_input above.
                context["service_name"] = item.name
                context["product_name"] = item.name
                self._record_event(
                    restaurant.id, analytics.PRODUCT_VIEWED,
                    customer_id=customer.id, niche_code=restaurant.niche_type, details={"item_id": str(item.id)},
                )
            return

        if verb == "remove_cart_line":
            idx = int(matched["id"].split(":")[-1])
            cart = context.get("cart", [])
            if 0 <= idx < len(cart):
                cart.pop(idx)
            context["cart"] = cart
            self._refresh_cart_summary(restaurant, context)
            return

        if verb == "add_to_cart_for_date_range":
            # Booking-niche (e.g. hotel) counterpart of add_to_cart: a date-range
            # engagement prices by nights, not a tapped quantity button, so this reads
            # context["check_in"]/["check_out"] (both bare isoformat dates -- the same
            # no-prefix convention every capture_key value uses, see the menu_select
            # branch of _process_input) instead of a matched qty. Whatever step this
            # action is attached to (its own capture_key, if any, runs first per the
            # normal menu_select order) must run after both dates and a pending_item
            # (via capture_pending_item on an earlier items-select step) are already in
            # context.
            pending = context.get("pending_item")
            if not pending:
                return
            check_in = context.get("check_in")
            check_out = context.get("check_out")
            nights = 1
            if check_in and check_out:
                nights = max((date.fromisoformat(check_out) - date.fromisoformat(check_in)).days, 1)
            cart = context.get("cart", [])
            cart_was_empty = len(cart) == 0
            cart.append({**pending, "qty": nights})
            context["cart"] = cart
            context["nights"] = nights
            context.pop("pending_item", None)
            self._refresh_cart_summary(restaurant, context)
            if cart_was_empty:
                self._record_event(restaurant.id, analytics.CART_STARTED, customer_id=customer.id, niche_code=restaurant.niche_type)
            self._record_event(
                restaurant.id, analytics.PRODUCT_ADDED,
                customer_id=customer.id, niche_code=restaurant.niche_type, details={"item_id": pending.get("item_id"), "nights": nights},
            )
            return

        if verb in ("create_engagement", "create_engagement_paid"):
            return await self._create_engagement(restaurant, customer, state, from_phone, context)

    def _refresh_cart_summary(self, restaurant, context: dict) -> None:
        """Recomputes a plain-text cart summary/total into context after every cart
        mutation, so any order-type niche's cart-review/checkout step can render actual
        line items via `{{cart_summary}}`/`{{cart_total}}` -- render_template only does
        flat `{{var}}` substitution (see template_engine.py), no loops, so this is
        computed here rather than in the template itself. Shared across every
        cart-based niche, not Restaurant-specific.
        """
        cart = context.get("cart", [])
        if not cart:
            context["cart_summary"] = "(cart is empty)"
            context["cart_total"] = "0"
            return
        lines = [f"{c['qty']}x {c['name']} - {restaurant.currency} {c['price'] * c['qty']:.0f}" for c in cart]
        context["cart_summary"] = "\n".join(lines)
        context["cart_total"] = f"{sum(c['price'] * c['qty'] for c in cart):.0f}"

    async def _create_engagement(self, restaurant, customer, state, from_phone, context: dict) -> bool:
        flow_repo = FlowDefinitionRepository(self.session)
        flow_def = await flow_repo.get_by_restaurant(restaurant.id)
        engagement_type = flow_def.action_type

        # STARTED fires here (not at confirm-step render) so it always reflects a real
        # attempt to complete, not just a customer viewing the review card -- see
        # app/services/analytics.py's module docstring for the full event vocabulary.
        started_event = _STARTED_EVENT_BY_ENGAGEMENT_TYPE.get(engagement_type)
        if started_event:
            self._record_event(restaurant.id, started_event, customer_id=customer.id, step_id=state.current_step, niche_code=flow_def.niche_code)

        cart = context.get("cart", [])
        subtotal = sum(line["price"] * line["qty"] for line in cart)
        total = subtotal  # tax/delivery kept at 0 for this pass -- see final report note.

        if self.dry_run:
            # Bot Preview: never create a real Engagement/EngagementItem row, never touch
            # stock, never generate a real payment link, never notify staff -- see
            # app/api/v1/routers/flow_preview.py's module docstring. Synthesizes the same
            # context keys a real create_engagement call sets so the terminal
            # confirmation message still renders correctly, with obviously-fake
            # placeholder data instead of a real reference number.
            context["last_reference_number"] = "PREVIEW-0000"
            context["order_id"] = "PREVIEW-0000"
            context["booking_id"] = "PREVIEW-0000"
            context["last_total"] = f"{total:.2f}"
            context["payment_link_url"] = ""
            context["cart"] = []
            state.context = context
            completed_event = _COMPLETED_EVENT_BY_ENGAGEMENT_TYPE.get(engagement_type)
            if completed_event:
                self._record_event(
                    restaurant.id, completed_event,
                    customer_id=customer.id, step_id=state.current_step, niche_code=flow_def.niche_code,
                    details={"reference_number": "PREVIEW-0000"},
                )
            return True

        # Atomic check-and-decrement per line, same guarantee as the legacy engine's
        # stock handling -- reject-with-message rather than oversell if a concurrent
        # customer took the last unit between add-to-cart and confirm.
        for line in cart:
            if line.get("qty", 1) and line.get("item_id"):
                item = await self.item_repo.get(uuid.UUID(line["item_id"]), restaurant.id)
                if item is not None and item.stock_quantity is not None:
                    ok = await self.item_repo.decrement_stock(item.id, line["qty"])
                    if not ok:
                        await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(
                            from_phone, f"Sorry, *{line['name']}* just sold out. Please remove or reduce it and try again."
                        ))
                        return False

        for attempt in range(3):
            reference = _reference_number(restaurant, engagement_type)
            engagement = Engagement(
                restaurant_id=restaurant.id,
                customer_id=customer.id,
                reference_number=reference,
                type=engagement_type,
                status=EngagementStatus.NEW,
                requires_payment=bool(cart),
                subtotal=subtotal,
                tax=0,
                discount=0,
                total=total,
                details={k: v for k, v in context.items() if not k.startswith("_") and k != "cart"},
            )
            self.session.add(engagement)
            try:
                await self.session.flush()
            except Exception:
                await self.session.rollback()
                continue
            break

        for line in cart:
            self.session.add(
                EngagementItem(
                    engagement_id=engagement.id,
                    catalog_item_id=uuid.UUID(line["item_id"]),
                    name_snapshot=line["name"],
                    price_snapshot=line["price"],
                    quantity=line["qty"],
                )
            )
        await self.session.flush()
        # notify_business's ORDER-type summary reads engagement.items -- eagerly load it
        # now (selectinload populates the relationship on this same identity-mapped
        # object) rather than let that be the first lazy access, which would raise
        # MissingGreenlet in this async context (no lazy-load I/O is safe outside an
        # explicit greenlet_spawn boundary). A cart-less engagement (inquiry/appointment/
        # booking) never touches engagement.items at all, so this only matters for order.
        await self.engagement_repo.get_with_items(engagement.id, restaurant.id)

        context["last_reference_number"] = engagement.reference_number
        # {{order_id}}/{{booking_id}} aliases -- same reference number, named per the
        # two vocabularies message-template authors actually use depending on niche.
        context["order_id"] = engagement.reference_number
        context["booking_id"] = engagement.reference_number
        context["last_total"] = f"{total:.2f}"
        context["cart"] = []

        completed_event = _COMPLETED_EVENT_BY_ENGAGEMENT_TYPE.get(engagement_type)
        if completed_event:
            self._record_event(
                restaurant.id, completed_event,
                customer_id=customer.id, step_id=state.current_step, niche_code=flow_def.niche_code,
                details={"reference_number": engagement.reference_number},
            )

        # Only for money-bearing engagements (order/booking with a non-zero total) -- an
        # inquiry/appointment never reaches here with requires_payment set. See
        # app/services/payment/generic_razorpay.py's module docstring for why this only
        # sends a link and never marks payment_status "paid" itself.
        #
        # `restaurant.is_demo` is checked explicitly here rather than left to
        # create_payment_link's own no-op-when-unconfigured behavior: a demo restaurant
        # never having real Razorpay keys set is true today only because nothing sets
        # them, not because anything enforces it -- the existing restaurant-update
        # endpoint has no guard stopping a Super Admin from pointing real credentials at
        # a demo restaurant. This makes "a demo never generates a real payment link" an
        # enforced invariant instead of an accident of unset fields.
        if engagement.requires_payment and total > 0 and not restaurant.is_demo:
            from app.services.payment.generic_razorpay import create_payment_link

            self._record_event(
                restaurant.id, analytics.PAYMENT_STARTED,
                customer_id=customer.id, niche_code=flow_def.niche_code,
                details={"reference_number": engagement.reference_number, "total": str(total)},
            )
            result = await create_payment_link(restaurant, engagement)
            if result.get("payment_link_url"):
                engagement.gateway_metadata = {**engagement.gateway_metadata, **result}
                engagement.payment_method = "razorpay"
                context["payment_link_url"] = result["payment_link_url"]
                await self.session.flush()
            else:
                # No real gateway configured (or the call failed) -- every order/booking
                # niche's confirmation copy has a bare "{{payment_link_url}}" line (see
                # niche_seeds/*.py), which would otherwise collapse to a blank line and
                # read as broken. A plain-language fallback keeps the message coherent
                # without implying a link was actually sent.
                context["payment_link_url"] = "💳 We'll share a secure payment link here shortly, or you can pay on delivery/pickup."
        elif engagement.requires_payment and total > 0:
            # `restaurant.is_demo` guard above skipped real gateway creation entirely --
            # same fallback copy, so a demo business's order confirmation reads the same
            # as a real one that's still waiting on its payment link.
            context["payment_link_url"] = "💳 We'll share a secure payment link here shortly, or you can pay on delivery/pickup."

        state.context = context

        # Same reasoning as the payment-link skip above: never send a real staff
        # notification for a demo restaurant, regardless of whether
        # staff_notification_number happens to be unset.
        if not restaurant.is_demo:
            await notify_business(self.session, self.sender, restaurant, engagement, customer)
        await self._broadcast(restaurant.id, {"type": "engagement_created", "engagement_id": str(engagement.id)})
        return True

    async def _time_slot_options(self, restaurant, context: dict) -> list[dict[str, Any]]:
        from sqlalchemy import select

        date_key = context.get("date") or context.get("check_in")
        if not date_key:
            return []
        target_date = date.fromisoformat(date_key)
        staff_id = context.get("staff_id")
        working = {"start": "09:00", "end": "18:00"}
        is_specific_staff = bool(staff_id) and staff_id != "any"
        if is_specific_staff:
            staff = await self.staff_repo.get(uuid.UUID(staff_id), restaurant.id)
            day_key = target_date.strftime("%a").lower()[:3]
            windows = (staff.working_hours or {}).get(day_key) if staff else None
            if windows:
                working = {"start": windows[0][0], "end": windows[0][1]}

        booked_result = await self.session.execute(
            select(Engagement.details).where(
                Engagement.restaurant_id == restaurant.id,
                Engagement.type == EngagementType.APPOINTMENT,
                Engagement.status != EngagementStatus.CANCELLED,
            )
        )
        booked_times = set()
        for (details,) in booked_result.all():
            if details.get("date") != date_key:
                continue
            # "Any Available" booked against a specific staff member doesn't block that
            # same slot for a different staff member -- only count a booking as
            # conflicting when it's for the same staff this customer is booking (or when
            # this customer isn't asking for a specific staff member at all, in which
            # case any existing booking at that time is being conservative and treating
            # the slot as unavailable business-wide).
            if is_specific_staff and details.get("staff_id") not in (staff_id, None, "any"):
                continue
            booked_times.add(details.get("time"))

        start_h = int(working["start"].split(":")[0])
        end_h = int(working["end"].split(":")[0])
        slots = []
        for hour in range(start_h, end_h):
            for minute in (0, 30):
                label = f"{hour:02d}:{minute:02d}"
                if label in booked_times:
                    continue
                slots.append({"id": f"time:{label}", "title": label})
        return slots[:10]


def _price_label(restaurant, item, include_attributes: bool = False) -> str:
    if item.price is None:
        label = "On request"
    else:
        price_type_labels = {
            "starting_from": f"From {restaurant.currency} {item.price:.0f}+",
            "per_hour": f"{restaurant.currency} {item.price:.0f}/hr",
            "on_request": "On request",
            "free": "Free",
        }
        label = price_type_labels.get(item.price_type, f"{restaurant.currency} {item.price:.0f}")
    if not include_attributes:
        return label
    attributes = item.attributes or {}
    duration = attributes.get("duration_minutes")
    if duration:
        hours, minutes = divmod(int(duration), 60)
        duration_label = (f"{hours}h " if hours else "") + (f"{minutes}min" if minutes else "")
        label = f"{label} · {duration_label.strip()}"
    return label


def _date_options(min_offset_days: int = 0) -> list[dict[str, str]]:
    today = date.today()
    options = []
    labels = {0: "Today", 1: "Tomorrow"}
    for offset in range(min_offset_days, min_offset_days + 6):
        d = today + timedelta(days=offset)
        label = labels.get(offset - min_offset_days) if min_offset_days == 0 else None
        title = label or d.strftime("%a %d %b")
        options.append({"id": f"date:{d.isoformat()}", "title": title})
    return options[:10]
