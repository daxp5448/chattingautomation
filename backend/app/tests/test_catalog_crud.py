"""API-level proof for catalog.py -- the generic-engine counterpart of menu.py, CRUD for
CatalogCategory/CatalogItem (the tables niche-provisioned businesses, including every Demo
Bot restaurant, actually use -- menu.py's /categories and /products operate on a completely
different, legacy set of tables and return nothing for these businesses).
"""

from app.core.security import encrypt_secret, hash_password
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.tests.test_restaurants import _complete_setup, _register_super_admin


async def _owner_headers(client):
    admin_headers = await _register_super_admin(client)
    created = await client.post(
        "/api/v1/restaurants", json={"name": "Catalog Test Biz", "slug": "catalog-test-biz"}, headers=admin_headers
    )
    assert created.status_code == 201, created.text
    body = created.json()
    await _complete_setup(client, body["setup_url"], password="OwnerPass123!")
    login = await client.post("/api/v1/auth/login", json={"email": body["owner_email"], "password": "OwnerPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, body["id"]


async def test_owner_can_crud_categories_and_items(client):
    headers, restaurant_id = await _owner_headers(client)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/catalog-categories",
        headers=headers, json={"name": "Starters", "display_order": 0},
    )
    assert created.status_code == 201, created.text
    category_id = created.json()["id"]
    assert created.json()["visible"] is True

    listed = await client.get(f"/api/v1/restaurants/{restaurant_id}/catalog-categories", headers=headers)
    assert listed.status_code == 200
    assert [c["name"] for c in listed.json()] == ["Starters"]

    updated = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}/catalog-categories/{category_id}",
        headers=headers, json={"visible": False, "image_url": "https://cdn.example.com/starters.jpg"},
    )
    assert updated.status_code == 200
    assert updated.json()["visible"] is False
    assert updated.json()["image_url"] == "https://cdn.example.com/starters.jpg"

    item_created = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/catalog-items",
        headers=headers, json={"category_id": category_id, "name": "Paneer Tikka", "price": 250},
    )
    assert item_created.status_code == 201, item_created.text
    item_id = item_created.json()["id"]
    assert item_created.json()["price_type"] == "fixed"
    assert item_created.json()["available"] is True

    item_listed = await client.get(f"/api/v1/restaurants/{restaurant_id}/catalog-items", headers=headers)
    assert item_listed.status_code == 200
    assert [i["name"] for i in item_listed.json()] == ["Paneer Tikka"]

    item_updated = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}/catalog-items/{item_id}",
        headers=headers, json={"available": False, "images": ["https://cdn.example.com/paneer.jpg"]},
    )
    assert item_updated.status_code == 200
    assert item_updated.json()["available"] is False
    assert item_updated.json()["images"] == ["https://cdn.example.com/paneer.jpg"]

    item_deleted = await client.delete(f"/api/v1/restaurants/{restaurant_id}/catalog-items/{item_id}", headers=headers)
    assert item_deleted.status_code == 204

    category_deleted = await client.delete(f"/api/v1/restaurants/{restaurant_id}/catalog-categories/{category_id}", headers=headers)
    assert category_deleted.status_code == 204


async def test_cashier_cannot_write_catalog(db_session, client):
    headers, restaurant_id = await _owner_headers(client)

    user = User(
        email="cashier-catalog@kelviontech.dev", hashed_password=hash_password("CashierPass123!"),
        role=UserRole.CASHIER, restaurant_id=restaurant_id, is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={"email": "cashier-catalog@kelviontech.dev", "password": "CashierPass123!"})
    cashier_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/catalog-categories",
        headers=cashier_headers, json={"name": "Should Not Work"},
    )
    assert resp.status_code == 403

    # Reads stay open to any authenticated staff -- same bar as menu.py.
    listed = await client.get(f"/api/v1/restaurants/{restaurant_id}/catalog-categories", headers=cashier_headers)
    assert listed.status_code == 200


async def test_owner_can_upload_category_image_and_gets_a_permanent_url(client):
    from app.core.config import settings

    headers, restaurant_id = await _owner_headers(client)

    import io
    from PIL import Image as PILImage

    buf = io.BytesIO()
    PILImage.new("RGB", (40, 30), (10, 200, 90)).save(buf, format="JPEG")

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/catalog-categories/upload-image",
        headers=headers, files={"file": ("icon.jpg", buf.getvalue(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["url"]
    assert url.startswith(f"{settings.PUBLIC_MEDIA_BASE_URL}/catalog/{restaurant_id}/")


async def test_owner_cannot_edit_another_restaurants_catalog(db_session, client):
    """resolve_tenant_id must actually be scoping this -- an Owner of restaurant A hitting
    restaurant B's catalog endpoints (a different Owner's business) must not succeed."""
    headers, _ = await _owner_headers(client)

    other = Restaurant(
        name="Other Biz", slug="other-catalog-biz",
        whatsapp_phone_number_id="OTHER_CATALOG_PNID", whatsapp_access_token_encrypted=encrypt_secret("x"),
    )
    db_session.add(other)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/restaurants/{other.id}/catalog-categories", headers=headers, json={"name": "Sneaky"},
    )
    assert resp.status_code in (403, 404)
