"""Proves the WhatsApp media_id caching added to generic_flow_engine.py::_Engine.
_media_message actually fires for the GENERIC (non-jewellery-design) image paths -- an
item-detail gallery image here, sent via _send_options's item_context_key branch -- the
same mechanism test_jewellery_media_id_cache.py already proved for JewelleryDesign rows,
now proven for the shared MetaMediaCache table every other image path uses. A fake httpx
transport stands in for both the image-bytes GET (image_presenter.py's ItemImage.url
points at a fake external host in tests) and Meta's real Media API POST, so no real
network call is made.

The upload is fire-and-forget (see meta_media_upload.py::schedule_background_upload) --
the customer's reply always goes out via `link` immediately, and the upload/cache-write
happens as a background asyncio task afterward, only pre-warming the cache for the NEXT
view. Tests explicitly await that background work (via the same _background_tasks
reference-holding set the real code uses) before asserting on its result.
"""

import asyncio

import httpx
from sqlalchemy import select

from app.core.security import encrypt_secret
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.enums import EngagementType
from app.models.flow_definition import FlowDefinition
from app.models.image import Image
from app.models.meta_media_cache import MetaMediaCache
from app.models.restaurant import Restaurant
from app.services import meta_media_upload
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.whatsapp_client import GraphAPIWhatsAppSender

PHONE = "919999955555"


async def _await_background_uploads() -> None:
    pending = list(meta_media_upload._background_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class _FakeMetaAndImageHostTransport(httpx.MockTransport):
    """Handles all 3 kinds of request GraphAPIWhatsAppSender's shared client makes once
    pointed at this fake transport: the image-bytes GET (image_presenter.py's
    ItemImage.url), Meta's real Media API upload POST, and the real /messages send POST
    -- the latter's request bodies are recorded in `sent_messages` (parsed JSON) since
    GraphAPIWhatsAppSender itself, unlike the test-only InMemoryWhatsAppSender, has no
    `.sent` list of its own to inspect.
    """

    def __init__(self):
        self.upload_calls: list[httpx.Request] = []
        self.image_fetch_calls: list[httpx.Request] = []
        self.sent_messages: list[dict] = []
        self._next_id = 1
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            self.image_fetch_calls.append(request)
            return httpx.Response(200, content=b"fake jpeg bytes", headers={"content-type": "image/jpeg"})
        if str(request.url).endswith("/media"):
            self.upload_calls.append(request)
            media_id = f"generic-media-{self._next_id}"
            self._next_id += 1
            return httpx.Response(200, json={"id": media_id})
        import json as _json
        self.sent_messages.append(_json.loads(request.content))
        return httpx.Response(200, json={"messages": [{"id": "wamid.fake"}]})


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
            "step_id": "item_detail", "type": "confirm_action", "prompt": "Here's the piece you picked.",
            "item_context_key": "item_id", "show_image": True,
            "buttons_from": "static", "static_options": [{"id": "detail:enquire", "title": "Enquire"}],
            "back_target": "item_select", "next": "done",
        },
        {"step_id": "done", "type": "message", "prompt": "Thanks!", "back_target": None, "terminal": True},
    ]


async def _setup(db_session):
    restaurant = Restaurant(
        name="Generic Media Cache Test", slug="generic-media-cache-test", uses_generic_engine=True,
        niche_type="jewellers", whatsapp_phone_number_id="GENERIC_MEDIA_TEST_PNID",
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

    image = Image(
        restaurant_id=restaurant.id, image_type="product", catalog_item_id=item.id,
        original_key="images/front/original.jpg", original_format="jpg",
        original_width=800, original_height=800, original_size_bytes=1000, status="ready",
        caption="Front view", display_order=1,
        variants={"website": {"key": "images/front/derived/website.webp", "format": "webp", "width": 800, "height": 800, "size_bytes": 500}},
    )
    db_session.add(image)

    db_session.add(FlowDefinition(restaurant_id=restaurant.id, niche_code="jewellers", action_type=EngagementType.INQUIRY, steps=_steps()))
    await db_session.commit()
    return restaurant, category, item


async def test_item_detail_image_sends_via_link_first_then_caches_media_id_in_background(db_session):
    restaurant, category, item = await _setup(db_session)

    transport = _FakeMetaAndImageHostTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)

    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}"))
    transport.sent_messages.clear()
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}"))

    # The reply the customer is actually waiting on -- link-based, sent without waiting
    # for the upload.
    image_messages = [m for m in transport.sent_messages if m.get("type") == "image"]
    assert len(image_messages) == 1
    assert "link" in image_messages[0]["image"]
    assert "id" not in image_messages[0]["image"]

    await _await_background_uploads()

    assert len(transport.upload_calls) == 1
    cached = (await db_session.execute(select(MetaMediaCache))).scalars().all()
    assert len(cached) == 1
    assert cached[0].phone_number_id == "GENERIC_MEDIA_TEST_PNID"
    assert cached[0].media_id == "generic-media-1"


async def test_item_detail_image_reuses_cached_media_id_on_second_view(db_session):
    restaurant, category, item = await _setup(db_session)

    transport = _FakeMetaAndImageHostTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)

    # First walk -- sends via link, background upload populates the cache.
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}"))
    await process_inbound_message(db_session, sender, restaurant, PHONE, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}"))
    await _await_background_uploads()
    assert len(transport.upload_calls) == 1

    # Second customer, same restaurant/item -- must hit the cache (sent via id, no
    # upload), not upload again.
    phone_2 = "919999955556"
    await process_inbound_message(db_session, sender, restaurant, phone_2, GenericInteraction(kind="text", text="hi"))
    await process_inbound_message(db_session, sender, restaurant, phone_2, GenericInteraction(kind="button_reply", reply_id=f"category:{category.id}"))
    transport.sent_messages.clear()
    await process_inbound_message(db_session, sender, restaurant, phone_2, GenericInteraction(kind="button_reply", reply_id=f"item:{item.id}"))

    assert len(transport.upload_calls) == 1  # still just the one, from the first customer
    image_messages = [m for m in transport.sent_messages if m.get("type") == "image"]
    assert len(image_messages) == 1
    assert "id" in image_messages[0]["image"]
    assert "link" not in image_messages[0]["image"]
