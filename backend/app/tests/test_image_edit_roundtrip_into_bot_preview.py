"""FINAL PRE-LIVE VERIFICATION section 4/8/9: proves the actual Super-Admin-editable
loop -- upload an image, edit its caption, reorder it -- lands in the very next Bot
Preview turn, through the real API + real dry-run engine (never a mock/fake preview).
"""

import io

import pytest_asyncio
from PIL import Image as PILImage
from sqlalchemy import select

from app.core.security import encrypt_secret, hash_password
from app.models.enums import EngagementType, UserRole
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.niche_seeds.jewellers import TEMPLATE as JEWEL_TEMPLATE
from app.services.image_type_profile_defaults import sync_default_profiles
from app.services.niche_provisioning import provision_from_template


@pytest_asyncio.fixture(autouse=True)
async def _seeded_profiles(db_session):
    await sync_default_profiles(db_session)


def _jpeg_bytes(color) -> bytes:
    img = PILImage.new("RGB", (800, 600), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def _make_owner_tenant(db_session, slug: str) -> tuple[Restaurant, dict]:
    restaurant = Restaurant(
        name=f"ImgRoundtrip {slug}", slug=f"imgroundtrip-{slug}",
        whatsapp_phone_number_id=f"IMGRT_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    existing = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == JEWEL_TEMPLATE["code"]))).scalar_one_or_none()
    if existing is not None:
        template = existing
    else:
        template = NicheTemplate(
            code=JEWEL_TEMPLATE["code"], name=JEWEL_TEMPLATE["name"], action_type=EngagementType(JEWEL_TEMPLATE["action_type"]),
            icon=JEWEL_TEMPLATE["icon"], welcome_message=JEWEL_TEMPLATE["welcome_message"],
            welcome_banner_image=JEWEL_TEMPLATE["welcome_banner_image"], welcome_buttons=JEWEL_TEMPLATE["welcome_buttons"],
            default_catalog=JEWEL_TEMPLATE["default_catalog"], default_flow_steps=JEWEL_TEMPLATE["default_flow_steps"],
            terminology=JEWEL_TEMPLATE["terminology"], default_modules=JEWEL_TEMPLATE["default_modules"],
        )
        db_session.add(template)
        await db_session.flush()
    await provision_from_template(db_session, restaurant, template)

    email = f"owner-imgrt-{slug}@kelviontech.dev"
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


def _image_captions(messages: list[dict]) -> list[str]:
    return [m["image"]["caption"] for m in messages if m.get("type") == "image"]


async def test_edit_item_image_caption_and_reorder_reflects_in_next_preview_turn(db_session, client):
    restaurant, creds = await _make_owner_tenant(db_session, "captiontest")
    headers = await _login(client, **creds)
    preview_base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"
    images_base = f"/api/v1/restaurants/{restaurant.id}/images"

    # Walk to piece_details to learn a real catalog item id (jewellery's item-detail
    # gallery step -- see test_niche_flow_preview_spotcheck.py for the full step shapes).
    resp = await client.post(preview_base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "welcome:appointment"})
    category_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("category:"))
    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": category_id})
    item_reply_id = next(o for o in _flatten_options(resp.json()["messages"]) if o.startswith("item:"))
    item_id = item_reply_id.removeprefix("item:")

    # No curated Image rows yet -- the item-detail step falls back to zero/whatever the
    # legacy `images` JSON list already had. Now upload a real one via the exact
    # endpoint Media Library / the Menu editor's ImageManager calls.
    upload = await client.post(
        images_base, headers=headers,
        data={"image_type": "product", "catalog_item_id": item_id, "caption": "Original Caption", "display_order": "0"},
        files={"file": ("ring.jpg", _jpeg_bytes((200, 50, 50)), "image/jpeg")},
    )
    assert upload.status_code == 201, upload.text
    image_id = upload.json()["id"]

    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": item_reply_id})
    assert "Original Caption" in _image_captions(resp.json()["messages"]), (
        f"newly uploaded image's caption not visible in Bot Preview: {resp.json()['messages']}"
    )

    # Super Admin edits the caption -- metadata-only PATCH, the same one the Menu/Flow
    # Builder ImageManager component calls on caption blur.
    patched = await client.patch(f"{images_base}/{image_id}", headers=headers, json={"caption": "Updated Caption via Super Admin"})
    assert patched.status_code == 200, patched.text

    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": item_reply_id})
    captions = _image_captions(resp.json()["messages"])
    assert "Updated Caption via Super Admin" in captions, f"edited caption not reflected in next preview turn: {captions}"
    assert "Original Caption" not in captions, "stale caption still showing after edit"

    # Reorder: add a second image ordered BEFORE the first, confirm the gallery order flips.
    second_upload = await client.post(
        images_base, headers=headers,
        data={"image_type": "product", "catalog_item_id": item_id, "caption": "Second Angle", "display_order": "1"},
        files={"file": ("ring2.jpg", _jpeg_bytes((50, 200, 50)), "image/jpeg")},
    )
    assert second_upload.status_code == 201, second_upload.text
    second_image_id = second_upload.json()["id"]

    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": item_reply_id})
    assert _image_captions(resp.json()["messages"]) == ["Updated Caption via Super Admin", "Second Angle"]

    # Swap display_order -- "Second Angle" should now render first.
    r1 = await client.patch(f"{images_base}/{image_id}", headers=headers, json={"display_order": 1})
    assert r1.status_code == 200, r1.text
    r2 = await client.patch(f"{images_base}/{second_image_id}", headers=headers, json={"display_order": 0})
    assert r2.status_code == 200, r2.text

    resp = await client.post(preview_base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": item_reply_id})
    assert _image_captions(resp.json()["messages"]) == ["Second Angle", "Updated Caption via Super Admin"], (
        "reordering (display_order swap) not reflected in Bot Preview's image sequence"
    )
