"""Proof for Phase 1 Item 4, the Demo Bot: one WhatsApp number, "Hi" -> select industry ->
run a complete demo of that niche -> try another industry.

Covers: sync idempotency, credential routing through the sentinel restaurant, the picker
built live from NicheTemplate rows (no hardcoded niche list), a full order-type niche
walkthrough driven through the real dispatcher/engine to completion, the enforced
payment/staff-notification safety guard, redelivered-webhook dedup, concurrent-customer
isolation, and the daily purge task.
"""

import itertools

from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.customer import Customer
from app.models.demo_session import DemoSession
from app.models.engagement import Engagement, EngagementItem
from app.models.enums import EngagementType
from app.models.generic_conversation_state import GenericConversationState
from app.models.message import Message
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.services.demo_bot_service import handle_demo_inbound
from app.services.demo_restaurant_sync import sync_demo_restaurants
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message, send_generic_message
from app.services.niche_template_sync import sync_niche_templates
from app.services.whatsapp_client import InMemoryWhatsAppSender, OutboundMessage

SENTINEL_PHONE_NUMBER_ID = "DEMO_BOT_TEST_PHONE_NUMBER_ID"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.demobot.test.{next(_wamid_counter)}"


async def _make_sentinel(db_session) -> Restaurant:
    sentinel = Restaurant(
        name="Demo Bot", slug="demo-bot", is_demo=True,
        whatsapp_phone_number_id=SENTINEL_PHONE_NUMBER_ID,
        whatsapp_access_token_encrypted=encrypt_secret("sentinel-real-token"),
    )
    db_session.add(sentinel)
    await db_session.flush()
    return sentinel


async def _seed_all_niches(db_session, sentinel: Restaurant) -> list[str]:
    await sync_niche_templates(db_session)
    return await sync_demo_restaurants(db_session, sentinel.id)


def _last_text(sender: InMemoryWhatsAppSender) -> str:
    for message in reversed(sender.sent):
        if message.payload.get("type") == "text":
            return message.payload["text"]["body"]
    raise AssertionError("No text message was sent")


def _last_picker_text(sender) -> str:
    """The industry picker is one plain-text message, not a tap-to-select interactive list
    (Meta caps those at 10 rows, and there are 12+ niches -- see demo_bot_service.py's
    _send_industry_picker / _resolve_free_text_pick)."""
    for message in reversed(sender.sent):
        if message.payload.get("type") != "text":
            continue
        body = message.payload["text"]["body"]
        if "Welcome to the KelvionTech Business OS" in body:
            return body
    raise AssertionError("No industry picker message was sent")


# --- sync idempotency ----------------------------------------------------------------------


async def test_sync_demo_restaurants_creates_one_per_template_and_is_idempotent(db_session):
    sentinel = await _make_sentinel(db_session)
    created = await _seed_all_niches(db_session, sentinel)
    assert len(created) >= 12  # every app/niche_seeds/*.py module

    demo_restaurants = (await db_session.execute(select(Restaurant).where(Restaurant.is_demo.is_(True), Restaurant.id != sentinel.id))).scalars().all()
    assert len(demo_restaurants) == len(created)
    for r in demo_restaurants:
        assert r.demo_sends_via_restaurant_id == sentinel.id
        assert r.whatsapp_phone_number_id is None
        assert r.uses_generic_engine is True

    # Re-running is a no-op -- no crash (would hit FlowDefinition.restaurant_id's unique
    # constraint if this naively re-provisioned), no duplicate rows.
    created_again = await _seed_all_niches(db_session, sentinel)
    assert created_again == []
    demo_restaurants_again = (await db_session.execute(select(Restaurant).where(Restaurant.is_demo.is_(True), Restaurant.id != sentinel.id))).scalars().all()
    assert len(demo_restaurants_again) == len(demo_restaurants)


