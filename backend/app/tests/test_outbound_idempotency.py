"""Coverage for the outbound-duplicate-message fix (see
app/services/whatsapp_client.py::GraphAPIWhatsAppSender.send and
app/services/generic_flow_engine.py::process_inbound_message):

1. Retry policy no longer retries an ambiguous-outcome timeout (the request may already
   have reached Meta) -- only connect-phase failures (never reached Meta) and 5xx
   (Meta explicitly rejected it) are retried. This closes the exact mechanism the
   platform audit flagged: "a timeout doesn't guarantee Meta never received the first
   attempt, so a retry after a timeout can produce a genuine duplicate outbound message."

2. A genuinely concurrent redelivery of the same wa_message_id (two workers both pass
   the existence pre-check before either commits) now fails gracefully at the DB's own
   unique-constraint flush, instead of an unhandled crash -- and, critically, before any
   outbound message has been sent, so the loser can never double-send.
"""

import itertools
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.core.security import encrypt_secret
from app.models.enums import EngagementType
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.niche_seeds.restaurant import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import GraphAPIWhatsAppSender, InMemoryWhatsAppSender, OutboundMessage

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.idem.test.{next(_wamid_counter)}"


# --- 1. retry policy ------------------------------------------------------------------------


def _mock_response(status_code: int) -> httpx.Response:
    request = httpx.Request("POST", "https://graph.facebook.com/v20.0/PNID/messages")
    return httpx.Response(status_code, request=request, json={"error": "boom"})


async def test_read_timeout_is_not_retried():
    """The ambiguous-outcome case: a ReadTimeout means the request may already have
    reached Meta -- retrying risks a duplicate customer-visible message, so this must
    fail after exactly ONE attempt, not three."""
    sender = GraphAPIWhatsAppSender()
    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out waiting for response", request=httpx.Request("POST", "https://x"))

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(httpx.ReadTimeout):
            await sender.send("PNID", "token", OutboundMessage.text("91900000", "hi"))

    assert call_count == 1


async def test_connect_error_is_still_retried():
    """A ConnectError means the TCP connection never opened -- Meta never saw this
    request, so retrying is safe and must still happen (unchanged behavior)."""
    sender = GraphAPIWhatsAppSender()
    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("refused", request=httpx.Request("POST", "https://x"))

    with patch("httpx.AsyncClient.post", new=fake_post), patch("asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.ConnectError):
            await sender.send("PNID", "token", OutboundMessage.text("91900000", "hi"))

    assert call_count == 3  # _MAX_SEND_ATTEMPTS, unchanged


async def test_5xx_is_still_retried_and_succeeds_on_second_attempt():
    """Meta explicitly rejecting with 5xx means the message was NOT accepted -- safe to
    retry, and this proves a transient 5xx followed by success doesn't send twice from
    our side (only one payload reaches "success")."""
    sender = GraphAPIWhatsAppSender()
    responses = [_mock_response(503), _mock_response(200)]
    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        response = responses[call_count]
        call_count += 1
        return response

    with patch("httpx.AsyncClient.post", new=fake_post), patch("asyncio.sleep", new=AsyncMock()):
        await sender.send("PNID", "token", OutboundMessage.text("91900000", "hi"))

    assert call_count == 2


async def test_4xx_is_never_retried():
    sender = GraphAPIWhatsAppSender()
    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _mock_response(400)

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(httpx.HTTPStatusError):
            await sender.send("PNID", "token", OutboundMessage.text("91900000", "hi"))

    assert call_count == 1


# --- 2. concurrent duplicate wa_message_id -------------------------------------------------


@pytest.fixture
async def idem_restaurant(db_session):
    restaurant = Restaurant(
        name="Idempotency Test Kitchen", slug="idempotency-test-kitchen",
        whatsapp_phone_number_id="IDEM_GENERIC_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    template = NicheTemplate(
        code=TEMPLATE["code"], name=TEMPLATE["name"], action_type=EngagementType(TEMPLATE["action_type"]),
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


async def test_concurrent_redelivery_of_same_wa_message_id_does_not_double_send(db_session, idem_restaurant, monkeypatch):
    """Simulates the exact race the flush-time IntegrityError catch exists for: a second
    worker's transaction commits the SAME wa_message_id at the precise moment our own
    pre-check (which hasn't seen it yet) reports "not found". Our own call must then fail
    its own flush against the real unique constraint, catch it, and bail out gracefully
    -- zero outbound messages sent, zero unhandled exceptions, exactly one Message row
    with this wa_message_id in the end (the "other worker"'s)."""
    import app.services.generic_flow_engine as gfe
    from app.db.session import AsyncSessionLocal
    from app.models.customer import Customer
    from app.models.enums import MessageDirection, MessageSender
    from app.models.message import Message
    from sqlalchemy import select

    restaurant = idem_restaurant
    sender = InMemoryWhatsAppSender()
    phone = "919876500091"

    # Establish the customer/state first with an ordinary, uncontested message.
    await process_inbound_message(
        db_session, sender, restaurant, phone,
        GenericInteraction(kind="text", text="hi", profile_name="Race Tester"),
        wa_message_id=_next_wamid(),
    )
    sender.sent.clear()

    customer = (await db_session.execute(select(Customer).where(Customer.restaurant_id == restaurant.id))).scalars().first()
    race_wamid = "wamid.race.contested"

    original_get_by_wa_message_id = gfe._GenericMessageRepo.get_by_wa_message_id

    async def racing_get_by_wa_message_id(self, wa_message_id):
        if wa_message_id == race_wamid:
            # A different worker's independent transaction "wins" the race right here --
            # commits the same wa_message_id before our own pre-check returns.
            async with AsyncSessionLocal() as other_session:
                other_session.add(Message(
                    restaurant_id=restaurant.id, customer_id=customer.id, direction=MessageDirection.INBOUND,
                    sent_by=MessageSender.CUSTOMER, body="the other worker's copy", wa_message_id=wa_message_id,
                ))
                await other_session.commit()
            return None  # our own pre-check still (correctly, for this simulated instant) reports "not found"
        return await original_get_by_wa_message_id(self, wa_message_id)

    monkeypatch.setattr(gfe._GenericMessageRepo, "get_by_wa_message_id", racing_get_by_wa_message_id)

    # Must not raise -- the IntegrityError is caught internally.
    await process_inbound_message(
        db_session, sender, restaurant, phone,
        GenericInteraction(kind="button_reply", reply_id="welcome:order"),
        wa_message_id=race_wamid,
    )

    # Our call sent nothing -- it lost the race and bailed out before any send.
    assert sender.sent == []

    async with AsyncSessionLocal() as verify_session:
        rows = (await verify_session.execute(select(Message).where(Message.wa_message_id == race_wamid))).scalars().all()
        assert len(rows) == 1
        assert rows[0].body == "the other worker's copy"
