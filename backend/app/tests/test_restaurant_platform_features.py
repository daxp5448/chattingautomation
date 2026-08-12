"""Platform-management extras: order stats on the super-admin list, per-restaurant data
export, and trial_ends_at being restricted the same way status is.
"""
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    _button_reply,
    _list_reply,
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
    demo_tenant,
)


async def _register_super_admin(client, email="platform-admin@kelviontech.dev"):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"}
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _place_one_order(client, demo_tenant):
    category = demo_tenant["category"]
    product = demo_tenant["product"]
    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:order_food")))
    await _post_webhook(client, _message_value(_list_reply(f"category:{category.id}")))
    await _post_webhook(client, _message_value(_list_reply(f"product:{product.id}")))
    await _post_webhook(client, _message_value(_text("1")))
    await _post_webhook(client, _message_value(_button_reply("cart:checkout")))
    await _post_webhook(client, _message_value(_button_reply("fulfillment:delivery")))
    await _post_webhook(client, _message_value(_text("skip")))
    await _post_webhook(client, _message_value(_text("123 Test Street")))
    await _post_webhook(client, _message_value(_button_reply("order:confirm")))


async def test_restaurant_list_includes_order_stats(client, demo_tenant, _use_in_memory_sender):
    admin_headers = await _register_super_admin(client)
    await _place_one_order(client, demo_tenant)

    resp = await client.get("/api/v1/restaurants", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["id"] == str(demo_tenant["restaurant"].id))
    assert row["total_orders"] == 1
    assert row["last_order_at"] is not None


async def test_restaurant_list_zero_orders_for_untouched_restaurant(client, demo_tenant):
    admin_headers = await _register_super_admin(client)
    resp = await client.get("/api/v1/restaurants", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    row = next(r for r in resp.json() if r["id"] == str(demo_tenant["restaurant"].id))
    assert row["total_orders"] == 0
    assert row["last_order_at"] is None


async def test_export_contains_menu_and_orders(client, demo_tenant, _use_in_memory_sender):
    admin_headers = await _register_super_admin(client)
    await _place_one_order(client, demo_tenant)

    resp = await client.get(f"/api/v1/restaurants/{demo_tenant['restaurant'].id}/export", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) >= {"restaurant", "branches", "categories", "products", "coupons", "customers", "orders"}
    assert len(data["products"]) == 1
    assert len(data["orders"]) == 1
    assert data["orders"][0]["items"][0]["quantity"] == 1
    # No secrets of any kind leak into an export.
    assert "razorpay_key_secret" not in data["restaurant"]
    assert "whatsapp_access_token" not in data["restaurant"]


async def test_only_super_admin_can_set_trial_date(client, demo_tenant):
    admin_headers = await _register_super_admin(client)
    restaurant = demo_tenant["restaurant"]

    owner_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "owner-trial-test@kelviontech.dev",
            "password": "TestPass123!",
            "role": "owner",
            "restaurant_id": str(restaurant.id),
        },
        headers=admin_headers,
    )
    assert owner_resp.status_code == 201, owner_resp.text
    owner_login = await client.post(
        "/api/v1/auth/login", json={"email": "owner-trial-test@kelviontech.dev", "password": "TestPass123!"}
    )
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}",
        json={"trial_ends_at": "2026-12-31T00:00:00Z"},
        headers=owner_headers,
    )
    assert resp.status_code == 403, resp.text

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}",
        json={"trial_ends_at": "2026-12-31T00:00:00Z"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["trial_ends_at"].startswith("2026-12-31")