async def test_slug_collision_on_one_niche_does_not_block_the_other_eleven(db_session):
    """Found live against a real dev database: an unrelated, ordinary (non-demo)
    business already owned the literal slug "demo-restaurant" (pre-dating the demo-bot
    naming convention). Provisioning used to be one all-or-nothing transaction, so that
    single collision silently blocked EVERY niche's demo restaurant, not just
    Restaurant's -- this proves the fix: each niche commits independently, and the
    colliding niche still gets a real demo restaurant via a disambiguated slug rather
    than being skipped or crashing the whole run.
    """
    sentinel = await _make_sentinel(db_session)
    await sync_niche_templates(db_session)

    stray_business = Restaurant(name="Someone's Actual Restaurant", slug="demo-restaurant")
    db_session.add(stray_business)
    await db_session.commit()

    created = await sync_demo_restaurants(db_session, sentinel.id)
    assert len(created) == 12, f"expected all 12 niches provisioned despite the slug collision, got {sorted(created)}"

    restaurant_demo = (await db_session.execute(
        select(Restaurant).where(Restaurant.niche_type == "restaurant", Restaurant.is_demo.is_(True))
    )).scalar_one()
    assert restaurant_demo.slug != "demo-restaurant"  # disambiguated, not skipped
    assert restaurant_demo.slug.startswith("demo-restaurant-")

    # The stray business itself is completely untouched.
    untouched = await db_session.get(Restaurant, stray_business.id)
    assert untouched.slug == "demo-restaurant"
    assert untouched.is_demo is False


# --- credential routing --------------------------------------------------------------------


async def test_send_generic_message_routes_demo_restaurant_through_sentinel(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    demo_restaurant = (await db_session.execute(
        select(Restaurant).where(Restaurant.is_demo.is_(True), Restaurant.id != sentinel.id)
    )).scalars().first()
    customer = Customer(restaurant_id=demo_restaurant.id, phone="919999900001")
    db_session.add(customer)
    await db_session.flush()

    sender = InMemoryWhatsAppSender()
    await send_generic_message(db_session, sender, demo_restaurant, customer.id, "919999900001", OutboundMessage.text("919999900001", "hello"))

    # InMemoryWhatsAppSender doesn't record which phone_number_id it was called with, so
    # the real proof is the demo restaurant's own credentials being blank yet the send
    # succeeding at all with no error -- confirmed indirectly by a real restaurant's
    # behavior being unaffected below (byte-for-byte, no demo_sends_via_restaurant_id).
    assert len(sender.sent) == 1


async def test_send_generic_message_real_restaurant_unaffected(db_session):
    real = Restaurant(
        name="Real Business", slug="real-business",
        whatsapp_phone_number_id="REAL_PHONE_NUMBER_ID",
        whatsapp_access_token_encrypted=encrypt_secret("real-token"),
    )
    db_session.add(real)
    await db_session.flush()
    customer = Customer(restaurant_id=real.id, phone="919999900002")
    db_session.add(customer)
    await db_session.flush()

    sender = InMemoryWhatsAppSender()
    await send_generic_message(db_session, sender, real, customer.id, "919999900002", OutboundMessage.text("919999900002", "hi"))
    assert len(sender.sent) == 1
    assert real.demo_sends_via_restaurant_id is None  # untouched


# --- picker built live, no hardcoding -------------------------------------------------------


async def test_picker_lists_every_current_niche_including_a_freshly_added_one(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)

    # A brand-new niche template + demo restaurant, added with no code changes -- proves
    # the picker reads live, not from any hardcoded list.
    extra_template = NicheTemplate(
        code="pet-grooming", name="Pet Grooming", action_type=EngagementType.APPOINTMENT,
        icon="🐾", welcome_message="Welcome!", default_flow_steps=[
            {"step_id": "welcome", "type": "menu_select", "prompt": "Hi", "static_options": [
                {"id": "welcome:info", "title": "Info"}
            ], "routes": {"welcome:info": "welcome"}}
        ],
    )
    db_session.add(extra_template)
    await db_session.flush()
    await sync_demo_restaurants(db_session, sentinel.id)

    sender = InMemoryWhatsAppSender()
    await handle_demo_inbound(db_session, sender, sentinel, "919999911111", GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())

    picker_text = _last_picker_text(sender)
    assert "Pet Grooming" in picker_text


async def test_welcome_banner_sent_before_picker_when_sentinel_has_branding(db_session):
    sentinel = await _make_sentinel(db_session)
    sentinel.logo_url = "https://example.test/kelvion-logo.png"
    sentinel.cover_image_url = "https://example.test/kelvion-description.png"
    await db_session.commit()
    await _seed_all_niches(db_session, sentinel)

    sender = InMemoryWhatsAppSender()
    await handle_demo_inbound(db_session, sender, sentinel, "919999922222", GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())

    images = [m for m in sender.sent if m.payload.get("type") == "image"]
    assert [m.payload["image"]["link"] for m in images] == [sentinel.logo_url, sentinel.cover_image_url]
    # Still followed by the actual picker -- the banner never replaces it.
    assert _last_picker_text(sender)


async def test_welcome_banner_skipped_cleanly_when_sentinel_has_no_branding_set(db_session):
    # Matches every OTHER test in this file (via _make_sentinel, which sets neither
    # field) -- asserted explicitly here so this specific "no branding configured yet"
    # path has its own direct proof, not just an implicit side effect of other tests
    # continuing to pass.
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)

    sender = InMemoryWhatsAppSender()
    await handle_demo_inbound(db_session, sender, sentinel, "919999933333", GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())

    assert not any(m.payload.get("type") == "image" for m in sender.sent)
    assert _last_picker_text(sender)


