"""Regression tests for the WhatsApp bot speed-optimization pass that followed the
latency investigation (see WHATSAPP_LATENCY_REPORT.md). Covers:

1. An explicit button/list reply on a `menu_select` step never calls `_resolve_options`
   (generic_flow_engine.py::_Engine.handle) -- its result is provably unused for that
   case, per `resolve_interaction`'s own short-circuit on a real `reply_id`.
2. Free text on the same kind of step still calls `_resolve_options` -- the optimization
   only skips the call when it's genuinely unnecessary, never for the free-text/fuzzy
   path that actually needs it.
3. The Demo Bot's ordinary mid-demo turn no longer re-fetches the same Customer/
   FlowDefinition rows a second time (demo_bot_service.py).
4. GenericConversationState's row lock (`get_for_update_by_customer`) is still acquired
   fresh on every turn, even when a caller passes in an already-fetched customer/flow_def
   -- the one read that must never be satisfied from an earlier unlocked peek.
5. Image messages are still always sent before their accompanying text message for the
   "message" step type (generic_flow_engine.py::_render_step) -- the one place this pass
   also corrected a stale, actively-misleading comment that claimed concurrent dispatch.

No real Meta API is reachable from any test here: every test uses InMemoryWhatsAppSender.
"""

import itertools
import uuid

import pytest_asyncio
from sqlalchemy import select

import app.services.generic_flow_engine as generic_flow_engine
from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.niche_seeds.restaurant import TEMPLATE
from app.repositories.customer_repository import CustomerRepository
from app.repositories.flow_definition_repository import FlowDefinitionRepository
from app.repositories.generic_conversation_repository import GenericConversationStateRepository
from app.services.demo_bot_service import handle_demo_inbound
from app.services.demo_restaurant_sync import sync_demo_restaurants
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.image_presenter import ItemImage
from app.services.niche_provisioning import provision_from_template
from app.services.niche_template_sync import sync_niche_templates
from app.services.whatsapp_client import InMemoryWhatsAppSender

PHONE_NUMBER_ID = "SPEED_OPT_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919876500088"
SENTINEL_PHONE_NUMBER_ID = "SPEED_OPT_DEMO_SENTINEL_PHONE_NUMBER_ID"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.speedopt.test.{next(_wamid_counter)}"


@pytest_asyncio.fixture
async def sender():
    return InMemoryWhatsAppSender()


@pytest_asyncio.fixture
async def restaurant_tenant(db_session):
    restaurant = Restaurant(
        name="Speed Opt Kitchen",
        slug="speed-opt-kitchen",
        whatsapp_phone_number_id=PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        staff_notification_number="919876500002",
    )
    db_session.add(restaurant)
    await db_session.flush()

    template = NicheTemplate(
        code=TEMPLATE["code"], name=TEMPLATE["name"], action_type=TEMPLATE["action_type"],
        icon=TEMPLATE["icon"], welcome_message=TEMPLATE["welcome_message"],
        welcome_banner_image=TEMPLATE["welcome_banner_image"], welcome_buttons=TEMPLATE["welcome_buttons"],
        default_catalog=TEMPLATE["default_catalog"], default_flow_steps=TEMPLATE["default_flow_steps"],
        terminology=TEMPLATE["terminology"], default_modules=TEMPLATE["default_modules"],
    )
    db_session.add(template)
    await db_session.flush()
    await provision_from_template(db_session, restaurant, template)
    await db_session.commit()
    return restaurant


def _patch_resolve_options_vs_intent_ordering(monkeypatch) -> list[int]:
    """`_resolve_options` (a real DB round-trip: menu/category/staff lookup + bulk image
    resolution) is legitimately called from more than one place per turn -- e.g.
    `_process_input`'s menu_select branch (validating the tapped option against the real
    list) and `_send_options` (rendering whichever step comes next). Counting ALL calls
    for a turn can't isolate the one specific call this optimization targets: the
    intent-resolution block at the top of `handle()`, which used to run
    unconditionally and feed `resolve_interaction` -- a function that itself ignores
    `options` entirely the instant `interaction.reply_id` is set.

    So instead of counting total calls, this records how many `_resolve_options` calls
    had already happened by the moment `resolve_interaction` is invoked -- which isolates
    exactly the one call site this fix touches, regardless of what happens later in the
    same turn (validation, re-rendering, advancing to the next step).
    """
    class _Recorder:
        resolve_options_count = 0
        snapshots: list[int] = []

    original_resolve_options = generic_flow_engine._Engine._resolve_options

    async def _counting_resolve_options(self, restaurant, state, step):
        _Recorder.resolve_options_count += 1
        return await original_resolve_options(self, restaurant, state, step)

    original_resolve_interaction = generic_flow_engine.resolve_interaction

    def _recording_resolve_interaction(interaction, options, context, restaurant):
        _Recorder.snapshots.append(_Recorder.resolve_options_count)
        return original_resolve_interaction(interaction, options, context, restaurant)

    monkeypatch.setattr(generic_flow_engine._Engine, "_resolve_options", _counting_resolve_options)
    monkeypatch.setattr(generic_flow_engine, "resolve_interaction", _recording_resolve_interaction)
    return _Recorder


