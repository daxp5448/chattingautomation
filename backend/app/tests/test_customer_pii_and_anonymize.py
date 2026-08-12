from urllib.parse import parse_qs, urlparse

from app.models.branch import Branch
from app.models.category import Category
from app.models.customer import Customer
from app.models.order import Order, OrderItem
from app.models.product import Product


async def _register_super_admin(client, email="admin@kelviontech.dev"):
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"})
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _setup_token_from_url(setup_url: str) -> str:
    return parse_qs(urlparse(setup_url).query)["token"][0]


async def _create_restaurant_with_owner(client, admin_headers, name="Customer Diner", slug="customer-diner"):
    resp = await client.post("/api/v1/restaurants", json={"name": name, "slug": slug}, headers=admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    token = _setup_token_from_url(body["setup_url"])
    setup_resp = await client.post("/api/v1/auth/setup", json={"token": token, "password": "OwnerPass123!"})
    assert setup_resp.status_code == 204, setup_resp.text
    login = await client.post("/api/v1/auth/login", json={"email": body["owner_email"], "password": "OwnerPass123!"})
    owner_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return body["id"], owner_headers


async def _register_staff(client, owner_headers, restaurant_id, role, email):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": restaurant_id},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_customer(db_session, restaurant_id, phone="+911234567890", name="Real Customer"):
    customer = Customer(restaurant_id=restaurant_id, phone=phone, name=name, email="real@example.com", address={"line1": "123 St"})
    db_session.add(customer)
    await db_session.commit()
    return customer


async def test_kitchen_role_gets_pii_stripped_customer_owner_gets_full(client, db_session):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)
    customer = await _seed_customer(db_session, restaurant_id)
    kitchen_headers = await _register_staff(client, owner_headers, restaurant_id, "kitchen", "kitchen@kelviontech.dev")

    owner_resp = await client.get(f"/api/v1/restaurants/{restaurant_id}/customers", headers=owner_headers)
    assert owner_resp.status_code == 200, owner_resp.text
    owner_body = next(c for c in owner_resp.json() if c["id"] == str(customer.id))
    assert owner_body["phone"] == customer.phone
    assert owner_body["email"] == "real@example.com"
    assert owner_body["address"] == {"line1": "123 St"}

    kitchen_resp = await client.get(f"/api/v1/restaurants/{restaurant_id}/customers", headers=kitchen_headers)
    assert kitchen_resp.status_code == 200, kitchen_resp.text
    kitchen_body = next(c for c in kitchen_resp.json() if c["id"] == str(customer.id))
    assert "phone" not in kitchen_body
    assert "email" not in kitchen_body
    assert "address" not in kitchen_body
    # Non-PII fields are still useful for kitchen ops.
    assert kitchen_body["name"] == "Real Customer"
    assert kitchen_body["id"] == str(customer.id)


async def test_anonymize_endpoint_blanks_pii_but_leaves_orders_intact(client, db_session):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)
    customer = await _seed_customer(db_session, restaurant_id, phone="+919876543210", name="To Be Forgotten")

    branch = Branch(restaurant_id=restaurant_id, name="Main")
    category = Category(restaurant_id=restaurant_id, name="Mains")
    db_session.add_all([branch, category])
    await db_session.flush()
    product = Product(restaurant_id=restaurant_id, category_id=category.id, name="Burger", price=100)
    db_session.add(product)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant_id,
        branch_id=branch.id,
        customer_id=customer.id,
        order_number="ORD-ANON-1",
        subtotal=100,
        tax=5,
        total=105,
    )
    db_session.add(order)
    await db_session.flush()
    item = OrderItem(order_id=order.id, product_id=product.id, name_snapshot="Burger", price_snapshot=100, quantity=1)
    db_session.add(item)
    await db_session.commit()

    resp = await client.post(f"/api/v1/restaurants/{restaurant_id}/customers/{customer.id}/anonymize", headers=owner_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Anonymized Customer"
    assert body["phone"].startswith("anonymized-")
    assert body["email"] is None
    assert body["address"] == {}
    assert "anonymized" in body["tags"]

    # The order (a GST/financial record) is completely untouched -- still queryable,
    # still linked to the same (now-anonymized) customer, amounts unchanged.
    orders_resp = await client.get(f"/api/v1/restaurants/{restaurant_id}/customers/{customer.id}/loyalty", headers=owner_headers)
    assert orders_resp.status_code == 200, orders_resp.text

    await db_session.refresh(order)
    assert order.order_number == "ORD-ANON-1"
    assert order.customer_id == customer.id
    assert float(order.total) == 105


async def test_anonymize_forbidden_for_kitchen_and_cashier(client, db_session):
    admin_headers = await _register_super_admin(client)
    restaurant_id, owner_headers = await _create_restaurant_with_owner(client, admin_headers)
    customer = await _seed_customer(db_session, restaurant_id)
    kitchen_headers = await _register_staff(client, owner_headers, restaurant_id, "kitchen", "kitchen2@kelviontech.dev")
    cashier_headers = await _register_staff(client, owner_headers, restaurant_id, "cashier", "cashier2@kelviontech.dev")

    for headers in (kitchen_headers, cashier_headers):
        resp = await client.post(
            f"/api/v1/restaurants/{restaurant_id}/customers/{customer.id}/anonymize", headers=headers
        )
        assert resp.status_code == 403, resp.text