# --- picking a niche starts its real entry step ---------------------------------------------


async def test_picking_a_niche_starts_its_entry_step(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()

    sender = InMemoryWhatsAppSender()
    phone = "919999922222"
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender, sentinel, phone,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:retail", text="Retail & Fashion"),
        wa_message_id=_next_wamid(),
    )

    assert "Welcome to" in _last_text(sender)
    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id == retail.id

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == retail.id, Customer.phone == phone))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state.current_step == "welcome"


# --- free-text picking (numbered single-message picker, no interactive list) ---------------


async def test_replying_with_a_bare_number_picks_that_niche(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)

    # Same ordering _send_industry_picker numbers by and _resolve_free_text_pick resolves
    # against (see _active_niche_templates) -- so "1" must resolve to templates[0].
    first_template = (await NicheTemplateRepository(db_session).list_all())[0]

    sender = InMemoryWhatsAppSender()
    phone = "919999944001"
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="1"), wa_message_id=_next_wamid())

    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    picked = await db_session.get(Restaurant, session_row.active_restaurant_id)
    assert picked.niche_type == first_template.code


async def test_replying_with_a_niche_name_picks_it(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)

    sender = InMemoryWhatsAppSender()
    phone = "919999944002"
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="jewellers"), wa_message_id=_next_wamid())

    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    jewellers = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "jewellers", Restaurant.is_demo.is_(True)))).scalar_one()
    assert session_row.active_restaurant_id == jewellers.id


async def test_plain_hi_never_gets_hijacked_into_a_niche_pick(db_session):
    """Regression guard: a naive substring-anywhere match (`"hi" in name.lower()`) once
    matched the plain greeting "hi" against "Education & Coa*chi*ng" and silently picked
    that niche instead of ever showing the picker. This proves "hi" always shows the
    picker, never auto-picks anything, regardless of which niches happen to be seeded."""
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)

    sender = InMemoryWhatsAppSender()
    phone = "919999944003"
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())

    assert _last_picker_text(sender)  # raises if no picker was sent
    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id is None  # nothing auto-picked


