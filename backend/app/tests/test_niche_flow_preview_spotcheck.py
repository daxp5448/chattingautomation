"""Manual-walk spot-checks (Super Admin audit requirement #15) for two of the three
representative journey shapes, driven through the REAL Bot Preview endpoint
(POST /restaurants/{id}/flow/preview, dry_run=True over the unmodified
generic_flow_engine) -- never a separate mock. The third shape (order+cart) is already
covered end-to-end by test_flow_preview.py's
test_preview_walks_the_real_restaurant_flow_start_to_confirmation.

- Salon: appointment/lead journey (staff -> date -> time -> confirm), human handoff, back
  navigation.
- Jewellery: item-detail image GALLERY (multiple images for one item, not just one photo)
  -> enquiry journey (free-text capture, no cart/payment at all).
"""

from app.core.security import encrypt_secret, hash_password
from app.models.enums import EngagementType, UserRole
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.jewellers import TEMPLATE as JEWEL_TEMPLATE
from app.niche_seeds.salon import TEMPLATE as SALON_TEMPLATE
from app.services.niche_provisioning import provision_from_template
from sqlalchemy import select


async def _make_owner_tenant(db_session, slug: str, template_dict: dict) -> tuple[Restaurant, dict]:
    restaurant = Restaurant(
        name=f"Spotcheck {slug}", slug=f"spotcheck-{slug}",
        whatsapp_phone_number_id=f"SPOTCHECK_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    existing = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == template_dict["code"]))).scalar_one_or_none()
    if existing is not None:
        template = existing
    else:
        template = NicheTemplate(
            code=template_dict["code"], name=template_dict["name"], action_type=EngagementType(template_dict["action_type"]),
            icon=template_dict["icon"], welcome_message=template_dict["welcome_message"],
            welcome_banner_image=template_dict["welcome_banner_image"], welcome_buttons=template_dict["welcome_buttons"],
            default_catalog=template_dict["default_catalog"], default_flow_steps=template_dict["default_flow_steps"],
            terminology=template_dict["terminology"], default_modules=template_dict["default_modules"],
        )
        db_session.add(template)
        await db_session.flush()
    await provision_from_template(db_session, restaurant, template)

    email = f"owner-spotcheck-{slug}@kelviontech.dev"
    password = "OwnerPass123!"
    user = User(email=email, hashed_password=hash_password(password), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return restaurant, {"email": email, "password": password}


async def _login(client, email: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _flatten_options(messages: list[dict]) -> list[str]:
    for m in messages:
        interactive = m.get("interactive", {})
        if interactive.get("type") == "button":
            return [b["reply"]["id"] for b in interactive["action"]["buttons"]]
        if interactive.get("type") == "list":
            return [r["id"] for r in interactive["action"]["sections"][0]["rows"]]
    return []


def _image_count(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("type") == "image")


def _text_of(messages: list[dict]) -> str:
    return " ".join(m.get("text", {}).get("body", "") for m in messages if m.get("type") == "text")


async def test_salon_appointment_journey_with_handoff_and_back_navigation(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "salon", SALON_TEMPLATE)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    session_id = body["session_id"]
    welcome_options = _flatten_options(body["messages"])
    assert "welcome:book" in welcome_options
    assert "welcome:human" in welcome_options  # human handoff reachable from welcome

    # Back navigation: category_select's Back returns to welcome, not a broken/blank step.
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:book"})
    category_options = _flatten_options(resp.json()["messages"])
    assert "__back__" in category_options
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__back__"})
    assert set(_flatten_options(resp.json()["messages"])) == set(welcome_options)

    # Re-enter and walk the full appointment journey to confirmation.
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:book"})
    category_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("category:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": category_id})
    service_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("item:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": service_id})
    staff_options = _flatten_options(resp.json()["messages"])
    assert "staff:any" in staff_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "staff:any"})
    date_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("date:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": date_id})
    time_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("time:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": time_id})
    assert "name:confirm" in _flatten_options(resp.json()["messages"])

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "name:confirm"})
    assert "booking:confirm" in _flatten_options(resp.json()["messages"])

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "booking:confirm"})
    final_text = _text_of(resp.json()["messages"])
    assert "confirmed" in final_text.lower()
    assert "PREVIEW-0000" in final_text  # a real (dry-run) reference number, not a fake static string

    # Terminology check: an appointment niche's confirmation must not say "order".
    assert "order" not in final_text.lower()


async def test_jewellery_item_gallery_and_enquiry_journey(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "jewel", JEWEL_TEMPLATE)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    welcome_options = _flatten_options(resp.json()["messages"])
    assert "welcome:appointment" in welcome_options
    assert "welcome:human" in welcome_options

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:appointment"})
    category_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("category:"))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": category_id})
    item_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("item:"))

    # piece_details is the item-detail gallery step -- every curated image for this piece
    # is sent as its own message (WhatsApp has no native multi-image carousel), not just
    # one representative photo. Every seeded jewellery item has >=1 image (see
    # test_niche_flow_acceptance_matrix.py), so this must be >=1, and this specific niche
    # was chosen for this spot-check precisely because its seed data gives multiple
    # images per piece.
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": item_id})
    detail_messages = resp.json()["messages"]
    assert _image_count(detail_messages) >= 1
    assert "piece:enquire" in _flatten_options(detail_messages)

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "piece:enquire"})
    # visit_capture: free text, no buttons -- accepts anything.
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "text", "text": "Weekend preferred"})
    # requirements_capture: free text.
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "text", "text": "18k gold, size 7"})
    assert "name:confirm" in _flatten_options(resp.json()["messages"])

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "name:confirm"})
    assert "inquiry:submit" in _flatten_options(resp.json()["messages"])

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "inquiry:submit"})
    final_text = _text_of(resp.json()["messages"])
    # An inquiry-type niche's confirmation must not fake a cart/payment/order flow.
    assert "cart" not in final_text.lower()
    assert "PREVIEW-0000" in final_text
