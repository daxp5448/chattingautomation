"""Public self-serve signup (see app/api/v1/routers/signup.py): a stranger creates their
own business + owner account, verifies a 6-digit OTP, lands auto-logged-in with a fully
usable dashboard -- while the WhatsApp bot stays silent until a Super Admin approves.
"""

from datetime import datetime, timedelta

from sqlalchemy import select

from app.models.enums import EngagementType, RestaurantStatus
from app.models.generic_conversation_state import GenericConversationState
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.restaurant import TEMPLATE
from app.repositories.audit_log_repository import AuditLogRepository
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    PHONE_NUMBER_ID,
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
)
from app.tests.test_restaurants import _register_super_admin


async def _seed_restaurant_template(db_session) -> NicheTemplate:
    """The test DB starts empty and `code` is globally unique -- mirrors
    test_message_catalog.py::_get_or_create_restaurant_template."""
    existing = (
        await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == TEMPLATE["code"]))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    template = NicheTemplate(
        code=TEMPLATE["code"],
        name=TEMPLATE["name"],
        action_type=EngagementType(TEMPLATE["action_type"]),
        icon=TEMPLATE["icon"],
        welcome_message=TEMPLATE["welcome_message"],
        welcome_banner_image=TEMPLATE["welcome_banner_image"],
        welcome_buttons=TEMPLATE["welcome_buttons"],
        default_catalog=TEMPLATE["default_catalog"],
        default_flow_steps=TEMPLATE["default_flow_steps"],
        terminology=TEMPLATE["terminology"],
        default_modules=TEMPLATE["default_modules"],
    )
    db_session.add(template)
    await db_session.commit()
    return template