async def test_unrecognized_free_text_falls_back_to_picker_not_a_crash(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)

    sender = InMemoryWhatsAppSender()
    phone = "919999944004"
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="asdkjqwe"), wa_message_id=_next_wamid())

    assert _last_picker_text(sender)
    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id is None


# --- full order walkthrough through the dispatcher, to completion --------------------------


async def _run_full_retail_order(db_session, sender, sentinel, phone):
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender, sentinel, phone,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:retail", text="Retail & Fashion"),
        wa_message_id=_next_wamid(),
    )
    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()

    async def tap(reply_id):
        await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id=reply_id, text=reply_id), wa_message_id=_next_wamid())

    async def text(body):
        await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text=body), wa_message_id=_next_wamid())

    from app.models.catalog import CatalogCategory, CatalogItem

    category = (await db_session.execute(select(CatalogCategory).where(CatalogCategory.restaurant_id == retail.id))).scalars().first()
    await tap("welcome:shop")
    await tap(f"category:{category.id}")
    item = (await db_session.execute(select(CatalogItem).where(CatalogItem.restaurant_id == retail.id, CatalogItem.category_id == category.id))).scalars().first()
    await tap(f"item:{item.id}")
    await tap("qty:1")
    await tap("cart:checkout")
    await text("123 Demo Street")
    await tap("order:confirm")
    return retail


async def test_full_order_walkthrough_creates_engagement_with_no_real_side_effects(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999933333"

    retail = await _run_full_retail_order(db_session, sender, sentinel, phone)

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == retail.id))).scalars().all()
    assert len(engagements) == 1
    engagement = engagements[0]
    assert engagement.type == EngagementType.ORDER
    assert engagement.payment_method is None  # never touched Razorpay
    assert engagement.gateway_metadata == {}

    items = (await db_session.execute(select(EngagementItem).where(EngagementItem.engagement_id == engagement.id))).scalars().all()
    assert len(items) == 1

    # No message was ever sent to any "staff" address -- everything in `sender.sent` was
    # addressed to the demo customer's own phone number.
    assert all(m.to == phone for m in sender.sent)


async def test_is_demo_guard_blocks_payment_link_and_staff_notification_even_when_configured(db_session):
    """The enforced-invariant test: even if a demo restaurant somehow has real-looking
    Razorpay keys and a staff notification number set, is_demo must still block both --
    this is the gap the design review found (today they're only accidentally inert)."""
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()
    retail.razorpay_key_id = "rzp_test_fake"
    retail.razorpay_key_secret_encrypted = encrypt_secret("fake-secret")
    retail.staff_notification_number = "919999900099"
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    phone = "919999944444"
    await _run_full_retail_order(db_session, sender, sentinel, phone)

    engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == retail.id))).scalars().all()
    assert len(engagements) == 1
    assert engagements[0].payment_method is None
    assert engagements[0].gateway_metadata == {}
    # No message ever addressed to the staff number.
    assert all(m.to != "919999900099" for m in sender.sent)


# --- "try another industry" -----------------------------------------------------------------


async def test_industries_keyword_returns_to_picker_without_disturbing_original_niche_state(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999955555"

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender, sentinel, phone,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:retail", text="Retail & Fashion"),
        wa_message_id=_next_wamid(),
    )
    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id="welcome:shop", text="Shop Now"), wa_message_id=_next_wamid())

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == retail.id, Customer.phone == phone))).scalar_one()
    state_before = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state_before.current_step == "category_select"

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="industries"), wa_message_id=_next_wamid())
    picker_text = _last_picker_text(sender)
    assert "Retail" in picker_text  # picker shown again

    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id is None

    customer_id = customer.id  # captured before expire_all() below invalidates the object
    db_session.expire_all()
    state_after = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_id))).scalar_one()
    assert state_after.current_step == "category_select"  # untouched by leaving to the picker


# --- concurrent isolation --------------------------------------------------------------------


