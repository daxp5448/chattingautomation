"""API-level proof for the Universal Image Processing Pipeline: tenant isolation (the
design-review-flagged risk -- a known image_id from another tenant must never be
reachable), the full upload -> ready -> crop -> replace -> restore happy path, and
Super-Admin-only enforcement on the image-type-profiles registry.
"""

import io

import pytest_asyncio
from PIL import Image as PILImage

from app.core.security import encrypt_secret, hash_password
from app.models.catalog import CatalogCategory, CatalogItem
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.image_type_profile_defaults import sync_default_profiles
from app.tests.test_restaurants import _register_super_admin


@pytest_asyncio.fixture(autouse=True)
async def _seeded_profiles(db_session):
    """The 10 default ImageTypeProfile rows aren't migration data (see
    image_type_profile_defaults.py) -- this file's tests need them present the same way
    a real deploy would after running app/scripts/seed_image_type_profiles.py once.
    """
    await sync_default_profiles(db_session)


def _jpeg_bytes(width: int = 800, height: int = 600, color=(120, 40, 200)) -> bytes:
    img = PILImage.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def _make_owner_tenant(db_session, slug: str) -> tuple[Restaurant, CatalogItem, dict]:
    """Creates a restaurant + one catalog item + an OWNER user for it directly (bypassing
    the full email-setup flow, which isn't the thing under test here), and logs that
    owner in. Returns (restaurant, catalog_item, auth_headers)."""
    restaurant = Restaurant(
        name=f"Image API Test {slug}",
        slug=f"image-api-test-{slug}",
        whatsapp_phone_number_id=f"IMGAPI_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    category = CatalogCategory(restaurant_id=restaurant.id, name="Category")
    db_session.add(category)
    await db_session.flush()

    item = CatalogItem(restaurant_id=restaurant.id, category_id=category.id, name="Item", images=[])
    db_session.add(item)

    email = f"owner-{slug}@kelviontech.dev"
    password = "OwnerPass123!"
    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.OWNER,
        restaurant_id=restaurant.id,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    return restaurant, item, {"email": email, "password": password}


async def _login(client, email: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- tenant isolation (the design-review-flagged risk) ----------------------------------


async def test_owner_cannot_reach_another_tenants_image_by_id(db_session, client):
    restaurant_a, item_a, creds_a = await _make_owner_tenant(db_session, "tenanta")
    restaurant_b, item_b, creds_b = await _make_owner_tenant(db_session, "tenantb")
    headers_a = await _login(client, **creds_a)
    headers_b = await _login(client, **creds_b)

    upload_b = await client.post(
        f"/api/v1/restaurants/{restaurant_b.id}/images",
        headers=headers_b,
        data={"image_type": "product", "catalog_item_id": str(item_b.id)},
        files={"file": ("b.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert upload_b.status_code == 201, upload_b.text
    image_b_id = upload_b.json()["id"]

    # Tenant A's own restaurant_id in the path (passes resolve_tenant_id fine), but a
    # real image id belonging to tenant B -- must 404, not leak tenant B's image.
    resp = await client.get(f"/api/v1/restaurants/{restaurant_a.id}/images/{image_b_id}", headers=headers_a)
    assert resp.status_code == 404

    # The URL-path restaurant_id mismatch case is also rejected (resolve_tenant_id's own
    # existing guarantee, re-confirmed here in the context of this new router).
    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/images/{image_b_id}", headers=headers_a)
    assert resp.status_code == 403

    # Tenant B, correctly, CAN reach their own image.
    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/images/{image_b_id}", headers=headers_b)
    assert resp.status_code == 200


async def test_owner_cannot_crop_another_tenants_image(db_session, client):
    restaurant_a, item_a, creds_a = await _make_owner_tenant(db_session, "cropa")
    restaurant_b, item_b, creds_b = await _make_owner_tenant(db_session, "cropb")
    headers_a = await _login(client, **creds_a)
    headers_b = await _login(client, **creds_b)

    upload_b = await client.post(
        f"/api/v1/restaurants/{restaurant_b.id}/images",
        headers=headers_b,
        data={"image_type": "product", "catalog_item_id": str(item_b.id)},
        files={"file": ("b.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    image_b_id = upload_b.json()["id"]

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant_a.id}/images/{image_b_id}/crop",
        headers=headers_a,
        json={"x": 0, "y": 0, "width": 100, "height": 100},
    )
    assert resp.status_code == 404


# --- full happy path: upload -> ready -> crop -> replace -> restore --------------------


async def test_full_upload_crop_replace_restore_lifecycle(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "lifecycle")
    headers = await _login(client, **creds)

    upload = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images",
        headers=headers,
        data={"image_type": "product", "catalog_item_id": str(item.id)},
        files={"file": ("original.jpg", _jpeg_bytes(1200, 900), "image/jpeg")},
    )
    assert upload.status_code == 201, upload.text
    body = upload.json()
    # The test-only sync-processing fixture (conftest.py) runs the Celery task's real
    # logic synchronously, so status is already "ready" by the time this response
    # returns -- no polling needed in this test environment.
    assert body["status"] == "ready"
    assert body["original_width"] == 1200
    assert body["original_height"] == 900
    assert set(body["variants"].keys()) == {"thumbnail", "whatsapp", "gallery", "website"}  # "product" profile
    assert "website" in body["urls"]
    first_image_id = body["id"]

    listed = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images", headers=headers, params={"catalog_item_id": str(item.id)}
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    # --- crop: always re-derives from the untouched original -----------------------------
    cropped = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images/{first_image_id}/crop",
        headers=headers,
        json={"x": 0, "y": 0, "width": 600, "height": 600},
    )
    assert cropped.status_code == 200, cropped.text
    assert cropped.json()["status"] == "ready"
    assert cropped.json()["crop_box"] == {"x": 0, "y": 0, "width": 600, "height": 600}

    # --- replace: creates a NEW row, never overwrites the old one ------------------------
    replaced = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images/{first_image_id}/replace",
        headers=headers,
        files={"file": ("newversion.jpg", _jpeg_bytes(1000, 1000, color=(10, 200, 10)), "image/jpeg")},
    )
    assert replaced.status_code == 201, replaced.text
    second_image_id = replaced.json()["id"]
    assert second_image_id != first_image_id
    assert replaced.json()["status"] == "ready"

    old_after_replace = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images/{first_image_id}", headers=headers
    )
    assert old_after_replace.json()["replaced_by_image_id"] == second_image_id
    # The old row's own variants are untouched, not deleted -- a real historical version.
    assert old_after_replace.json()["status"] == "ready"

    # --- restore: repoints back to the first (older) image explicitly --------------------
    restored = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images/{first_image_id}/restore", headers=headers
    )
    assert restored.status_code == 200
    assert restored.json()["replaced_by_image_id"] is None

    # --- delete: soft delete only, a subsequent GET 404s but the row still exists --------
    deleted = await client.delete(
        f"/api/v1/restaurants/{restaurant.id}/images/{second_image_id}", headers=headers
    )
    assert deleted.status_code == 204
    after_delete = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images/{second_image_id}", headers=headers
    )
    assert after_delete.status_code == 404


