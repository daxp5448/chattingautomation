"""API-level proof for the previously-missing "Orders/Bookings/Appointments/Leads"
surface for generic-engine businesses: GET /restaurants/{id}/engagements existed only as
an unused repository method before this -- no router called it, so an admin had no way
to see a jewellery/salon/real-estate/etc. business's real activity at all (the legacy
Orders page only ever queries the `Order` table, which generic-engine businesses never
write to). Walks a REAL (non-preview) jewellery enquiry to completion via
process_inbound_message, then proves the new list/get/status-update endpoints work
against that real Engagement row -- not a mock, not dry_run.
"""

import itertools

from sqlalchemy import select

from app.core.security import encrypt_secret, hash_password
from app.models.enums import EngagementType, UserRole
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.jewellers import TEMPLATE
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.niche_provisioning import provision_from_template
from app.services.whatsapp_client import InMemoryWhatsAppSender

CUSTOMER_PHONE = "919876511001"
_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.engagements.test.{next(_wamid_counter)}"


async def _make_jewellers_tenant(db_session, slug: str) -> tuple[Restaurant, dict]:
    restaurant = Restaurant(
        name=f"Engagements Test {slug}", slug=f"engagements-test-{slug}",
        whatsapp_phone_number_id=f"ENGAPI_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    existing = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == TEMPLATE["code"]))).scalar_one_or_none()
    if existing is not None:
        template = existing
    else:
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

    email = f"owner-engapi-{slug}@kelviontech.dev"
    password = "OwnerPass123!"
    user = User(email=email, hashed_password=hash_password(password), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return restaurant, {"email": email, "password": password}


async def _login(client, email: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _walk_to_real_enquiry(db_session, restaurant):
    """Drives a REAL (non-preview) conversation through the real engine to produce a
    genuine, persisted Engagement row -- same call webhook.py makes for real inbound
    WhatsApp traffic."""
    sender = InMemoryWhatsAppSender()

    async def tap(reply_id):
        await process_inbound_message(
            db_session, sender, restaurant, CUSTOMER_PHONE,
            GenericInteraction(kind="button_reply", reply_id=reply_id, text=reply_id), wa_message_id=_next_wamid(),
        )

    async def say(text):
        await process_inbound_message(
            db_session, sender, restaurant, CUSTOMER_PHONE,
            GenericInteraction(kind="text", text=text, profile_name="Ananya Sharma"), wa_message_id=_next_wamid(),
        )

    def last_options():
        for m in reversed(sender.sent):
            interactive = m.payload.get("interactive", {})
            if interactive.get("type") == "button":
                return [b["reply"]["id"] for b in interactive["action"]["buttons"]]
            if interactive.get("type") == "list":
                return [r["id"] for r in interactive["action"]["sections"][0]["rows"]]
        return []

    await say("hi")
    await tap("welcome:appointment")
    category_id = next(o for o in last_options() if o.startswith("category:"))
    await tap(category_id)
    item_id = next(o for o in last_options() if o.startswith("item:"))
    await tap(item_id)
    await tap("piece:enquire")
    await say("Weekend preferred")
    await say("18k gold, size 7")
    await tap("name:confirm")
    await tap("inquiry:submit")
    return sender


async def test_list_get_and_transition_status_of_a_real_engagement(db_session, client):
    restaurant, creds = await _make_jewellers_tenant(db_session, "crud")
    await _walk_to_real_enquiry(db_session, restaurant)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/engagements"

    listed = await client.get(base, headers=headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1, f"expected exactly 1 real engagement, got {rows}"
    engagement = rows[0]
    assert engagement["type"] == "inquiry"
    assert engagement["status"] == "new"
    assert engagement["customer_phone"] == CUSTOMER_PHONE
    assert engagement["customer_name"] == "Ananya Sharma"
    assert engagement["reference_number"]

    fetched = await client.get(f"{base}/{engagement['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["id"] == engagement["id"]

    # Illegal transition: NEW -> COMPLETED must be rejected, not silently allowed.
    illegal = await client.patch(f"{base}/{engagement['id']}/status", json={"status": "completed"}, headers=headers)
    assert illegal.status_code == 400, illegal.text

    # Legal transition: NEW -> CONFIRMED, and the customer is actually notified.
    confirmed = await client.patch(f"{base}/{engagement['id']}/status", json={"status": "confirmed"}, headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"

    refetched = await client.get(f"{base}/{engagement['id']}", headers=headers)
    assert refetched.json()["status"] == "confirmed"  # persisted, not just returned once

    filtered_by_type = await client.get(f"{base}?type_filter=inquiry", headers=headers)
    assert len(filtered_by_type.json()) == 1
    filtered_by_wrong_type = await client.get(f"{base}?type_filter=order", headers=headers)
    assert filtered_by_wrong_type.json() == []
    filtered_by_status = await client.get(f"{base}?status_filter=confirmed", headers=headers)
    assert len(filtered_by_status.json()) == 1


async def test_engagement_status_update_sends_niche_appropriate_whatsapp_message(db_session, client, monkeypatch):
    restaurant, creds = await _make_jewellers_tenant(db_session, "notify")
    await _walk_to_real_enquiry(db_session, restaurant)
    headers = await _login(client, **creds)

    sent_messages = []

    async def _fake_send(phone_number_id, access_token, message):
        sent_messages.append(message)

    import app.api.v1.routers.engagements as engagements_router
    monkeypatch.setattr(engagements_router._sender, "send", _fake_send)

    listed = await client.get(f"/api/v1/restaurants/{restaurant.id}/engagements", headers=headers)
    engagement_id = listed.json()[0]["id"]

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}/engagements/{engagement_id}/status", json={"status": "confirmed"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert len(sent_messages) == 1
    body = sent_messages[0].payload["text"]["body"]
    assert "enquiry" in body.lower()  # jewellery's inquiry-type noun, not "order"
    # jewellery's terminology.status_labels["confirmed"] == "Contacted" (lead-CRM
    # wording), not a generic "Confirmed" -- proves the niche-specific label was
    # actually looked up, not just a Title-Cased fallback of the raw status code.
    assert "Contacted" in body


async def test_owner_cannot_reach_another_tenants_engagements(db_session, client):
    restaurant_a, creds_a = await _make_jewellers_tenant(db_session, "tenanta")
    restaurant_b, _creds_b = await _make_jewellers_tenant(db_session, "tenantb")
    await _walk_to_real_enquiry(db_session, restaurant_b)
    headers_a = await _login(client, **creds_a)

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/engagements", headers=headers_a)
    assert resp.status_code == 403


async def test_new_business_with_zero_activity_returns_empty_list_not_an_error(db_session, client):
    restaurant, creds = await _make_jewellers_tenant(db_session, "empty")
    headers = await _login(client, **creds)
    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/engagements", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