async def _signup(client, db_session, email="newowner@bellanapoli.dev", business="Bella Napoli Pizzeria"):
    await _seed_restaurant_template(db_session)
    resp = await client.post(
        "/api/v1/signup",
        json={
            "business_name": business,
            "owner_email": email,
            "password": "OwnerPass123!",
            "niche_code": TEMPLATE["code"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- happy path ---------------------------------------------------------------------


async def test_signup_creates_pending_business_and_verifies_via_otp(client, db_session):
    result = await _signup(client, db_session)
    restaurant_id = result["restaurant_id"]
    # Outside production the raw code comes back in the response, same convention as
    # RestaurantCreateResult.setup_url -- no SMTP needed in tests.
    assert result["debug_otp_code"] and len(result["debug_otp_code"]) == 6

    restaurant = (
        await db_session.execute(select(Restaurant).where(Restaurant.id == restaurant_id))
    ).scalar_one()
    assert restaurant.status == RestaurantStatus.PENDING_REVIEW
    # Provisioned from the niche template, exactly like an admin-created business.
    assert restaurant.uses_generic_engine is True
    assert restaurant.niche_type == TEMPLATE["code"]

    owner = (await db_session.execute(select(User).where(User.email == "newowner@bellanapoli.dev"))).scalar_one()
    assert owner.is_active is False  # cannot log in until the OTP is verified

    # The real password is set at signup -- but login is still blocked pre-verification.
    early_login = await client.post(
        "/api/v1/auth/login", json={"email": "newowner@bellanapoli.dev", "password": "OwnerPass123!"}
    )
    assert early_login.status_code == 401

    verify = await client.post(
        "/api/v1/signup/verify-otp", json={"restaurant_id": restaurant_id, "code": result["debug_otp_code"]}
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["access_token"]

    await db_session.refresh(owner)
    assert owner.is_active is True
    assert owner.otp_hash is None


async def test_signup_is_audit_logged(client, db_session):
    result = await _signup(client, db_session)
    entries = await AuditLogRepository(db_session).list_for_restaurant(result["restaurant_id"])
    assert [e.action for e in entries] == ["signup_created"]


async def test_verified_owner_can_use_dashboard_before_approval(client, db_session):
    """The whole point of the pending-review model: the dashboard works immediately, only
    the WhatsApp bot is gated."""
    result = await _signup(client, db_session)
    verify = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/restaurants/{result['restaurant_id']}/catalog-categories",
        json={"name": "Pizzas"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


# --- OTP mechanics ------------------------------------------------------------------


async def test_wrong_otp_is_rejected_and_counts_an_attempt(client, db_session):
    result = await _signup(client, db_session)
    resp = await client.post(
        "/api/v1/signup/verify-otp", json={"restaurant_id": result["restaurant_id"], "code": "000000"}
    )
    assert resp.status_code == 400

    owner = (await db_session.execute(select(User).where(User.email == "newowner@bellanapoli.dev"))).scalar_one()
    await db_session.refresh(owner)
    assert owner.otp_attempts == 1

    # The real code still works while attempts remain.
    ok = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    assert ok.status_code == 200, ok.text


async def test_otp_locks_out_after_five_wrong_attempts(client, db_session):
    result = await _signup(client, db_session)
    for _ in range(5):
        resp = await client.post(
            "/api/v1/signup/verify-otp", json={"restaurant_id": result["restaurant_id"], "code": "000000"}
        )
        assert resp.status_code == 400

    # Even the CORRECT code is refused once the attempt cap is hit.
    locked = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    assert locked.status_code == 429


async def test_expired_otp_is_rejected(client, db_session):
    result = await _signup(client, db_session)
    owner = (await db_session.execute(select(User).where(User.email == "newowner@bellanapoli.dev"))).scalar_one()
    owner.otp_expires_at = datetime.utcnow() - timedelta(minutes=1)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


async def test_resend_issues_a_new_code_and_invalidates_the_old_one(client, db_session):
    result = await _signup(client, db_session)
    resend = await client.post("/api/v1/signup/resend-otp", json={"restaurant_id": result["restaurant_id"]})
    assert resend.status_code == 200, resend.text
    new_code = resend.json()["debug_otp_code"]
    assert new_code != result["debug_otp_code"]

    stale = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    assert stale.status_code == 400

    ok = await client.post(
        "/api/v1/signup/verify-otp", json={"restaurant_id": result["restaurant_id"], "code": new_code}
    )
    assert ok.status_code == 200, ok.text


async def test_resend_is_capped_per_signup(client, db_session):
    """The per-ACCOUNT lifetime cap, distinct from the 3/minute per-IP limit that would
    otherwise fire first: it's what stops an attacker who rotates IPs from using resend as
    an unbounded email-bombing vector against one victim's inbox. Seeded directly rather
    than by hammering the endpoint, since the IP limiter blocks that path from one host.
    """
    result = await _signup(client, db_session)
    owner = (await db_session.execute(select(User).where(User.email == "newowner@bellanapoli.dev"))).scalar_one()
    owner.otp_resend_count = 5
    await db_session.commit()

    capped = await client.post("/api/v1/signup/resend-otp", json={"restaurant_id": result["restaurant_id"]})
    assert capped.status_code == 429
    assert "support" in capped.json()["detail"].lower()


# --- validation / duplicate handling ------------------------------------------------


async def test_unknown_niche_code_is_rejected(client, db_session):
    await _seed_restaurant_template(db_session)
    resp = await client.post(
        "/api/v1/signup",
        json={
            "business_name": "Nowhere Cafe",
            "owner_email": "nowhere@example.dev",
            "password": "OwnerPass123!",
            "niche_code": "not_a_real_niche",
        },
    )
    assert resp.status_code == 400


async def test_repeat_signup_before_verifying_resends_on_the_same_business(client, db_session):
    """A mistyped OTP must not permanently strand that email address."""
    first = await _signup(client, db_session)
    second = await _signup(client, db_session)
    assert second["restaurant_id"] == first["restaurant_id"]
    assert second["debug_otp_code"] != first["debug_otp_code"]

    restaurants = (
        await db_session.execute(select(Restaurant).where(Restaurant.name == "Bella Napoli Pizzeria"))
    ).scalars().all()
    assert len(restaurants) == 1  # no duplicate business row


async def test_signup_with_an_already_verified_email_conflicts(client, db_session):
    result = await _signup(client, db_session)
    verify = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    assert verify.status_code == 200

    resp = await client.post(
        "/api/v1/signup",
        json={
            "business_name": "Another Business",
            "owner_email": "newowner@bellanapoli.dev",
            "password": "OwnerPass123!",
            "niche_code": TEMPLATE["code"],
        },
    )
    assert resp.status_code == 409


async def test_signup_cannot_set_privileged_fields(client, db_session):
    """SignupRequest has no is_demo/feature_package_id/whatsapp_*/razorpay_* fields at
    all, so extra keys are ignored rather than silently honoured."""
    await _seed_restaurant_template(db_session)
    resp = await client.post(
        "/api/v1/signup",
        json={
            "business_name": "Sneaky Co",
            "owner_email": "sneaky@example.dev",
            "password": "OwnerPass123!",
            "niche_code": TEMPLATE["code"],
            "is_demo": True,
            "whatsapp_phone_number_id": "999000111222",
            "status": "active",
        },
    )
    assert resp.status_code == 201, resp.text
    restaurant = (
        await db_session.execute(select(Restaurant).where(Restaurant.id == resp.json()["restaurant_id"]))
    ).scalar_one()
    assert restaurant.is_demo is False
    assert restaurant.whatsapp_phone_number_id is None
    assert restaurant.status == RestaurantStatus.PENDING_REVIEW


# --- public niche list --------------------------------------------------------------


async def test_public_niche_list_is_unauthenticated_and_narrow(client, db_session):
    await _seed_restaurant_template(db_session)
    resp = await client.get("/api/v1/signup/niches")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert any(r["code"] == TEMPLATE["code"] for r in rows)
    # Only the picker-relevant fields -- no internal flow-engine configuration.
    assert set(rows[0]) == {"code", "name", "icon"}


# --- approval gating ----------------------------------------------------------------


async def test_pending_review_business_bot_stays_silent_until_approved(
    client, db_session, _use_in_memory_sender
):
    """Mirrors test_restaurant_status.py's suspended/cancelled assertions, against the new
    self-serve status -- and then proves approval actually turns the bot on."""
    # Register the admin BEFORE signup: verify-otp sets auth cookies on this shared test
    # client, so afterwards /auth/register would see an authenticated OWNER (which is
    # correctly refused) rather than an unauthenticated bootstrap caller.
    admin_headers = await _register_super_admin(client, email="signup-admin@kelviontech.dev")

    result = await _signup(client, db_session)
    restaurant_id = result["restaurant_id"]
    await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": restaurant_id, "code": result["debug_otp_code"]},
    )

    # Connect the shared webhook fixture's phone_number_id to this new business, the way a
    # real owner would after setting up their WhatsApp number from the dashboard.
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}",
        json={"whatsapp_phone_number_id": PHONE_NUMBER_ID},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text

    # Pending review: the customer hears the "still being set up" notice, and NO
    # conversation state is created (the flow engine is skipped entirely).
    await _post_webhook(client, _message_value(_text("hi")))
    states = (
        await db_session.execute(
            select(GenericConversationState).where(GenericConversationState.restaurant_id == restaurant_id)
        )
    ).scalars().all()
    assert states == []
    assert len(_use_in_memory_sender.sent) == 1
    assert "still being set up" in _use_in_memory_sender.sent[0].payload["text"]["body"]

    # Super Admin approves -> the bot goes live.
    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}", json={"status": "active"}, headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "active"

    await _post_webhook(client, _message_value(_text("hi")))
    states_after = (
        await db_session.execute(
            select(GenericConversationState).where(GenericConversationState.restaurant_id == restaurant_id)
        )
    ).scalars().all()
    assert len(states_after) == 1

    entries = await AuditLogRepository(db_session).list_for_restaurant(restaurant_id)
    assert "signup_created" in [e.action for e in entries]
    change = next(e for e in entries if e.action == "status_change")
    assert change.diff == {"from": "pending_review", "to": "active"}