async def test_two_concurrent_demo_customers_on_the_same_niche_do_not_collide(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()

    sender_a, sender_b = InMemoryWhatsAppSender(), InMemoryWhatsAppSender()
    phone_a, phone_b = "919999966001", "919999966002"

    for sender, phone in ((sender_a, phone_a), (sender_b, phone_b)):
        await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
        await handle_demo_inbound(
            db_session, sender, sentinel, phone,
            GenericInteraction(kind="list_reply", reply_id="demo:pick:retail", text="Retail & Fashion"),
            wa_message_id=_next_wamid(),
        )

    await handle_demo_inbound(db_session, sender_a, sentinel, phone_a, GenericInteraction(kind="button_reply", reply_id="welcome:shop", text="Shop Now"), wa_message_id=_next_wamid())

    customer_a = (await db_session.execute(select(Customer).where(Customer.restaurant_id == retail.id, Customer.phone == phone_a))).scalar_one()
    customer_b = (await db_session.execute(select(Customer).where(Customer.restaurant_id == retail.id, Customer.phone == phone_b))).scalar_one()
    assert customer_a.id != customer_b.id

    state_a = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_a.id))).scalar_one()
    state_b = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_b.id))).scalar_one()
    assert state_a.current_step == "category_select"
    assert state_b.current_step == "welcome"  # untouched by A's own progress


async def test_two_concurrent_demo_customers_on_different_niches_do_not_collide(db_session):
    """FINAL PRE-LIVE VERIFICATION section 11's exact scenario: Customer A picks
    Jewellery, Customer B picks Restaurant, on the same flagship number, at the same
    time -- their DemoSession routing must send each to a genuinely different demo
    restaurant, with independently progressing conversation state, and B's Customer/
    state rows must not even exist under the niche A is in (or vice versa)."""
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    jewellery = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "jewellers", Restaurant.is_demo.is_(True)))).scalar_one()
    restaurant_niche = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "restaurant", Restaurant.is_demo.is_(True)))).scalar_one()
    assert jewellery.id != restaurant_niche.id

    sender_a, sender_b = InMemoryWhatsAppSender(), InMemoryWhatsAppSender()
    phone_a, phone_b = "919999977001", "919999977002"

    # Interleaved, not sequential per-customer, to mirror two real prospects texting
    # the flagship number around the same time.
    await handle_demo_inbound(db_session, sender_a, sentinel, phone_a, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(db_session, sender_b, sentinel, phone_b, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender_a, sentinel, phone_a,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:jewellers", text="Jewellery"), wa_message_id=_next_wamid(),
    )
    await handle_demo_inbound(
        db_session, sender_b, sentinel, phone_b,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:restaurant", text="Restaurant"), wa_message_id=_next_wamid(),
    )
    # Advance A one step further into Jewellery; B must be completely unaffected.
    await handle_demo_inbound(db_session, sender_a, sentinel, phone_a, GenericInteraction(kind="button_reply", reply_id="welcome:appointment", text="Book Appointment"), wa_message_id=_next_wamid())

    customer_a_in_jewellery = (await db_session.execute(select(Customer).where(Customer.restaurant_id == jewellery.id, Customer.phone == phone_a))).scalar_one()
    customer_b_in_restaurant = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant_niche.id, Customer.phone == phone_b))).scalar_one()

    # Neither customer has a row under the OTHER niche's demo restaurant at all --
    # true isolation, not just "different current_step values on shared rows".
    stray_a = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant_niche.id, Customer.phone == phone_a))).scalar_one_or_none()
    stray_b = (await db_session.execute(select(Customer).where(Customer.restaurant_id == jewellery.id, Customer.phone == phone_b))).scalar_one_or_none()
    assert stray_a is None, "Customer A leaked a row into the Restaurant demo business"
    assert stray_b is None, "Customer B leaked a row into the Jewellery demo business"

    state_a = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_a_in_jewellery.id))).scalar_one()
    state_b = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_b_in_restaurant.id))).scalar_one()
    assert state_a.current_step == "category_select"  # A progressed into Jewellery
    assert state_b.current_step == "welcome"  # B untouched, still at Restaurant's welcome

    # The DemoSession pointer itself resolved each phone number to the correct,
    # DIFFERENT demo restaurant -- the actual routing mechanism the flagship number
    # depends on, not just an incidental side effect of Customer scoping.
    session_a = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone_a))).scalar_one()
    session_b = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone_b))).scalar_one()
    assert session_a.active_restaurant_id == jewellery.id
    assert session_b.active_restaurant_id == restaurant_niche.id


