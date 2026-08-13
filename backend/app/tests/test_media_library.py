"""API-level proof for the Media Library endpoint (GET /restaurants/{id}/images/library):
tenant isolation, `search`-by-catalog-item-name, `image_type` filtering, soft-deleted
images excluded, and that it stays open to any authenticated caller (no OWNER/MANAGER
gate) exactly like the router's other GETs.
"""

import pytest_asyncio

from app.models.catalog import CatalogCategory, CatalogItem
from app.services.image_type_profile_defaults import sync_default_profiles
from app.tests.test_images_api import _jpeg_bytes, _login, _make_owner_tenant


@pytest_asyncio.fixture(autouse=True)
async def _seeded_profiles(db_session):
    """Same reasoning as test_images_api.py's identical fixture -- upload requires a real
    ImageTypeProfile row to resolve `image_type`."""
    await sync_default_profiles(db_session)


async def _upload(client, restaurant, item, headers, image_type: str = "product", **jpeg_kwargs):
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/images",
        headers=headers,
        data={"image_type": image_type, "catalog_item_id": str(item.id)},
        files={"file": ("x.jpg", _jpeg_bytes(**jpeg_kwargs), "image/jpeg")},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_library_returns_only_calling_tenants_images(db_session, client):
    restaurant_a, item_a, creds_a = await _make_owner_tenant(db_session, "liba")
    restaurant_b, item_b, creds_b = await _make_owner_tenant(db_session, "libb")
    headers_a = await _login(client, **creds_a)
    headers_b = await _login(client, **creds_b)

    await _upload(client, restaurant_a, item_a, headers_a)
    await _upload(client, restaurant_b, item_b, headers_b)
    await _upload(client, restaurant_b, item_b, headers_b)

    resp_a = await client.get(f"/api/v1/restaurants/{restaurant_a.id}/images/library", headers=headers_a)
    assert resp_a.status_code == 200
    assert len(resp_a.json()) == 1
    assert resp_a.json()[0]["restaurant_id"] == str(restaurant_a.id)

    resp_b = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/images/library", headers=headers_b)
    assert resp_b.status_code == 200
    assert len(resp_b.json()) == 2

    # Cross-tenant: A's own restaurant_id in the path (passes resolve_tenant_id), never
    # returns anything belonging to B -- and a mismatched restaurant_id in the path is
    # rejected outright by resolve_tenant_id, same guarantee as every other endpoint here.
    resp_cross = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/images/library", headers=headers_a)
    assert resp_cross.status_code == 403


async def test_library_includes_owning_catalog_item(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "libitem")
    headers = await _login(client, **creds)
    await _upload(client, restaurant, item, headers)

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/images/library", headers=headers)
    assert resp.status_code == 200
    entry = resp.json()[0]
    assert entry["catalog_item"]["id"] == str(item.id)
    assert entry["catalog_item"]["name"] == item.name
    assert entry["catalog_item"]["category_id"] == str(item.category_id)


async def test_library_search_filters_by_catalog_item_name(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "libsearch")
    headers = await _login(client, **creds)

    # A second catalog item in the same restaurant, with a distinctly-named image.
    category = CatalogCategory(restaurant_id=restaurant.id, name="Category 2")
    db_session.add(category)
    await db_session.flush()
    other_item = CatalogItem(restaurant_id=restaurant.id, category_id=category.id, name="Margherita Pizza", images=[])
    db_session.add(other_item)
    await db_session.commit()

    await _upload(client, restaurant, item, headers)  # item.name == "Item"
    await _upload(client, restaurant, other_item, headers)

    resp = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images/library", headers=headers, params={"search": "pizza"}
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["catalog_item"]["name"] == "Margherita Pizza"

    # Case-insensitive, substring match.
    resp_ci = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images/library", headers=headers, params={"search": "MARGH"}
    )
    assert len(resp_ci.json()) == 1

    resp_none = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images/library", headers=headers, params={"search": "no-such-item"}
    )
    assert resp_none.json() == []


async def test_library_image_type_filter(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "libtype")
    headers = await _login(client, **creds)

    await _upload(client, restaurant, item, headers, image_type="product")
    await _upload(client, restaurant, item, headers, image_type="gallery")

    resp = await client.get(
        f"/api/v1/restaurants/{restaurant.id}/images/library", headers=headers, params={"image_type": "gallery"}
    )
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["image_type"] == "gallery"


async def test_library_excludes_soft_deleted_images(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "libdel")
    headers = await _login(client, **creds)

    created = await _upload(client, restaurant, item, headers)
    keep = await _upload(client, restaurant, item, headers)

    delete_resp = await client.delete(
        f"/api/v1/restaurants/{restaurant.id}/images/{created['id']}", headers=headers
    )
    assert delete_resp.status_code == 204

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/images/library", headers=headers)
    assert resp.status_code == 200
    ids = {row["id"] for row in resp.json()}
    assert ids == {keep["id"]}


async def test_library_requires_authentication(db_session, client):
    restaurant, item, creds = await _make_owner_tenant(db_session, "libauth")
    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/images/library")
    assert resp.status_code == 401


async def test_library_open_to_any_authenticated_role_not_just_owner_manager(db_session, client):
    """The router's other GETs (get_image, list_images) take `CurrentUser`, not the
    OWNER/MANAGER-gated `_MANAGE_IMAGES` dependency used by upload/crop/replace/delete --
    this endpoint matches that same read-only bar, confirmed here with a CASHIER account."""
    from app.core.security import encrypt_secret, hash_password
    from app.models.enums import UserRole
    from app.models.restaurant import Restaurant
    from app.models.user import User

    restaurant, item, owner_creds = await _make_owner_tenant(db_session, "libcashier")
    owner_headers = await _login(client, **owner_creds)
    await _upload(client, restaurant, item, owner_headers)

    email = "cashier-libcashier@kelviontech.dev"
    password = "CashierPass123!"
    cashier = User(
        email=email,
        hashed_password=hash_password(password),
        role=UserRole.CASHIER,
        restaurant_id=restaurant.id,
        is_active=True,
    )
    db_session.add(cashier)
    await db_session.commit()
    cashier_headers = await _login(client, email, password)

    resp = await client.get(f"/api/v1/restaurants/{restaurant.id}/images/library", headers=cashier_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
