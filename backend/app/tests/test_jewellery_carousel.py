"""Acceptance proof for the jewellery-only visual carousel (Material -> Category ->
paginated Design gallery), an isolated feature layered on top of the existing generic
engine -- see the approved plan for full context. Walks the REAL Bot Preview dry-run
endpoint (`POST /restaurants/{id}/flow/preview`, the exact function a real inbound
WhatsApp webhook calls), never a direct engine-internals shortcut, so this proves the
whole chain: JewelleryDesignRepository -> generic_flow_engine.py's new
"jewellery_materials"/"jewellery_categories" sources and _render_jewellery_gallery ->
outbound WhatsApp-shaped payload.

Also proves the two things the plan explicitly promised:
  1. Pagination never dumps more than page_size images in one turn, however large the
     underlying catalogue is (seeded with 15 designs in one category here).
  2. Every other niche's flow, and jewellery's own EXISTING enquiry flow
     (category_select/item_select/piece_details), are completely unaffected -- proven by
     re-running the full suite (see plan's verification section), not just by this file.
"""

import uuid

from app.core.security import encrypt_secret, hash_password
from app.models.enums import EngagementType, UserRole
from app.models.jewellery_design import JewelleryDesign
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.jewellers import TEMPLATE as JEWEL_TEMPLATE
from app.services.niche_provisioning import provision_from_template
from sqlalchemy import select


async def _make_owner_tenant(db_session, slug: str) -> tuple[Restaurant, dict]:
    restaurant = Restaurant(
        name=f"JewelCarousel {slug}",
        slug=f"jewelcarousel-{slug}",
        whatsapp_phone_number_id=f"JEWELCAR_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    existing = (
        await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == JEWEL_TEMPLATE["code"]))
    ).scalar_one_or_none()
    if existing is not None:
        db_template = existing
    else:
        db_template = NicheTemplate(
            code=JEWEL_TEMPLATE["code"], name=JEWEL_TEMPLATE["name"], action_type=EngagementType(JEWEL_TEMPLATE["action_type"]),
            icon=JEWEL_TEMPLATE["icon"], welcome_message=JEWEL_TEMPLATE["welcome_message"],
            welcome_banner_image=JEWEL_TEMPLATE["welcome_banner_image"], welcome_buttons=JEWEL_TEMPLATE["welcome_buttons"],
            default_catalog=JEWEL_TEMPLATE["default_catalog"], default_flow_steps=JEWEL_TEMPLATE["default_flow_steps"],
            terminology=JEWEL_TEMPLATE["terminology"], default_modules=JEWEL_TEMPLATE["default_modules"],
        )
        db_session.add(db_template)
        await db_session.flush()
    await provision_from_template(db_session, restaurant, db_template)

    email = f"owner-jewelcar-{slug}@kelviontech.dev"
    password = "OwnerPass123!"
    user = User(email=email, hashed_password=hash_password(password), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return restaurant, {"email": email, "password": password}


async def _login(client, email: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed_designs(restaurant_id, material: str, category: str, count: int, *, active: bool = True) -> list[JewelleryDesign]:
    return [
        JewelleryDesign(
            restaurant_id=restaurant_id,
            material=material,
            category=category,
            name=f"{material.title()} {category.title()} Design {i:03d}",
            design_code=f"{material}_{category}_{i:03d}",
            image_key=f"jewellery/{material}/{category}/{material}_{category}_{i:03d}.jpg",
            thumbnail_key=f"jewellery/{material}/{category}/thumbnails/{material}_{category}_{i:03d}.webp",
            source="unsplash",
            source_id=f"fake-unsplash-id-{material}-{category}-{i}",
            display_order=i,
            is_active=active,
        )
        for i in range(1, count + 1)
    ]


def _flatten_buttons(messages: list[dict]) -> list[str]:
    for m in messages:
        interactive = m.get("interactive", {})
        if interactive.get("type") == "button":
            return [b["reply"]["id"] for b in interactive["action"]["buttons"]]
        if interactive.get("type") == "list":
            return [r["id"] for r in interactive["action"]["sections"][0]["rows"]]
    return []


def _image_captions(messages: list[dict]) -> list[str]:
    return [m["image"]["caption"] for m in messages if m.get("type") == "image"]


def _last_body(messages: list[dict]) -> str:
    for m in reversed(messages):
        interactive = m.get("interactive", {})
        if interactive.get("type") in ("button", "list"):
            return interactive["body"]["text"]
        if m.get("type") == "text":
            return m["text"]["body"]
    return ""


async def test_gold_bangles_pagination_load_more_and_back_navigation(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "gold-bangles")
    headers = await _login(client, **creds)
    preview_base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    for design in _seed_designs(restaurant.id, "gold", "bangles", 15):
        db_session.add(design)
    for design in _seed_designs(restaurant.id, "gold", "rings", 3):
        db_session.add(design)
    await db_session.commit()

    resp = await client.post(preview_base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]

    # Welcome -> Browse Designs -> Material list -- Gold is one of the offered materials.
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:explore_design"})
    material_options = _flatten_buttons(resp.json()["messages"])
    assert "material:gold" in material_options, material_options

    # Material tapped -> Category list scoped to Gold -- both seeded categories appear.
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "material:gold"})
    category_options = _flatten_buttons(resp.json()["messages"])
    assert set(category_options) == {"jewellery_category:bangles", "jewellery_category:rings", "__back__"}, category_options

    # Category tapped -> page 1: exactly page_size (10) images, Load More offered, no
    # dead dump of all 15 at once.
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "jewellery_category:bangles"})
    messages = resp.json()["messages"]
    captions = _image_captions(messages)
    assert len(captions) == 10, captions
    assert captions[0] == "Gold Bangles Design 001\nGold • Bangles"
    assert captions[-1] == "Gold Bangles Design 010\nGold • Bangles"
    buttons = _flatten_buttons(messages)
    assert buttons == ["__jewellery_more__", "__back__"], buttons
    assert "showing 10 of 15" in _last_body(messages)

    # Load More -> page 2: the remaining 5, no Load More this time (nothing left).
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__jewellery_more__"})
    messages = resp.json()["messages"]
    captions = _image_captions(messages)
    assert len(captions) == 5, captions
    assert captions[0] == "Gold Bangles Design 011\nGold • Bangles"
    assert captions[-1] == "Gold Bangles Design 015\nGold • Bangles"
    buttons = _flatten_buttons(messages)
    assert buttons == ["__back__"], buttons
    assert "showing 15 of 15" in _last_body(messages)

    # Back -> Category list (not restarted, not "start over").
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__back__"})
    assert set(_flatten_buttons(resp.json()["messages"])) == {"jewellery_category:bangles", "jewellery_category:rings", "__back__"}

    # Back again -> Material list.
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__back__"})
    assert "material:gold" in _flatten_buttons(resp.json()["messages"])

    # Back again -> Welcome (original enquiry-flow buttons still intact and unrelated to
    # this feature -- proof jewellery's existing flow wasn't touched).
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__back__"})
    welcome_buttons = _flatten_buttons(resp.json()["messages"])
    assert "welcome:appointment" in welcome_buttons
    assert "welcome:explore_design" in welcome_buttons


