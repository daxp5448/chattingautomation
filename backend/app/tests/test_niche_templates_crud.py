"""API-level proof for NicheTemplate CRUD (Super Admin only) -- create/read/update/delete,
role enforcement, and default_flow_steps validation via the shared flow-shape validator.
"""

from app.tests.test_restaurants import _register_super_admin


def _welcome_steps(entry_id: str = "welcome", step_type: str = "menu_select") -> list[dict]:
    return [
        {
            "step_id": entry_id,
            "type": step_type,
            "prompt": "Welcome!",
            "buttons_from": "static",
            "static_options": [{"id": "welcome:go", "title": "Go"}],
            "routes": {"welcome:go": "category_select"},
            "back_target": None,
        },
        {"step_id": "category_select", "type": "message", "prompt": "Categories", "back_target": "welcome"},
    ]


async def test_super_admin_can_create_and_read_niche_template(client):
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/niche-templates",
        headers=headers,
        json={
            "code": "pet_grooming",
            "name": "Pet Grooming",
            "action_type": "appointment",
            "icon": "\U0001f436",
            "welcome_message": "Welcome!",
            "default_flow_steps": _welcome_steps(),
            "terminology": {"item_label": "Service"},
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["code"] == "pet_grooming"
    assert body["is_customized"] is False
    template_id = body["id"]

    got = await client.get(f"/api/v1/niche-templates/{template_id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["name"] == "Pet Grooming"

    # Shows up in the (unauthenticated-content-wise) summary list too.
    listed = await client.get("/api/v1/niche-templates", headers=headers)
    assert any(t["code"] == "pet_grooming" for t in listed.json())


async def test_create_rejects_duplicate_code(client):
    headers = await _register_super_admin(client)
    payload = {
        "code": "dup_code",
        "name": "First",
        "action_type": "order",
        "welcome_message": "Hi",
        "default_flow_steps": _welcome_steps(),
    }
    first = await client.post("/api/v1/niche-templates", headers=headers, json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/niche-templates", headers=headers, json={**payload, "name": "Second"})
    assert second.status_code == 409


async def test_create_rejects_non_menu_select_entry_step(client):
    """entry_step_id is always derived as default_flow_steps[0]'s own step_id (matching
    niche_provisioning.py's own rule exactly), so the only reachable validation failure
    through this schema is the entry step being the wrong TYPE to carry buttons at all."""
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/niche-templates",
        headers=headers,
        json={
            "code": "bad_entry_type",
            "name": "Bad Entry Type",
            "action_type": "order",
            "welcome_message": "Hi",
            "default_flow_steps": _welcome_steps(step_type="message"),
        },
    )
    assert resp.status_code == 400
    assert "menu_select" in resp.json()["detail"]


async def test_create_rejects_default_catalog_item_missing_a_name(client):
    """default_catalog is validated against NicheCatalogCategory/NicheCatalogItem (see
    schemas/niche_template.py) -- shape mirrors exactly what niche_provisioning.py reads
    when a real business is provisioned from this template, so a missing item name is
    rejected here with a normal 422 instead of KeyError-ing much later at provisioning
    time."""
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/niche-templates",
        headers=headers,
        json={
            "code": "bad_catalog",
            "name": "Bad Catalog",
            "action_type": "order",
            "welcome_message": "Hi",
            "default_flow_steps": _welcome_steps(),
            "default_catalog": [{"name": "Category A", "items": [{"description": "no name field"}]}],
        },
    )
    assert resp.status_code == 422


async def test_update_rejects_default_catalog_category_missing_a_name(client):
    headers = await _register_super_admin(client)
    created = await client.post(
        "/api/v1/niche-templates",
        headers=headers,
        json={
            "code": "good_catalog", "name": "Good Catalog", "action_type": "order",
            "welcome_message": "Hi", "default_flow_steps": _welcome_steps(),
        },
    )
    template_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/niche-templates/{template_id}",
        headers=headers,
        json={"default_catalog": [{"icon_image": "https://example.com/a.jpg", "items": []}]},
    )
    assert resp.status_code == 422


async def test_owner_cannot_create_niche_template(db_session, client):
    from app.core.security import encrypt_secret, hash_password
    from app.models.enums import UserRole
    from app.models.restaurant import Restaurant
    from app.models.user import User

    restaurant = Restaurant(
        name="Niche Template Test Biz", slug="niche-template-test-biz",
        whatsapp_phone_number_id="NTPL_PNID", whatsapp_access_token_encrypted=encrypt_secret("x"),
    )
    db_session.add(restaurant)
    await db_session.flush()
    user = User(email="owner-ntpl@kelviontech.dev", hashed_password=hash_password("OwnerPass123!"), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={"email": "owner-ntpl@kelviontech.dev", "password": "OwnerPass123!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/niche-templates",
        headers=headers,
        json={"code": "x", "name": "X", "action_type": "order", "welcome_message": "hi", "default_flow_steps": _welcome_steps()},
    )
    assert resp.status_code == 403


async def test_update_marks_customized_and_delete_is_unrestricted(client):
    headers = await _register_super_admin(client)
    created = await client.post(
        "/api/v1/niche-templates",
        headers=headers,
        json={
            "code": "editable_niche", "name": "Original Name", "action_type": "inquiry",
            "welcome_message": "Hi", "default_flow_steps": _welcome_steps(),
        },
    )
    template_id = created.json()["id"]
    assert created.json()["is_customized"] is False

    updated = await client.patch(
        f"/api/v1/niche-templates/{template_id}", headers=headers, json={"name": "Edited Name"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Edited Name"
    assert updated.json()["is_customized"] is True

    deleted = await client.delete(f"/api/v1/niche-templates/{template_id}", headers=headers)
    assert deleted.status_code == 204
    missing = await client.get(f"/api/v1/niche-templates/{template_id}", headers=headers)
    assert missing.status_code == 404


def _jpeg_bytes(width: int = 40, height: int = 30, color=(90, 60, 200)) -> bytes:
    import io

    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()


async def test_owner_cannot_upload_niche_template_image(db_session, client):
    from app.core.security import encrypt_secret, hash_password
    from app.models.enums import UserRole
    from app.models.restaurant import Restaurant
    from app.models.user import User

    restaurant = Restaurant(
        name="Niche Upload Test Biz", slug="niche-upload-test-biz",
        whatsapp_phone_number_id="NTPL_UPLOAD_PNID", whatsapp_access_token_encrypted=encrypt_secret("x"),
    )
    db_session.add(restaurant)
    await db_session.flush()
    user = User(email="owner-ntpl-upload@kelviontech.dev", hashed_password=hash_password("OwnerPass123!"), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()

    login = await client.post("/api/v1/auth/login", json={"email": "owner-ntpl-upload@kelviontech.dev", "password": "OwnerPass123!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/niche-templates/upload-image",
        headers=headers,
        files={"file": ("b.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 403


async def test_super_admin_can_upload_niche_template_image_and_gets_a_permanent_url(client):
    from app.core.config import settings

    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/niche-templates/upload-image",
        headers=headers,
        files={"file": ("banner.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    assert url.startswith(f"{settings.PUBLIC_MEDIA_BASE_URL}/niche-templates/uploads/")
    assert url.endswith(".jpg")


async def test_upload_niche_template_image_rejects_non_image_content_type(client):
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/niche-templates/upload-image",
        headers=headers,
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400
