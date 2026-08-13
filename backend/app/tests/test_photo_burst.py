"""Coverage for the photo-burst gating in generic_flow_engine.py::_Engine._send_options /
._photo_burst_urls (see the approved plan "Niche Image Editor + Visual Category Browsing").
Reuses the Jewellers e2e fixture from test_niche_jewellers.py -- the niche the feature was
designed around -- and drives the real conversation engine end-to-end, since
send_generic_message writes a real Message row keyed to a real Customer/Restaurant, so a
bare unit call isn't a natural fit here.
"""

import uuid

from app.models.catalog import CatalogItem
from app.services.generic_flow_engine import _PHOTO_BURST_MAX_DEFAULT
from app.tests.test_niche_jewellers import (
    CUSTOMER_PHONE,
    CUSTOMER_PROFILE_NAME,
    _get_category_id,
    _get_item,
    _send_text,
    _tap,
    jewellers_tenant,
    sender,
)


async def test_shared_category_image_still_uses_old_single_combo_image(db_session, jewellers_tenant, sender):
    """Backward-compat proof: Gold Jewellery's two items share one image in the seed data
    (see app/niche_seeds/jewellers.py) -- burst must NOT fire, exact old behavior."""
    restaurant = jewellers_tenant
    gold_category_id = await _get_category_id(db_session, restaurant.id, "Gold Jewellery")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:explore")
    before = len(sender.sent)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    sent = sender.sent[before:]

    image_messages = [m for m in sent if m.payload.get("type") == "image"]
    text_messages = [m for m in sent if m.payload.get("type") == "text"]
    assert len(image_messages) == 1  # the old single combo image, not a burst
    assert len(text_messages) == 0  # no separate burst-mode intro text
    caption = image_messages[0].payload["image"]["caption"]
    assert "Gold Necklace" in caption and "Gold Bangles" in caption


async def test_distinct_item_photos_trigger_a_photo_burst_before_the_selector(db_session, jewellers_tenant, sender):
    restaurant = jewellers_tenant
    gold_category_id = await _get_category_id(db_session, restaurant.id, "Gold Jewellery")
    necklace = await _get_item(db_session, restaurant.id, "Gold Necklace")
    bangles = await _get_item(db_session, restaurant.id, "Gold Bangles")
    necklace.images = ["https://cdn.example.com/necklace.jpg"]
    bangles.images = ["https://cdn.example.com/bangles.jpg"]
    await db_session.commit()

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:explore")
    before = len(sender.sent)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    sent = sender.sent[before:]

    # Intro text, then each item's own photo, then the interactive selector -- in order.
    assert sent[0].payload.get("type") == "text"
    image_messages = [m for m in sent if m.payload.get("type") == "image"]
    assert [m.payload["image"]["link"] for m in image_messages] == [
        "https://cdn.example.com/necklace.jpg", "https://cdn.example.com/bangles.jpg",
    ]
    assert image_messages[0].payload["image"]["caption"].startswith("Gold Necklace")
    assert image_messages[1].payload["image"]["caption"].startswith("Gold Bangles")
    assert sent[-1].payload.get("type") == "interactive"


async def test_partial_photography_falls_back_to_combo_image_not_a_mixed_burst(db_session, jewellers_tenant, sender):
    """One item has a real, distinct photo; the other still has none -- the strict
    all-or-nothing gate means this must fall back to the old combo-image behavior rather
    than bursting a mismatched mix (the exact case the design review flagged)."""
    restaurant = jewellers_tenant
    gold_category_id = await _get_category_id(db_session, restaurant.id, "Gold Jewellery")
    necklace = await _get_item(db_session, restaurant.id, "Gold Necklace")
    bangles = await _get_item(db_session, restaurant.id, "Gold Bangles")
    necklace.images = ["https://cdn.example.com/necklace.jpg"]
    bangles.images = []
    await db_session.commit()

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:explore")
    before = len(sender.sent)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    sent = sender.sent[before:]

    image_messages = [m for m in sent if m.payload.get("type") == "image"]
    text_messages = [m for m in sent if m.payload.get("type") == "text"]
    assert len(image_messages) == 1  # combo-image fallback, not a burst
    assert len(text_messages) == 0


async def test_category_exceeding_photo_burst_max_falls_back_to_combo_image(db_session, jewellers_tenant, sender):
    restaurant = jewellers_tenant
    gold_category_id = await _get_category_id(db_session, restaurant.id, "Gold Jewellery")
    necklace = await _get_item(db_session, restaurant.id, "Gold Necklace")
    bangles = await _get_item(db_session, restaurant.id, "Gold Bangles")
    necklace.images = ["https://cdn.example.com/necklace.jpg"]
    bangles.images = ["https://cdn.example.com/bangles.jpg"]
    # Push the category past _PHOTO_BURST_MAX_DEFAULT with extra items, each its own
    # distinct real photo -- proves the cap wins even when every option WOULD otherwise
    # qualify for a burst.
    extra_needed = (_PHOTO_BURST_MAX_DEFAULT + 1) - 2
    for i in range(extra_needed):
        db_session.add(
            CatalogItem(
                id=uuid.uuid4(), restaurant_id=restaurant.id, category_id=uuid.UUID(gold_category_id),
                name=f"Extra Gold Item {i}", images=[f"https://cdn.example.com/extra-{i}.jpg"],
                price=1000, display_order=10 + i,
            )
        )
    await db_session.commit()

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:explore")
    before = len(sender.sent)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{gold_category_id}")
    sent = sender.sent[before:]

    image_messages = [m for m in sent if m.payload.get("type") == "image"]
    text_messages = [m for m in sent if m.payload.get("type") == "text"]
    assert len(image_messages) == 1  # combo-image fallback, cap exceeded
    assert len(text_messages) == 0
