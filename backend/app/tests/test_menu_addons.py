"""Addon CRUD (backend/app/api/v1/routers/menu.py) -- create+list already existed;
PATCH/DELETE were a gap (Super Admin audit item) closed alongside categories/products,
which already had all four. Full create -> list -> update -> delete -> verify-gone cycle
against a real restaurant, not just route existence.
"""


async def _register_super_admin(client, email="menu-admin@kelviontech.dev"):
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"})
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_addon_full_crud_cycle(client):
    headers = await _register_super_admin(client)
    restaurant = await client.post(
        "/api/v1/restaurants", json={"name": "Addon Diner", "slug": "addon-diner"}, headers=headers
    )
    assert restaurant.status_code == 201, restaurant.text
    restaurant_id = restaurant.json()["id"]

    created = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/addons", json={"name": "Extra Cheese", "price": 30}, headers=headers
    )
    assert created.status_code == 201, created.text
    addon_id = created.json()["id"]
    assert created.json()["name"] == "Extra Cheese"
    assert created.json()["price"] == 30

    listed = await client.get(f"/api/v1/restaurants/{restaurant_id}/addons", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(a["id"] == addon_id for a in listed.json())

    updated = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}/addons/{addon_id}", json={"price": 40}, headers=headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["price"] == 40
    assert updated.json()["name"] == "Extra Cheese"  # untouched field survives a partial PATCH

    refetched = await client.get(f"/api/v1/restaurants/{restaurant_id}/addons", headers=headers)
    assert next(a for a in refetched.json() if a["id"] == addon_id)["price"] == 40

    deleted = await client.delete(f"/api/v1/restaurants/{restaurant_id}/addons/{addon_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text

    after_delete = await client.get(f"/api/v1/restaurants/{restaurant_id}/addons", headers=headers)
    assert not any(a["id"] == addon_id for a in after_delete.json())


async def test_update_nonexistent_addon_404s(client):
    headers = await _register_super_admin(client)
    restaurant = await client.post(
        "/api/v1/restaurants", json={"name": "Addon Diner 2", "slug": "addon-diner-2"}, headers=headers
    )
    restaurant_id = restaurant.json()["id"]

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}/addons/00000000-0000-0000-0000-000000000000",
        json={"price": 5},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text
