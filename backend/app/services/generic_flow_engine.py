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

from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.models.customer import Customer
from app.models.engagement import Engagement, EngagementItem
from app.models.enums import EngagementStatus, EngagementType, MessageDirection, MessageSender
from app.models.message import Message
from app.models.restaurant import Restaurant
from app.repositories.catalog_repository import CatalogCategoryRepository, CatalogItemRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.engagement_repository import EngagementRepository
from app.repositories.flow_definition_repository import FlowDefinitionRepository
from app.repositories.generic_conversation_repository import GenericConversationStateRepository
from app.repositories.staff_member_repository import StaffMemberRepository
from app.services.image_presenter import resolve_item_images
from app.services.notification_service import notify_business
from app.services.template_engine import render_template
from app.services.whatsapp_client import OutboundMessage, WhatsAppSender

logger = logging.getLogger(__name__)

BACK_REPLY_ID = "__back__"
SKIP_REPLY_ID = "__skip__"

_GREETING_WORDS = {"hi", "hello", "hey", "hii", "hola", "start", "menu", "yo", "sup", "namaste"}
_PLACEHOLDER_IMAGE = "https://placehold.co/600x400?text={label}"

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
    normalized = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    if not normalized:
        return True
    words = normalized.split()
    return len(words) <= 2 and all(w in _GREETING_WORDS for w in words)


