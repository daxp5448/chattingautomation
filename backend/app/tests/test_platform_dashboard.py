"""GET /admin/dashboard/platform-stats -- the Super Admin Dashboard's real cross-tenant
aggregate (see app/api/v1/routers/dashboard.py). Verifies every number is a genuine DB
aggregate (not a client-side reduce, not hardcoded), that demo/showcase restaurants are
excluded, and that both engines' order-shaped activity are combined correctly.
"""
import uuid

from app.models.customer import Customer
from app.models.engagement import Engagement
from app.models.enums import EngagementType
from app.models.restaurant import Restaurant


async def _register_super_admin(client, email="platform-admin@kelviontech.dev"):
    resp = await client.post("/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"})
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_platform_stats_aggregates_across_restaurants_and_excludes_demo(client, db_session):
    headers = await _register_super_admin(client)

    real = await client.post(
        "/api/v1/restaurants",
        json={"name": "Real Salon", "slug": "real-salon-platform-test"},
        headers=headers,
    )
    assert real.status_code == 201, real.text
    real_id = uuid.UUID(real.json()["id"])

    demo = await client.post(
        "/api/v1/restaurants",
        json={"name": "Demo Salon", "slug": "demo-salon-platform-test", "is_demo": True},
        headers=headers,
    )
    assert demo.status_code == 201, demo.text
    demo_id = uuid.UUID(demo.json()["id"])

    # niche_type isn't a RestaurantCreate field (it's set by provisioning from a
    # niche_code, see restaurants.py) -- set directly here since this test is only
    # exercising the aggregate's grouping, not the provisioning flow itself.
    real_row = await db_session.get(Restaurant, real_id)
    real_row.niche_type = "salon"

    # Seed one order-type and one appointment-type engagement on the real restaurant, and
    # one on the demo restaurant -- the demo one must NOT show up in any platform total.
    real_customer = Customer(restaurant_id=real_id, phone="+10000000001", name="Real Customer")
    demo_customer = Customer(restaurant_id=demo_id, phone="+10000000002", name="Demo Customer")
    db_session.add_all([real_customer, demo_customer])
    await db_session.flush()

    order = Engagement(
        restaurant_id=real_id, customer_id=real_customer.id, reference_number="PLATTEST-ORDER-1",
        type=EngagementType.ORDER, total=250,
    )
    appointment = Engagement(
        restaurant_id=real_id, customer_id=real_customer.id, reference_number="PLATTEST-APPT-1",
        type=EngagementType.APPOINTMENT, total=0,
    )
    demo_order = Engagement(
        restaurant_id=demo_id, customer_id=demo_customer.id, reference_number="PLATTEST-DEMO-ORDER-1",
        type=EngagementType.ORDER, total=999999,
    )
    db_session.add_all([order, appointment, demo_order])
    await db_session.commit()

    resp = await client.get("/api/v1/admin/dashboard/platform-stats", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Exactly the one real restaurant -- the demo one is excluded from every count. A
    # freshly created restaurant defaults to RestaurantStatus.ONBOARDING (not ACTIVE), so
    # it counts toward "total" but not "active" until explicitly activated.
    assert body["businesses"]["total"] == 1
    assert body["businesses"]["active"] == 0
    assert body["businesses"]["by_niche"] == {"salon": 1}

    assert body["orders_generic"]["count"] == 1
    assert body["orders_generic"]["revenue"] == 250.0
    assert body["orders"]["count"] == 1  # combined legacy+generic, still excludes the demo order
    assert body["orders"]["revenue"] == 250.0
    assert body["appointments"]["count"] == 1

    reference_numbers = {entry["id"] for entry in body["recent_activity"]}
    assert str(order.id) in reference_numbers
    assert str(appointment.id) in reference_numbers
    assert str(demo_order.id) not in reference_numbers


async def test_platform_stats_requires_super_admin(client):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "owner-cant-see-platform@kelviontech.dev", "password": "TestPass123!", "role": "super_admin"},
    )
    assert resp.status_code == 201, resp.text

    # A super_admin creates the business, but the auto-created OWNER login must not be
    # able to read the platform-wide dashboard -- that's Super-Admin-only data about
    # every OTHER tenant, not this one business's own scope.
    login = await client.post(
        "/api/v1/auth/login", json={"email": "owner-cant-see-platform@kelviontech.dev", "password": "TestPass123!"}
    )
    super_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = await client.post(
        "/api/v1/restaurants",
        json={"name": "Owner Scope Test", "slug": "owner-scope-test"},
        headers=super_headers,
    )
    assert created.status_code == 201, created.text

    from urllib.parse import parse_qs, urlparse

    token = parse_qs(urlparse(created.json()["setup_url"]).query)["token"][0]
    setup = await client.post("/api/v1/auth/setup", json={"token": token, "password": "OwnerPass123!"})
    assert setup.status_code == 204, setup.text
    owner_login = await client.post(
        "/api/v1/auth/login", json={"email": created.json()["owner_email"], "password": "OwnerPass123!"}
    )
    owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

    resp = await client.get("/api/v1/admin/dashboard/platform-stats", headers=owner_headers)
    assert resp.status_code == 403, resp.text
