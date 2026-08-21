"""Proves the WhatsApp media_id caching added to generic_flow_engine.py::
_design_image_message actually works, in the ways the plain sequential-image-carousel
tests can't (they all run through Bot Preview's dry_run=True path, which deliberately
never touches this logic at all -- see _design_image_message's own docstring). A fake
httpx transport stands in for Meta's real Media API so no real network call is made.

The upload itself is fire-and-forget (see meta_media_upload.py::schedule_background_upload)
-- the CURRENT send always goes out via `link` immediately, and the upload/cache-write
happens as a background asyncio task that only pre-warms the cache for the NEXT send.
Tests explicitly await app.services.meta_media_upload._background_tasks (the same
reference-holding set schedule_background_upload uses to keep a fire-and-forget task
alive) to deterministically wait for that background work to finish before asserting on
its result, rather than a flaky sleep-based wait.

Covers: first use sends via `link` and schedules a background upload, a fresh cache hit
skips the upload/background task entirely and sends via `id` immediately, a stale (past
MEDIA_ID_FRESHNESS_DAYS) or phone_number_id-mismatched cached id triggers a re-upload, and
an upload failure leaves the design's cache fields untouched (still falls back to `link`
on every subsequent send too, exactly as before this feature existed).
"""

import asyncio
from datetime import datetime, timedelta

import httpx
import pytest_asyncio

from app.core.security import encrypt_secret, hash_password
from app.models.enums import EngagementType, UserRole
from app.models.jewellery_design import JewelleryDesign
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.jewellers import TEMPLATE as JEWEL_TEMPLATE
from app.services import image_storage_service, meta_media_upload
from app.services.generic_flow_engine import _Engine
from app.services.meta_media_upload import MEDIA_ID_FRESHNESS_DAYS
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import GraphAPIWhatsAppSender
from sqlalchemy import select


async def _await_background_uploads() -> None:
    """Deterministically waits for every fire-and-forget upload task scheduled during the
    test so far to finish, by awaiting the same _background_tasks set
    schedule_background_upload itself holds a reference in (a snapshot, since the set
    mutates itself via each task's own done-callback as they complete)."""
    pending = list(meta_media_upload._background_tasks)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