async def test_upload_rejects_unknown_image_type(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "badtype")
    headers = await _login(client, **creds)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images",
        headers=headers,
        data={"image_type": "not_a_real_type", "catalog_item_id": str(item.id)},
        files={"file": ("x.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    assert resp.status_code == 400


async def test_upload_rejects_corrupt_file(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "corrupt")
    headers = await _login(client, **creds)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images",
        headers=headers,
        data={"image_type": "product", "catalog_item_id": str(item.id)},
        files={"file": ("x.jpg", b"not a real image at all", "image/jpeg")},
    )
    assert resp.status_code == 400


# --- Super-Admin-only image-type-profiles registry --------------------------------------


async def test_image_type_profiles_readable_and_seeded(client):
    headers = await _register_super_admin(client)
    resp = await client.get("/api/v1/image-type-profiles", headers=headers)
    assert resp.status_code == 200
    codes = {p["code"] for p in resp.json()}
    assert {"logo", "cover", "banner", "category", "product", "gallery", "service", "staff", "property", "vehicle"} <= codes


async def test_owner_cannot_write_image_type_profiles(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "noadmin")
    headers = await _login(client, **creds)

    resp = await client.post(
        "/api/v1/image-type-profiles",
        headers=headers,
        json={"code": "vehicle_interior", "label": "Vehicle Interior", "variant_specs": []},
    )
    assert resp.status_code == 403


async def test_super_admin_can_add_a_new_image_type_without_a_deploy(client):
    """The concrete proof of "Never Hardcode Anything" for image types: adding an 11th
    type is a POST, not a migration or a code change."""
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/image-type-profiles",
        headers=headers,
        json={
            "code": "menu_board",
            "label": "Menu Board",
            "variant_specs": [
                {"variant_name": "whatsapp", "target_context": "whatsapp", "width": 800, "height": 600, "crop_mode": "cover", "format": "webp"}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    profile_id = resp.json()["id"]

    updated = await client.patch(
        f"/api/v1/image-type-profiles/{profile_id}", headers=headers, json={"label": "Menu Board (Updated)"}
    )
    assert updated.status_code == 200
    assert updated.json()["label"] == "Menu Board (Updated)"
