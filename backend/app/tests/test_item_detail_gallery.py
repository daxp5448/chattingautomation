"""Proof that an "item detail" step (item_context_key set -- e.g. a niche's "Ring
Details"/"Room Details"/"Property Details" step) sends EVERY active image curated for the
previously-selected item as its own message, in display_order, with its own caption --
not just the first one. See generic_flow_engine.py::_Engine._send_options's
item_context_key branch and _item_gallery, and app/services/image_presenter.py for the
ordering/caption/is_active contract this drives off of.
"""

import uuid

from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.enums import EngagementType
from app.models.flow_definition import FlowDefinition
from app.models.image import Image
from app.models.restaurant import Restaurant
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.whatsapp_client import InMemoryWhatsAppSender

PHONE = "919999966666"


def _steps():
    return [
        {
            "step_id": "welcome", "type": "menu_select", "prompt": "Hi!",
            "buttons_from": "categories", "capture_key": "category_id",
            "back_target": None, "next": "item_select", "show_image": False,
        },
        {
            "step_id": "item_select", "type": "menu_select", "prompt": "Pick a piece:",
            "buttons_from": "items", "category_context_key": "category_id", "capture_key": "item_id",
            "back_target": "welcome", "next": "item_detail", "show_image": False,
        },
        {
            # The step under test -- item_context_key is what triggers gallery-sending.
            "step_id": "item_detail", "type": "confirm_action", "prompt": "Here's the piece you picked.",
            "item_context_key": "item_id", "show_image": True,
            "buttons_from": "static", "static_options": [{"id": "detail:enquire", "title": "Enquire"}],
            "back_target": "item_select", "next": "done",
        },
        {"step_id": "done", "type": "message", "prompt": "Thanks!", "back_target": None, "terminal": True},
    ]


async def _setup(db_session):
    restaurant = Restaurant(
        name="Gallery Test Jewellers", slug="gallery-test-jewellers", uses_generic_engine=True,
        niche_type="jewellers", whatsapp_phone_number_id="GALLERY_TEST_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    category = CatalogCategory(restaurant_id=restaurant.id, name="Rings")
    db_session.add(category)
    await db_session.flush()

    item = CatalogItem(restaurant_id=restaurant.id, category_id=category.id, name="Diamond Ring", price=65000, images=[])
    db_session.add(item)
    await db_session.flush()

    db_session.add(FlowDefinition(restaurant_id=restaurant.id, niche_code="jewellers", action_type=EngagementType.INQUIRY, steps=_steps()))
    await db_session.commit()
    return restaurant, category, item


def _image(restaurant, item, suffix, caption, order):
    return Image(
        restaurant_id=restaurant.id, image_type="product", catalog_item_id=item.id,
        original_key=f"images/{suffix}/original.jpg", original_format="jpg",
        original_width=800, original_height=800, original_size_bytes=1000, status="ready",
        caption=caption, display_order=order,
        variants={"website": {"key": f"images/{suffix}/derived/website.webp", "format": "webp", "width": 800, "height": 800, "size_bytes": 500}},
    )


async def test_item_detail_step_sends_every_active_image_in_order_with_captions(db_session):
    restaurant, category, item = await _setup(db_session)
    db_session.add(_image(restaurant, item, "back", "Side profile", 2))
    db_session.add(_image(restaurant, item, "front", "Front view, 18K gold", 1))
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}"))
    sender.sent.clear()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}"))

    image_messages = [m for m in sender.sent if m.payload.get("type") == "image"]
    assert len(image_messages) == 2
    assert [m.payload["image"]["caption"] for m in image_messages] == ["Front view, 18K gold", "Side profile"]
    assert image_messages[0].payload["image"]["link"] == "https://fake-image-storage.test/images/front/derived/website.webp"
    assert image_messages[1].payload["image"]["link"] == "https://fake-image-storage.test/images/back/derived/website.webp"


async def test_item_detail_step_skips_inactive_images(db_session):
    restaurant, category, item = await _setup(db_session)
    db_session.add(_image(restaurant, item, "hidden", "Bad angle", 1))
    active = _image(restaurant, item, "shown", "Good angle", 2)
    db_session.add(active)
    await db_session.flush()
    hidden = (await db_session.execute(select(Image).where(Image.original_key == "images/hidden/original.jpg"))).scalar_one()
    hidden.is_active = False
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}"))
    sender.sent.clear()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}"))

    image_messages = [m for m in sender.sent if m.payload.get("type") == "image"]
    assert len(image_messages) == 1
    assert image_messages[0].payload["image"]["caption"] == "Good angle"


async def test_item_detail_step_falls_back_to_single_placeholder_when_item_has_no_images(db_session):
    restaurant, category, item = await _setup(db_session)
    # No Image rows and item.images is [] -- must not crash, must not send zero-caption
    # garbage, falls back to the restaurant-level cover/placeholder single image.
    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}"))
    sender.sent.clear()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}"))

    image_messages = [m for m in sender.sent if m.payload.get("type") == "image"]
    assert len(image_messages) == 1  # the restaurant-level fallback, not zero and not a crash
