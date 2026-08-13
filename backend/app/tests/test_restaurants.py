from urllib.parse import parse_qs, urlparse


async def _register_super_admin(client, email="admin@kelviontech.dev"):
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"})
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _setup_token_from_url(setup_url: str) -> str:
    return parse_qs(urlparse(setup_url).query)["token"][0]


async def _complete_setup(client, setup_url: str, password: str = "OwnerPass123!"):
    token = _setup_token_from_url(setup_url)
    resp = await client.post("/api/v1/auth/setup", json={"token": token, "password": password})
    assert resp.status_code == 204, resp.text


async def test_create_restaurant_auto_creates_owner_login(client):
    headers = await _register_super_admin(client)

    resp = await client.post(
        "/api/v1/restaurants", json={"name": "Auto Owner Diner", "slug": "auto-owner-diner"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["owner_email"]
    assert body["setup_url"]
    assert "owner_temporary_password" not in body

    # Can't log in yet -- the owner account has no usable password until setup completes.
    premature_login = await client.post(
        "/api/v1/auth/login", json={"email": body["owner_email"], "password": "whatever"}
    )
    assert premature_login.status_code == 401, premature_login.text

    await _complete_setup(client, body["setup_url"], password="OwnerPass123!")

    login = await client.post(
        "/api/v1/auth/login", json={"email": body["owner_email"], "password": "OwnerPass123!"}
    )
    assert login.status_code == 200, login.text


async def test_list_restaurants_includes_demo_restaurants_flagged(client):
    """GET /restaurants used to hard-exclude is_demo restaurants (so Demo Bot testing was
    invisible to Super Admin -- no way to open a demo restaurant's own dashboard/orders/
    live-chat). Now included, distinguished via is_demo on each row instead of hidden."""
    headers = await _register_super_admin(client)

    real = await client.post(
        "/api/v1/restaurants", json={"name": "Real Diner", "slug": "real-diner"}, headers=headers
    )
    assert real.status_code == 201, real.text

    demo = await client.post(
        "/api/v1/restaurants", json={"name": "Demo Diner", "slug": "demo-diner", "is_demo": True}, headers=headers
    )
    assert demo.status_code == 201, demo.text

    listed = await client.get("/api/v1/restaurants", headers=headers)
    assert listed.status_code == 200, listed.text
    by_slug = {r["slug"]: r for r in listed.json()}
    assert by_slug["real-diner"]["is_demo"] is False
    assert by_slug["demo-diner"]["is_demo"] is True


async def test_unauthenticated_register_blocked_once_an_account_exists(client):
    await _register_super_admin(client)

    # _register_super_admin logged in on this same client, which -- like a real browser --
    # now carries the httpOnly session cookies that login sets. Clear them so this request
    # actually simulates an anonymous attacker instead of the just-created super admin.
    client.cookies.clear()

    resp = await client.post(
        "/api/v1/auth/register", json={"email": "attacker@kelviontech.dev", "password": "TestPass123!", "role": "super_admin"}
    )
    assert resp.status_code == 401, resp.text


async def test_owner_cannot_self_elevate_to_super_admin(client):
    admin_headers = await _register_super_admin(client)
    restaurant = (
        await client.post("/api/v1/restaurants", json={"name": "Owner Diner", "slug": "owner-diner"}, headers=admin_headers)
    ).json()

    await _complete_setup(client, restaurant["setup_url"], password="OwnerPass123!")
    owner_login = await client.post(
        "/api/v1/auth/login", json={"email": restaurant["owner_email"], "password": "OwnerPass123!"}
    )
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "sneaky@kelviontech.dev", "password": "TestPass123!", "role": "super_admin"},
        headers=owner_headers,
    )
    assert resp.status_code == 403, resp.text

    # Owners can still create their own staff, scoped to their own restaurant.
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "cashier@kelviontech.dev",
            "password": "TestPass123!",
            "role": "cashier",
            "restaurant_id": restaurant["id"],
        },
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