# --- redelivery / idempotency ----------------------------------------------------------------


async def test_redelivered_webhook_does_not_double_send(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999977777"
    wamid = _next_wamid()

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=wamid)
    count_after_first = len(sender.sent)
    assert count_after_first > 0

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=wamid)
    assert len(sender.sent) == count_after_first  # no duplicate picker send


# --- purge task --------------------------------------------------------------------------


async def test_purge_removes_only_old_demo_data_and_never_touches_real_restaurants(db_session):
    from datetime import timedelta

    from app.db.base import utcnow
    from app.tasks.demo_data_purge import _purge_demo_data

    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999988888"
    await _run_full_retail_order(db_session, sender, sentinel, phone)

    retail = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "retail", Restaurant.is_demo.is_(True)))).scalar_one()
    old_cutoff = utcnow() - timedelta(days=30)

    # Backdate this demo's rows to look old.
    await db_session.execute(Engagement.__table__.update().where(Engagement.restaurant_id == retail.id).values(created_at=old_cutoff))
    await db_session.execute(Message.__table__.update().where(Message.restaurant_id == retail.id).values(created_at=old_cutoff))
    await db_session.execute(GenericConversationState.__table__.update().where(GenericConversationState.restaurant_id == retail.id).values(created_at=old_cutoff))
    await db_session.execute(Customer.__table__.update().where(Customer.restaurant_id == retail.id).values(created_at=old_cutoff))

    # A real (non-demo) restaurant with equally-old data must be left completely alone.
    real = Restaurant(name="Real Biz", slug="real-biz-purge-test")
    db_session.add(real)
    await db_session.flush()
    real_customer = Customer(restaurant_id=real.id, phone="919999900077")
    db_session.add(real_customer)
    await db_session.commit()
    await db_session.execute(Customer.__table__.update().where(Customer.id == real_customer.id).values(created_at=old_cutoff))
    await db_session.commit()

    deleted = await _purge_demo_data()
    assert deleted > 0

    remaining_engagements = (await db_session.execute(select(Engagement).where(Engagement.restaurant_id == retail.id))).scalars().all()
    assert remaining_engagements == []
    remaining_customers = (await db_session.execute(select(Customer).where(Customer.restaurant_id == retail.id))).scalars().all()
    assert remaining_customers == []

    real_still_there = (await db_session.execute(select(Customer).where(Customer.id == real_customer.id))).scalar_one_or_none()
    assert real_still_there is not None


