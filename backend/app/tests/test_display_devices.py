from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException

from app.api.v1.routers.display_devices import resolve_display_device
from app.core.display_tokens import hash_display_token
from app.models.category import Category
from app.models.customer import Customer
from app.models.display_device import DisplayDevice
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.branch import Branch


async def _register_super_admin(client, email="admin@kelviontech.dev"):
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"})
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _setup_token_from_url(setup_url: str) -> str:
    return parse_qs(urlparse(setup_url).query)["token"][0]


async def _create_restaurant_with_owner(client, admin_headers, name="Display Diner", slug="display-diner"):
    resp = await client.post("/api/v1/restaurants", json={"name": name, "slug": slug}, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    token = _setup_token_from_url(body["setup_url"])
    setup_resp = await client.post("/api/v1/auth/setup", json={"token": token, "password": "OwnerPass123!"})
    assert setup_resp.status_code == 204, setup_resp.text
    login = await client.post("/api/v1/auth/login", json={"email": body["owner_email"], "password": "OwnerPass123!"})
    owner_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return body["id"], owner_headers


async def _seed_order(db_session, restaurant_id, branch_name="Main"):
    """Seeds a branch/category/product/customer/order directly through the ORM so the
    POS orders endpoint has something to return -- there's no HTTP-level order-creation
    endpoint to hit from a test client (orders are created by the WhatsApp flow engine)."""
    branch = Branch(restaurant_id=restaurant_id, name=branch_name)
    db_session.add(branch)
    await db_session.flush()

    category = Category(restaurant_id=restaurant_id, name="Mains")
    db_session.add(category)
    await db_session.flush()

    product = Product(restaurant_id=restaurant_id, category_id=category.id, name="Burger", price=100)
    db_session.add(product)
    await db_session.flush()

    customer = Customer(restaurant_id=restaurant_id, phone="+911234567890", name="Secret Customer")
    db_session.add(customer)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant_id,
        branch_id=branch.id,
        customer_id=customer.id,
        order_number="ORD-1",
        subtotal=100,
        total=100,
    )
    db_session.add(order)
    await db_session.flush()

    item = OrderItem(order_id=order.id, product_id=product.id, name_snapshot="Burger", price_snapshot=100, quantity=2)
    db_session.add(item)
    await db_session.commit()
    return branch, order


async def test_create_device_returns_token_once_and_list_never_leaks_it(client):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)

    resp = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/display-devices",
        json={"name": "Counter Screen"},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Counter Screen"
    assert body["token"]
    device_id = body["id"]

    list_resp = await client.get(f"/api/v1/restaurants/{restaurant_id}/display-devices", headers=owner_headers)
    assert list_resp.status_code == 200, list_resp.text
    devices = list_resp.json()
    assert len(devices) == 1
    assert devices[0]["id"] == device_id
    assert "token" not in devices[0]
    assert "token_hash" not in devices[0]
    assert devices[0]["revoked_at"] is None


async def test_pos_orders_excludes_pii_and_rejects_bad_tokens(client, db_session):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)
    branch, order = await _seed_order(db_session, restaurant_id)

    create_resp = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/display-devices",
        json={"name": "Kitchen Screen"},
        headers=owner_headers,
    )
    token = create_resp.json()["token"]

    ok_resp = await client.get(f"/api/v1/pos/{restaurant_id}/orders", params={"token": token})
    assert ok_resp.status_code == 200, ok_resp.text
    orders = ok_resp.json()
    assert len(orders) == 1
    pos_order = orders[0]
    assert pos_order["order_number"] == "ORD-1"
    assert pos_order["total"] == 100
    assert len(pos_order["items"]) == 1
    assert pos_order["items"][0] == {"name_snapshot": "Burger", "quantity": 2}
    # No PII / payment / gateway data anywhere in the response.
    forbidden_keys = {"customer_id", "customer_name", "customer_phone", "phone", "payment_method", "payment_status", "gateway_metadata", "delivery_address"}
    assert not (forbidden_keys & pos_order.keys())

    bad_token_resp = await client.get(f"/api/v1/pos/{restaurant_id}/orders", params={"token": "not-a-real-token"})
    assert bad_token_resp.status_code == 401, bad_token_resp.text

    # Token valid, but for a different restaurant -> 401.
    other_restaurant_id, _ = await _create_restaurant_with_owner(client, admin_headers, name="Other Diner", slug="other-diner")
    wrong_restaurant_resp = await client.get(f"/api/v1/pos/{other_restaurant_id}/orders", params={"token": token})
    assert wrong_restaurant_resp.status_code == 401, wrong_restaurant_resp.text


async def test_revoking_a_device_immediately_invalidates_its_token(client, db_session):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)
    await _seed_order(db_session, restaurant_id)

    create_resp = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/display-devices",
        json={"name": "Counter Screen"},
        headers=owner_headers,
    )
    device_id = create_resp.json()["id"]
    token = create_resp.json()["token"]

    still_ok = await client.get(f"/api/v1/pos/{restaurant_id}/orders", params={"token": token})
    assert still_ok.status_code == 200

    revoke_resp = await client.delete(f"/api/v1/restaurants/{restaurant_id}/display-devices/{device_id}", headers=owner_headers)
    assert revoke_resp.status_code == 204, revoke_resp.text

    now_blocked = await client.get(f"/api/v1/pos/{restaurant_id}/orders", params={"token": token})
    assert now_blocked.status_code == 401, now_blocked.text

    list_resp = await client.get(f"/api/v1/restaurants/{restaurant_id}/display-devices", headers=owner_headers)
    assert list_resp.json()[0]["revoked_at"] is not None


async def test_branch_scoped_device_only_sees_its_own_branch_orders(client, db_session):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)
    branch_a, order_a = await _seed_order(db_session, restaurant_id, branch_name="Branch A")

    branch_b = Branch(restaurant_id=restaurant_id, name="Branch B")
    db_session.add(branch_b)
    await db_session.commit()

    device_resp = await client.post(
        f"/api/v1/restaurants/{restaurant_id}/display-devices",
        json={"name": "Branch B Screen", "branch_id": str(branch_b.id)},
        headers=owner_headers,
    )
    token = device_resp.json()["token"]

    resp = await client.get(f"/api/v1/pos/{restaurant_id}/orders", params={"token": token})
    assert resp.status_code == 200
    assert resp.json() == []  # order_a belongs to Branch A, not Branch B


async def test_resolve_display_device_helper_directly(db_session):
    """Direct unit test of the auth-resolution helper -- there's no practical way to
    exercise the WS device-token path (app/api/v1/routers/ws.py) without a real socket
    in this test suite, but it shares this exact same lookup/hash/revoked-check shape."""
    from app.models.restaurant import Restaurant

    restaurant = Restaurant(name="Helper Diner", slug="helper-diner")
    db_session.add(restaurant)
    await db_session.flush()

    device = DisplayDevice(restaurant_id=restaurant.id, name="Screen", token_hash=hash_display_token("raw-secret"))
    db_session.add(device)
    await db_session.commit()

    resolved = await resolve_display_device(db_session, restaurant.id, "raw-secret")
    assert resolved.id == device.id

    with pytest.raises(HTTPException) as exc_info:
        await resolve_display_device(db_session, restaurant.id, "wrong-secret")
    assert exc_info.value.status_code == 401