class _FakeMetaTransport(httpx.MockTransport):
    """Records every request it receives and returns a canned Meta Media API response --
    the media_id increments per call so tests can tell upload attempts apart."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self._next_id = 1
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        media_id = f"fake-media-{self._next_id}"
        self._next_id += 1
        return httpx.Response(200, json={"id": media_id})


class _FailingMetaTransport(httpx.MockTransport):
    def __init__(self):
        self.calls: list[httpx.Request] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(400, json={"error": {"message": "invalid"}})


async def _make_jewellery_tenant(db_session) -> Restaurant:
    restaurant = Restaurant(
        name="MediaIdCache Test",
        slug="mediaidcache-test",
        whatsapp_phone_number_id="MEDIAID_TEST_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    existing = (
        await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == JEWEL_TEMPLATE["code"]))
    ).scalar_one_or_none()
    if existing is None:
        existing = NicheTemplate(
            code=JEWEL_TEMPLATE["code"], name=JEWEL_TEMPLATE["name"], action_type=EngagementType(JEWEL_TEMPLATE["action_type"]),
            icon=JEWEL_TEMPLATE["icon"], welcome_message=JEWEL_TEMPLATE["welcome_message"],
            welcome_banner_image=JEWEL_TEMPLATE["welcome_banner_image"], welcome_buttons=JEWEL_TEMPLATE["welcome_buttons"],
            default_catalog=JEWEL_TEMPLATE["default_catalog"], default_flow_steps=JEWEL_TEMPLATE["default_flow_steps"],
            terminology=JEWEL_TEMPLATE["terminology"], default_modules=JEWEL_TEMPLATE["default_modules"],
        )
        db_session.add(existing)
        await db_session.flush()
    await provision_from_template(db_session, restaurant, existing)

    user = User(
        email="owner-mediaidcache@kelviontech.dev", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return restaurant


def _seed_design(restaurant_id) -> JewelleryDesign:
    image_key = "jewellery/gold/rings/gold_rings_001.jpg"
    # The autouse _fake_image_storage fixture (conftest.py) monkeypatches
    # image_storage_service module-wide with an in-memory dict -- this seeds this
    # design's key into it via the same public upload_bytes() function real code uses,
    # so upload_media()'s download_bytes() call finds real bytes to "upload" to Meta.
    image_storage_service.upload_bytes(image_key, b"fake jpeg bytes", "image/jpeg")
    return JewelleryDesign(
        restaurant_id=restaurant_id, material="gold", category="rings", name="Gold Ring Design 001",
        design_code="gold_rings_001", image_key=image_key,
        source="unsplash", source_id="fake-src-1", display_order=1, is_active=True,
    )


async def test_first_use_sends_via_link_and_schedules_a_background_upload(db_session):
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    db_session.add(design)
    await db_session.commit()

    transport = _FakeMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=False)

    # The reply the customer is actually waiting on -- must never be delayed by the upload.
    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")
    assert "link" in message.payload["image"]
    assert "id" not in message.payload["image"]
    assert design.meta_media_id is None  # not yet -- the background task hasn't run

    await _await_background_uploads()
    await db_session.refresh(design)

    assert len(transport.calls) == 1
    assert design.meta_media_id == "fake-media-1"
    assert design.meta_media_id_phone_number_id == "MEDIAID_TEST_PNID"
    assert design.meta_media_id_uploaded_at is not None


async def test_second_send_after_background_upload_uses_the_cached_id(db_session):
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    db_session.add(design)
    await db_session.commit()

    transport = _FakeMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=False)

    await engine._design_image_message(restaurant, design, "caption", "919876500000")
    await _await_background_uploads()
    await db_session.refresh(design)
    assert len(transport.calls) == 1

    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")
    assert message.payload["image"]["id"] == "fake-media-1"
    assert "link" not in message.payload["image"]
    assert len(transport.calls) == 1  # no second upload -- cache hit


async def test_fresh_cached_id_skips_reupload(db_session):
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    design.meta_media_id = "already-cached"
    design.meta_media_id_phone_number_id = "MEDIAID_TEST_PNID"
    design.meta_media_id_uploaded_at = datetime.utcnow()
    db_session.add(design)
    await db_session.commit()

    transport = _FakeMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=False)

    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")

    assert len(transport.calls) == 0  # no upload attempted -- cache hit
    assert message.payload["image"]["id"] == "already-cached"


async def test_stale_cached_id_triggers_reupload(db_session):
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    design.meta_media_id = "stale-id"
    design.meta_media_id_phone_number_id = "MEDIAID_TEST_PNID"
    design.meta_media_id_uploaded_at = datetime.utcnow() - timedelta(days=MEDIA_ID_FRESHNESS_DAYS + 1)
    db_session.add(design)
    await db_session.commit()

    transport = _FakeMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=False)

    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")
    assert "link" in message.payload["image"]  # stale id -> this send still falls back to link

    await _await_background_uploads()
    await db_session.refresh(design)
    assert len(transport.calls) == 1
    assert design.meta_media_id == "fake-media-1"


async def test_cached_id_for_a_different_phone_number_id_triggers_reupload(db_session):
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    design.meta_media_id = "id-from-another-number"
    design.meta_media_id_phone_number_id = "SOME_OTHER_PNID"
    design.meta_media_id_uploaded_at = datetime.utcnow()
    db_session.add(design)
    await db_session.commit()

    transport = _FakeMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=False)

    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")
    assert "link" in message.payload["image"]

    await _await_background_uploads()
    await db_session.refresh(design)
    assert len(transport.calls) == 1
    assert design.meta_media_id_phone_number_id == "MEDIAID_TEST_PNID"


async def test_upload_failure_leaves_cache_untouched_and_keeps_falling_back_to_link(db_session):
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    db_session.add(design)
    await db_session.commit()

    transport = _FailingMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=False)

    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")
    assert "link" in message.payload["image"]

    await _await_background_uploads()
    await db_session.refresh(design)
    assert len(transport.calls) == 1
    assert design.meta_media_id is None  # never cached a failed attempt

    # A subsequent send tries again (nothing cached) and still falls back cleanly.
    message2 = await engine._design_image_message(restaurant, design, "caption", "919876500000")
    assert "link" in message2.payload["image"]


async def test_dry_run_never_attempts_a_real_upload(db_session):
    """Bot Preview (dry_run=True) must never make a real Meta API call."""
    restaurant = await _make_jewellery_tenant(db_session)
    design = _seed_design(restaurant.id)
    db_session.add(design)
    await db_session.commit()

    transport = _FakeMetaTransport()
    sender = GraphAPIWhatsAppSender()
    sender._client = httpx.AsyncClient(transport=transport)
    engine = _Engine(db_session, sender, dry_run=True)

    message = await engine._design_image_message(restaurant, design, "caption", "919876500000")

    assert len(transport.calls) == 0
    assert "link" in message.payload["image"]
    assert design.meta_media_id is None
