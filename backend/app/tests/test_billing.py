"""DEMO billing only (see app/api/v1/routers/billing.py's module docstring) -- no real
payment gateway. Covers: signup starts a 7-day trial automatically, GET .../billing/status
reflects expiry correctly, POST .../demo-pay is the fake charge and is role-gated.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.restaurant import Restaurant
from app.repositories.audit_log_repository import AuditLogRepository
from app.tests.test_restaurants import _register_super_admin
from app.tests.test_signup import _signup


async def test_signup_starts_a_seven_day_trial(client, db_session):
    result = await _signup(client, db_session)
    restaurant = (
        await db_session.execute(select(Restaurant).where(Restaurant.id == result["restaurant_id"]))
    ).scalar_one()
    assert restaurant.trial_ends_at is not None
    trial_ends_at = restaurant.trial_ends_at
    if trial_ends_at.tzinfo is None:
        # SQLite doesn't reliably round-trip tzinfo for a DateTime(timezone=True) column
        # when read directly off the ORM within the same session -- everything that
        # writes this column writes UTC (see billing.py's own defensive handling).
        trial_ends_at = trial_ends_at.replace(tzinfo=timezone.utc)
    delta = trial_ends_at - datetime.now(timezone.utc)
    # Allow slack for test execution time -- must be close to 7 days, not exactly to the
    # microsecond.
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, minutes=1)
    assert restaurant.is_demo_billing_paid is False


async def _verify(client, result):
    r = await client.post(
        "/api/v1/signup/verify-otp",
        json={"restaurant_id": result["restaurant_id"], "code": result["debug_otp_code"]},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_billing_status_not_expired_right_after_signup(client, db_session):
    result = await _signup(client, db_session)
    headers = await _verify(client, result)

    r = await client.get(f"/api/v1/restaurants/{result['restaurant_id']}/billing/status", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trial_expired"] is False
    assert body["is_demo_billing_paid"] is False
    assert body["trial_ends_at"] is not None


async def test_billing_status_expired_once_trial_date_passes(client, db_session):
    result = await _signup(client, db_session)
    headers = await _verify(client, result)

    restaurant = (
        await db_session.execute(select(Restaurant).where(Restaurant.id == result["restaurant_id"]))
    ).scalar_one()
    restaurant.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    r = await client.get(f"/api/v1/restaurants/{result['restaurant_id']}/billing/status", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["trial_expired"] is True


async def test_demo_pay_flips_the_flag_and_clears_expired_status(client, db_session):
    result = await _signup(client, db_session)
    headers = await _verify(client, result)

    restaurant = (
        await db_session.execute(select(Restaurant).where(Restaurant.id == result["restaurant_id"]))
    ).scalar_one()
    restaurant.trial_ends_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    r = await client.post(f"/api/v1/restaurants/{result['restaurant_id']}/billing/demo-pay", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_demo_billing_paid"] is True
    # Trial having passed is still true (demo-pay doesn't rewrite trial_ends_at) -- a
    # paid business just isn't gated by it, per the frontend banner reading both fields.
    assert body["trial_expired"] is True

    await db_session.refresh(restaurant)
    assert restaurant.is_demo_billing_paid is True


async def test_demo_pay_is_audit_logged(client, db_session):
    result = await _signup(client, db_session)
    headers = await _verify(client, result)

    r = await client.post(f"/api/v1/restaurants/{result['restaurant_id']}/billing/demo-pay", headers=headers)
    assert r.status_code == 200, r.text

    entries = await AuditLogRepository(db_session).list_for_restaurant(result["restaurant_id"])
    assert "demo_payment_recorded" in [e.action for e in entries]


async def test_staff_roles_cannot_demo_pay(client, db_session):
    """Only the owner (or a super_admin) can trigger the fake charge -- mirrors the
    role-gating pattern update_restaurant already uses for subscription fields."""
    result = await _signup(client, db_session)
    owner_headers = await _verify(client, result)

    manager_resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "manager-billing-test@kelviontech.dev",
            "password": "TestPass123!",
            "role": "manager",
            "restaurant_id": result["restaurant_id"],
        },
        headers=owner_headers,
    )
    assert manager_resp.status_code == 201, manager_resp.text
    manager_login = await client.post(
        "/api/v1/auth/login", json={"email": "manager-billing-test@kelviontech.dev", "password": "TestPass123!"}
    )
    manager_headers = {"Authorization": f"Bearer {manager_login.json()['access_token']}"}

    r = await client.post(f"/api/v1/restaurants/{result['restaurant_id']}/billing/demo-pay", headers=manager_headers)
    assert r.status_code == 403, r.text


async def test_super_admin_can_view_and_demo_pay_for_any_business(client, db_session):
    # Register the admin BEFORE signup: signup+verify sets owner auth cookies on this
    # shared test client, so /auth/register afterwards would see an authenticated OWNER
    # (correctly refused) instead of an unauthenticated bootstrap caller -- same ordering
    # fix as test_signup.py's approval-flow test.
    admin_headers = await _register_super_admin(client, email="billing-admin@kelviontech.dev")
    result = await _signup(client, db_session)

    r = await client.get(f"/api/v1/restaurants/{result['restaurant_id']}/billing/status", headers=admin_headers)
    assert r.status_code == 200, r.text

    r = await client.post(f"/api/v1/restaurants/{result['restaurant_id']}/billing/demo-pay", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["is_demo_billing_paid"] is True