# --- #1 / #2: _resolve_options only runs when free text genuinely needs it --------------


async def test_button_reply_on_menu_select_step_does_not_call_resolve_options(db_session, restaurant_tenant, sender, monkeypatch):
    recorder = _patch_resolve_options_vs_intent_ordering(monkeypatch)

    await process_inbound_message(db_session, sender, restaurant_tenant, CUSTOMER_PHONE, GenericInteraction(kind="text", text="Hi"), wa_message_id=_next_wamid())
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id="welcome:order", text="Order Now"),
        wa_message_id=_next_wamid(),
    )
    starters = (await db_session.execute(
        select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant_tenant.id, CatalogCategory.name == "Starters")
    )).scalar_one()

    recorder.snapshots.clear()
    count_before = recorder.resolve_options_count
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id=f"category:{starters.id}", text="Starters"),
        wa_message_id=_next_wamid(),
    )
    # The whole point of the fix: for a real button/list tap, zero NEW _resolve_options
    # calls have happened by the time resolve_interaction runs this turn -- the wasteful
    # DB round trip that used to feed it (and whose result it would have ignored anyway)
    # is skipped. (_resolve_options may still be called later in the SAME turn, e.g. to
    # validate the tap or render the next step -- this only isolates the one call site
    # the fix actually touches.)
    assert recorder.snapshots == [count_before]


async def test_free_text_on_menu_select_step_still_calls_resolve_options(db_session, restaurant_tenant, sender, monkeypatch):
    recorder = _patch_resolve_options_vs_intent_ordering(monkeypatch)

    await process_inbound_message(db_session, sender, restaurant_tenant, CUSTOMER_PHONE, GenericInteraction(kind="text", text="Hi"), wa_message_id=_next_wamid())

    recorder.snapshots.clear()
    count_before = recorder.resolve_options_count
    # Free text (no reply_id) on the welcome menu_select step -- fuzzy/ambiguous/
    # disambiguation handling all depend on resolve_interaction actually seeing real,
    # freshly-resolved options, so _resolve_options must have run at least once by then.
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="text", text="I'd like to place an order"),
        wa_message_id=_next_wamid(),
    )
    assert recorder.snapshots == [count_before + 1]


async def test_single_button_reply_flow_is_unchanged_end_to_end(db_session, restaurant_tenant, sender):
    """The optimization must be invisible from the customer's point of view -- an
    ordinary single button tap still advances the conversation and sends exactly the
    reply it always did."""
    await process_inbound_message(db_session, sender, restaurant_tenant, CUSTOMER_PHONE, GenericInteraction(kind="text", text="Hi"), wa_message_id=_next_wamid())
    sender.sent.clear()
    await process_inbound_message(
        db_session, sender, restaurant_tenant, CUSTOMER_PHONE,
        GenericInteraction(kind="button_reply", reply_id="welcome:order", text="Order Now"),
        wa_message_id=_next_wamid(),
    )
    interactive = [m for m in sender.sent if m.payload.get("type") == "interactive"]
    assert interactive, "expected the category_select step's options message to be sent"


# --- #3 / #4: Demo Bot no longer duplicates lookups, locking stays intact ---------------


async def _make_demo_sentinel(db_session) -> Restaurant:
    sentinel = Restaurant(
        name="Speed Opt Demo Bot", slug="speed-opt-demo-bot", is_demo=True,
        whatsapp_phone_number_id=SENTINEL_PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("sentinel-token"),
    )
    db_session.add(sentinel)
    await db_session.flush()
    return sentinel