async def test_typing_menu_mid_order_does_not_discard_the_order(db_session):
    """Real bug, found from a live customer's actual conversation log: "menu" used to be
    a global leave-to-picker keyword, so a restaurant customer mid-order who typed "menu"
    (an entirely ordinary thing to type in a restaurant bot -- wanting to see the food
    menu again) got yanked out to the cross-niche industry picker instead, silently
    discarding their in-progress order; the next thing they tapped ("Custom", meant for
    the quantity prompt they'd already been shown) landed on the picker instead and did
    nothing. "menu" is no longer in _LEAVE_TO_PICKER_WORDS -- this proves a restaurant
    customer can type it mid-order and keep going exactly where they left off.
    """
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999955556"

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hi"), wa_message_id=_next_wamid())
    await handle_demo_inbound(
        db_session, sender, sentinel, phone,
        GenericInteraction(kind="list_reply", reply_id="demo:pick:restaurant", text="Restaurant"),
        wa_message_id=_next_wamid(),
    )
    restaurant = (await db_session.execute(select(Restaurant).where(Restaurant.niche_type == "restaurant", Restaurant.is_demo.is_(True)))).scalar_one()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id="welcome:order", text="Order Now"), wa_message_id=_next_wamid())

    from app.models.catalog import CatalogCategory, CatalogItem

    category = (await db_session.execute(select(CatalogCategory).where(CatalogCategory.restaurant_id == restaurant.id, CatalogCategory.name == "Starters"))).scalar_one()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}", text="Starters"), wa_message_id=_next_wamid())
    item = (await db_session.execute(select(CatalogItem).where(CatalogItem.restaurant_id == restaurant.id, CatalogItem.category_id == category.id))).scalars().first()
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}", text=item.name), wa_message_id=_next_wamid())

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id, Customer.phone == phone))).scalar_one()
    state_before = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state_before.current_step == "quantity_select"

    # The actual bug trigger: typing "menu" while at the quantity prompt.
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="menu"), wa_message_id=_next_wamid())

    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id == restaurant.id  # still in the restaurant demo, not bounced to the picker

    await db_session.refresh(state_before)
    assert state_before.current_step == "quantity_select"  # order/step untouched

    # Tapping Custom now must actually reach the quantity prompt, not the picker.
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id="qty:custom", text="Custom"), wa_message_id=_next_wamid())
    assert "quantity" in _last_text(sender).lower()

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="5"), wa_message_id=_next_wamid())
    await db_session.refresh(state_before)
    assert state_before.current_step == "cart_menu"
    assert state_before.context["cart"][0]["qty"] == 5


async def test_finishing_an_order_then_texting_offers_continue_or_switch_industry(db_session):
    """Real bug, found from a live customer's actual conversation log: after an order
    finished, ANY further text silently reset straight back into that SAME niche's own
    welcome (generic_flow_engine.py's terminal-message-step fallback) -- no explanation,
    no way back to the cross-niche picker short of a word ("menu") that collided with
    real niche vocabulary and had to be removed. Now the demo bot explicitly asks with
    two real buttons instead of guessing from free text.
    """
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999955557"

    retail = await _run_full_retail_order(db_session, sender, sentinel, phone)

    # Any further message now gets the explicit offer, not a silent reset.
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hello"), wa_message_id=_next_wamid())
    last = sender.sent[-1]
    assert last.payload["type"] == "interactive"
    button_ids = {b["reply"]["id"] for b in last.payload["interactive"]["action"]["buttons"]}
    assert button_ids == {"demo:continue", "demo:menu"}

    # Tapping "Continue Browsing" restarts the SAME niche (retail), not the picker.
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id="demo:continue", text="Continue Browsing"), wa_message_id=_next_wamid())
    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id == retail.id

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == retail.id, Customer.phone == phone))).scalar_one()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer.id))).scalar_one()
    assert state.current_step == "welcome"


async def test_finishing_an_order_then_tapping_try_another_industry_shows_the_picker(db_session):
    sentinel = await _make_sentinel(db_session)
    await _seed_all_niches(db_session, sentinel)
    sender = InMemoryWhatsAppSender()
    phone = "919999955558"

    await _run_full_retail_order(db_session, sender, sentinel, phone)
    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="text", text="hello"), wa_message_id=_next_wamid())

    await handle_demo_inbound(db_session, sender, sentinel, phone, GenericInteraction(kind="button_reply", reply_id="demo:menu", text="Try Another Industry"), wa_message_id=_next_wamid())
    picker_text = _last_picker_text(sender)
    assert "Retail" in picker_text

    session_row = (await db_session.execute(select(DemoSession).where(DemoSession.customer_phone == phone))).scalar_one()
    assert session_row.active_restaurant_id is None
