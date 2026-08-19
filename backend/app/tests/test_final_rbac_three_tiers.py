"""FINAL PRE-LIVE VERIFICATION section 10, consolidated: Super Admin / Business Admin
(Owner) / Staff (Cashier), exactly as specified -- Super Admin can manage the platform,
a Business Admin cannot access another business, Staff cannot reach Super-Admin-only
functionality. Real API authorization checks, not just nav-hiding on the frontend
(nav filtering is a separate, already-covered concern in frontend/app/(dashboard)/layout.tsx).
"""

from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.user import User
from app.tests.test_restaurants import _register_super_admin


async def _create_business(client, super_headers, name: str, slug: str) -> str:
    resp = await client.post("/api/v1/restaurants", json={"name": name, "slug": slug}, headers=super_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _add_user(db_session, client, restaurant_id: str, role: UserRole, email: str) -> dict:
    user = User(email=email, hashed_password=hash_password("StaffPass123!"), role=role, restaurant_id=restaurant_id, is_active=True)
    db_session.add(user)
    await db_session.commit()
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "StaffPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_super_admin_can_manage_the_platform(client):
    headers = await _register_super_admin(client, email="tiers-super@kelviontech.dev")

    assert (await client.get("/api/v1/restaurants", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/admin/dashboard/platform-stats", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/niche-templates", headers=headers)).status_code == 200
    assert (await client.get("/api/v1/feature-packages", headers=headers)).status_code == 200
    created = await client.post("/api/v1/restaurants", json={"name": "SA Manage Test", "slug": "sa-manage-test"}, headers=headers)
    assert created.status_code == 201, created.text


async def test_business_admin_cannot_access_another_business(client, db_session):
    headers = await _register_super_admin(client, email="tiers-super2@kelviontech.dev")
    business_a = await _create_business(client, headers, "Tenant A", "tiers-tenant-a")
    business_b = await _create_business(client, headers, "Tenant B", "tiers-tenant-b")

    owner_a_headers = await _add_user(db_session, client, business_a, UserRole.OWNER, "tiers-owner-a@kelviontech.dev")

    # Reading/editing Tenant B's own data must 403 for Tenant A's owner, even though
    # they're both legitimately "Business Admin" role, just for different businesses.
    assert (await client.get(f"/api/v1/restaurants/{business_b}", headers=owner_a_headers)).status_code == 403
    assert (await client.get(f"/api/v1/restaurants/{business_b}/branches", headers=owner_a_headers)).status_code == 403
    assert (await client.get(f"/api/v1/restaurants/{business_b}/coupons", headers=owner_a_headers)).status_code == 403
    assert (
        await client.patch(f"/api/v1/restaurants/{business_b}", json={"name": "Hijacked"}, headers=owner_a_headers)
    ).status_code == 403

    # And a Business Admin is not a Super Admin -- the platform-wide views stay closed.
    assert (await client.get("/api/v1/restaurants", headers=owner_a_headers)).status_code == 403
    assert (await client.get("/api/v1/admin/dashboard/platform-stats", headers=owner_a_headers)).status_code == 403


async def test_staff_cannot_reach_super_admin_functionality(client, db_session):
    headers = await _register_super_admin(client, email="tiers-super3@kelviontech.dev")
    business = await _create_business(client, headers, "Tiers Staff Business", "tiers-staff-business")
    cashier_headers = await _add_user(db_session, client, business, UserRole.CASHIER, "tiers-cashier@kelviontech.dev")
    kitchen_headers = await _add_user(db_session, client, business, UserRole.KITCHEN, "tiers-kitchen@kelviontech.dev")

    for staff_headers in (cashier_headers, kitchen_headers):
        # No platform-wide visibility at all.
        assert (await client.get("/api/v1/restaurants", headers=staff_headers)).status_code == 403
        assert (await client.get("/api/v1/admin/dashboard/platform-stats", headers=staff_headers)).status_code == 403
        assert (await client.post("/api/v1/niche-templates", json={"code": "x", "name": "x", "action_type": "order"}, headers=staff_headers)).status_code == 403
        assert (await client.get(f"/api/v1/restaurants/{business}/audit-log", headers=staff_headers)).status_code == 403
        # Nor business-configuration actions even within their OWN business.
        assert (
            await client.post(f"/api/v1/restaurants/{business}/branches", json={"name": "New Branch"}, headers=staff_headers)
        ).status_code == 403