async def test_demo_bot_ordinary_turn_does_not_duplicate_customer_or_flow_definition_lookups(db_session, monkeypatch):
    sentinel = await _make_demo_sentinel(db_session)
    await sync_niche_templates(db_session)
    await sync_demo_restaurants(db_session, sentinel.id)

    sender = InMemoryWhatsAppSender()
    phone = "919999955557"

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender, sentinel, phone,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:restaurant", text="Restaurant"),
        wa_message_id=_next_wamid(),
    )
    restaurant = (await db_session.execute(
        select(Restaurant).where(Restaurant.niche_type == "restaurant", Restaurant.is_demo.is_(True))
    )).scalar_one()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id="welcome:order", text="Order Now"), wa_message_id=_next_wamid())
    category = (await db_session.execute(
        select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant.id, CatalogCategory.name == "Starters")
    )).scalar_one()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}", text="Starters"), wa_message_id=_next_wamid())
    item = (await db_session.execute(
        select(CatalogItem).where(CatalogItem.restaurant_id == restaurant.id, CatalogItem.category_id == category.id)
    )).scalars().first()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}", text=item.name), wa_message_id=_next_wamid())
    # Now sitting at quantity_select -- an ordinary "already mid-demo" turn from here.

    customer_calls: list[uuid.UUID] = []
    original_get_or_create = CustomerRepository.get_or_create

    async def _counting_get_or_create(self, restaurant_id, phone_arg):
        customer_calls.append(restaurant_id)
        return await original_get_or_create(self, restaurant_id, phone_arg)

    flow_def_calls: list[uuid.UUID] = []
    original_get_by_restaurant = FlowDefinitionRepository.get_by_restaurant

    async def _counting_get_by_restaurant(self, restaurant_id):
        flow_def_calls.append(restaurant_id)
        return await original_get_by_restaurant(self, restaurant_id)

    lock_calls: list[uuid.UUID] = []
    original_get_for_update = GenericConversationStateRepository.get_for_update_by_customer

    async def _counting_get_for_update(self, customer_id):
        lock_calls.append(customer_id)
        return await original_get_for_update(self, customer_id)

    monkeypatch.setattr(CustomerRepository, "get_or_create", _counting_get_or_create)
    monkeypatch.setattr(FlowDefinitionRepository, "get_by_restaurant", _counting_get_by_restaurant)
    monkeypatch.setattr(GenericConversationStateRepository, "get_for_update_by_customer", _counting_get_for_update)

    # The actual regression case: an ordinary mid-order message ("menu" is NOT in
    # _LEAVE_TO_PICKER_WORDS -- see demo_bot_service.py) that falls all the way through
    # to handle_demo_inbound's "delegate straight into the real engine" branch.
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="menu"), wa_message_id=_next_wamid())

    restaurant_scoped_customer_calls = [r for r in customer_calls if r == restaurant.id]
    restaurant_scoped_flow_def_calls = [r for r in flow_def_calls if r == restaurant.id]
    assert len(restaurant_scoped_customer_calls) == 1, "Customer should be fetched exactly once per turn (was 2 before the fix)"
    assert len(restaurant_scoped_flow_def_calls) == 1, "FlowDefinition should be fetched exactly once per turn (was 2 before the fix)"
    # Never weakened: the ConversationState row lock must still be acquired freshly for
    # this turn, exactly once -- never skipped or satisfied from
    # _customer_is_at_a_terminal_step's own separate, unlocked read.
    assert len(lock_calls) == 1


# --- #5: image-before-text ordering for the "message" step type -------------------------


async def test_message_step_sends_curated_images_before_its_text(db_session, restaurant_tenant, sender, monkeypatch):
    """Regression guard for the exact site whose comment previously (incorrectly) claimed
    concurrent dispatch -- generic_flow_engine.py::_Engine._render_step's "message" step
    type. send_generic_messages_batch sends sequentially, in list order; this proves the
    list itself is still built image(s)-first, text-last here."""

    async def _fake_step_gallery(self, restaurant, step):
        return [ItemImage(url="https://example.test/banner.jpg", caption="Banner")]

    monkeypatch.setattr(generic_flow_engine._Engine, "_step_gallery", _fake_step_gallery)

    customer = await CustomerRepository(db_session).get_or_create(restaurant_tenant.id, CUSTOMER_PHONE)
    state = GenericConversationState(restaurant_id=restaurant_tenant.id, customer_id=customer.id, current_step="message_test", context={})
    db_session.add(state)
    await db_session.flush()

    engine = generic_flow_engine._Engine(db_session, sender, dry_run=False)
    engine.flow_id = uuid.uuid4()  # _step_gallery is stubbed above -- never actually queried by this id
    step = {"step_id": "message_test", "type": "message", "prompt": "Here is our menu!", "show_image": True}
    await engine._render_step(restaurant_tenant, customer, state, CUSTOMER_PHONE, step, {"message_test": step})

    assert [m.payload.get("type") for m in sender.sent] == ["image", "text"]
    assert sender.sent[0].payload["image"]["link"] == "https://example.test/banner.jpg"