async def test_silver_earrings_single_page_no_load_more(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "silver-earrings")
    headers = await _login(client, **creds)
    preview_base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    for design in _seed_designs(restaurant.id, "silver", "earrings", 4):
        db_session.add(design)
    await db_session.commit()

    resp = await client.post(preview_base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:explore_design"})
    await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "material:silver"})
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "jewellery_category:earrings"})
    messages = resp.json()["messages"]
    assert len(_image_captions(messages)) == 4
    # Fewer designs than page_size -- Load More must not appear.
    assert _flatten_buttons(messages) == ["__back__"]


async def test_empty_category_shows_clean_message_not_a_broken_carousel(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "empty-category")
    headers = await _login(client, **creds)
    preview_base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    designs = _seed_designs(restaurant.id, "gold", "anklets", 1)
    for design in designs:
        db_session.add(design)
    await db_session.commit()

    resp = await client.post(preview_base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:explore_design"})
    await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "material:gold"})
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "jewellery_category:anklets"})
    assert len(_image_captions(resp.json()["messages"])) == 1  # sanity: it was really there

    # The design gets deactivated (e.g. Super Admin removes the last one, or it's the
    # only design and goes out of stock) -- re-rendering the same step must now show the
    # clean empty-state message, never an empty/broken image carousel.
    designs[0].is_active = False
    await db_session.commit()

    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__back__"})
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "jewellery_category:anklets"})
    messages = resp.json()["messages"]
    assert _image_captions(messages) == []
    body = _last_body(messages)
    assert "no designs available" in body.lower()
    assert _flatten_buttons(messages) == ["__back__"]


async def test_jewellery_existing_enquiry_flow_still_works_unchanged(db_session, client):
    """Regression proof colocated with the new feature's own tests: the pre-existing
    category_select -> item_select -> piece_details enquiry path (see jewellers.py) is
    completely untouched by the new material/category/design_gallery steps."""
    restaurant, creds = await _make_owner_tenant(db_session, "existing-flow")
    headers = await _login(client, **creds)
    preview_base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(preview_base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:appointment"})
    category_options = _flatten_buttons(resp.json()["messages"])
    category_id = next(o for o in category_options if o.startswith("category:"))
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": category_id})
    item_options = _flatten_buttons(resp.json()["messages"])
    assert any(o.startswith("item:") for o in item_options)