@dataclass
class GenericInteraction:
    kind: str  # "text" | "list_reply" | "button_reply" | "location"
    text: str | None = None
    reply_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    profile_name: str | None = None


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
) -> None:
    """Entry point called by webhook.py for every generic-engine business's inbound
    message -- the direct counterpart of flow_engine.py::process_inbound_message.
    """
    message_repo = _GenericMessageRepo(session)
    if wa_message_id:
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
    await session.flush()

    if flow_def is None:
        await send_generic_message(session, sender, restaurant, customer.id, from_phone, OutboundMessage.text(
            from_phone, "This business hasn't finished setting up its WhatsApp bot yet. Please check back soon."
        ))
        await session.commit()
        return

    engine = _Engine(session, sender)
    await engine.handle(restaurant, customer, state, from_phone, flow_def, interaction)
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
    # A per-niche demo restaurant owns no real WhatsApp number of its own (see
    # app/models/restaurant.py::demo_sends_via_restaurant_id) -- it sends through the one
    # sentinel Demo Bot restaurant's real credentials instead. NULL for every real
    # restaurant, so this is a no-op lookup and behavior is byte-for-byte unchanged for
    # them. Resolved here (not mutated onto `restaurant` itself) because this function
    # commits mid-request elsewhere in the call chain -- writing real credentials onto a
    # demo restaurant's own in-memory row would risk them being flushed to that row
    # permanently, which is exactly what this avoids.
    send_via = restaurant
    if restaurant.demo_sends_via_restaurant_id:
        send_via = await session.get(Restaurant, restaurant.demo_sends_via_restaurant_id)
    access_token = decrypt_secret(send_via.whatsapp_access_token_encrypted or "")
    try:
        await sender.send(send_via.whatsapp_phone_number_id or "", access_token, message)
    except Exception:
        logger.warning("Generic-engine WhatsApp send failed for restaurant %s", restaurant.id, exc_info=True)
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
    def __init__(self, session, sender: WhatsAppSender):
        self.session = session
        self.sender = sender
        self.category_repo = CatalogCategoryRepository(session)
        self.item_repo = CatalogItemRepository(session)
        self.staff_repo = StaffMemberRepository(session)
        self.engagement_repo = EngagementRepository(session)

    # --- top-level dispatch ----------------------------------------------------------

    async def handle(self, restaurant, customer, state, from_phone, flow_def, interaction: GenericInteraction) -> None:
        # A HUMAN_HANDOFF step (see _render_step) sets this -- while True, every
        # automated branch below is skipped entirely. The inbound Message row is already
        # written by process_inbound_message before handle() is ever called, so "log but
        # don't advance" falls out for free; this just broadcasts a live-update signal so
        # staff watching the handed-off conversation see the new message arrive.
        if state.is_handed_over:
            await ws_manager.broadcast(
                restaurant.id, {"type": "generic_inbound_while_handed_off", "customer_id": str(customer.id)}
            )
            return

        steps_by_id = {s["step_id"]: s for s in flow_def.steps}

        if interaction.kind == "text" and _looks_like_greeting(interaction.text or ""):
            state.context = {}
            await self._advance_and_render(restaurant, customer, state, from_phone, steps_by_id[flow_def.entry_step_id], steps_by_id)
            return

        current = steps_by_id.get(state.current_step) or steps_by_id[flow_def.entry_step_id]

        if interaction.reply_id == BACK_REPLY_ID:
            target = current.get("back_target")
            target_step = steps_by_id.get(target) if target else None
            if target_step is not None:
                await self._advance_and_render(restaurant, customer, state, from_phone, target_step, steps_by_id)
            else:
                await self._advance_and_render(restaurant, customer, state, from_phone, current, steps_by_id)
            return

        await self._process_input(restaurant, customer, state, from_phone, current, steps_by_id, interaction)

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

        show_back = bool(step.get("back_target"))

        if step["type"] in ("message",):
            await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, prompt))
            return

        if step["type"] == "human_handoff":
            handoff_message = step.get("message") or "🧑‍💼 Connecting you with our team -- someone will reply here shortly."
            await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.text(from_phone, handoff_message))
            state.is_handed_over = True
            await ws_manager.broadcast(restaurant.id, {"type": "generic_handover", "customer_id": str(customer.id)})
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

        if step["type"] == "quantity_input":
            options = [
                {"id": "qty:1", "title": "1"},
                {"id": "qty:2", "title": "2"},
                {"id": "qty:3", "title": "3"},
                {"id": "qty:custom", "title": "Custom"},
            ]
            await self._send_options(restaurant, customer, from_phone, prompt, options, show_back, step, state.context)
            return

        # menu_select / confirm_action -- both render as a selectable option set.
        options = await self._resolve_options(restaurant, state, step)
        await self._send_options(restaurant, customer, from_phone, prompt, options, show_back, step, state.context)

    async def _prompt_text(self, restaurant: Restaurant, customer: Customer, step: dict, context: dict) -> str:
        template = step.get("prompt") or ""
        # customer_name prefers an explicit override the customer typed at an "Edit Name"
        # step (context["customer_name_override"], if a niche's flow captures one) over
        # the WhatsApp-profile-seeded Customer.name, which itself may still be empty for
        # a first-time contact whose profile has no display name set.
        customer_name = context.get("customer_name_override") or customer.name or ""
        return render_template(
            template,
            {"restaurant_name": restaurant.name, "currency": restaurant.currency, "customer_name": customer_name, **context},
        )

    async def _send_options(self, restaurant, customer, from_phone, body, options, show_back, step, context) -> None:
        all_options = list(options)
        if show_back:
            all_options.append({"id": BACK_REPLY_ID, "title": "⬅ Back"})

        image_url = await self._image_for_step(restaurant, step, context)
        if image_url and step.get("show_image", True):
            caption_lines = [body]
            if step["type"] == "menu_select" and step.get("buttons_from") in ("categories", "items"):
                # Include the description (items already carry price/duration in
                # "description" via _price_label -- see _resolve_options) so the image
                # caption is a real menu/catalog preview, not just a bare name list.
                caption_lines += [
                    f"• {o['title']}" + (f" - {o['description']}" if o.get("description") else "")
                    for o in options[:10]
                ]
            await send_generic_message(self.session, self.sender, restaurant, customer.id, from_phone, OutboundMessage.image(from_phone, image_url, "\n".join(caption_lines)[:1024]))

        # Meta caps interactive-button messages at 3 total buttons; use a list (cap 10)
        # whenever that would be exceeded, so Back always has room instead of getting
        # silently dropped.
        if len(all_options) <= 3:
            await send_generic_message(
                self.session, self.sender, restaurant, customer.id, from_phone,
                OutboundMessage.interactive_buttons(from_phone, body, [{"id": o["id"], "title": o["title"][:20]} for o in all_options]),
            )
        else:
            rows = [{"id": o["id"], "title": o["title"][:24], "description": o.get("description", "")[:72]} for o in all_options]
            await send_generic_message(
                self.session, self.sender, restaurant, customer.id, from_phone,
                OutboundMessage.interactive_list(from_phone, body, "Select", rows, step.get("section_title", "Options")),
            )

    async def _image_for_step(self, restaurant: Restaurant, step: dict, context: dict) -> str | None:
        source = step.get("buttons_from")
        if source == "categories":
            categories = await self.category_repo.list_visible(restaurant.id)
            for c in categories:
                if c.image_url:
                    return c.image_url
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
                        return images[0]
        elif step.get("item_context_key"):
            item_id = context.get(step["item_context_key"])
            if item_id:
                item = await self.item_repo.get(uuid.UUID(item_id), restaurant.id)
                if item:
                    images = await resolve_item_images(self.session, item, restaurant.id)
                    if images:
                        return images[0]
        if step.get("id") == "welcome" or source == "welcome":
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
            return [{"id": f"category:{c.id}", "title": c.name} for c in categories]

        if source == "items":
            category_id = context.get(step.get("category_context_key", "category_id"))
            if not category_id:
                return []
            items = await self.item_repo.list_by_category(uuid.UUID(category_id), restaurant.id)
            return [
                {
                    "id": f"item:{i.id}",
                    "title": i.name,
                    "description": _price_label(restaurant, i, include_attributes=True),
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
            cart.append({**pending, "qty": matched.get("qty", 1)})
            context["cart"] = cart
            context.pop("pending_item", None)
            self._refresh_cart_summary(restaurant, context)
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
            cart.append({**pending, "qty": nights})
            context["cart"] = cart
            context["nights"] = nights
            context.pop("pending_item", None)
            self._refresh_cart_summary(restaurant, context)
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

        cart = context.get("cart", [])
        subtotal = sum(line["price"] * line["qty"] for line in cart)
        total = subtotal  # tax/delivery kept at 0 for this pass -- see final report note.

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
        context["last_total"] = f"{total:.2f}"
        context["cart"] = []

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

            result = await create_payment_link(restaurant, engagement)
            if result.get("payment_link_url"):
                engagement.gateway_metadata = {**engagement.gateway_metadata, **result}
                engagement.payment_method = "razorpay"
                context["payment_link_url"] = result["payment_link_url"]
                await self.session.flush()
            else:
                context["payment_link_url"] = None
        elif engagement.requires_payment and total > 0:
            context["payment_link_url"] = None

        state.context = context

        # Same reasoning as the payment-link skip above: never send a real staff
        # notification for a demo restaurant, regardless of whether
        # staff_notification_number happens to be unset.
        if not restaurant.is_demo:
            await notify_business(self.session, self.sender, restaurant, engagement, customer)
        await ws_manager.broadcast(restaurant.id, {"type": "engagement_created", "engagement_id": str(engagement.id)})
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
