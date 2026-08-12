"""Regression coverage for auth + PATCH-then-serialize, added after a live smoke test
caught two bugs pytest's fake-sender-based suite never exercised:
  1. passlib/bcrypt>=4.1 incompatibility broke every hash_password/verify_password call.
  2. server_default/onupdate=func.now() on TimestampMixin caused a MissingGreenlet crash
     when serializing a row's `updated_at` right after an UPDATE.
"""

from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

from app.repositories.user_repository import UserRepository

async def test_register_then_login(client):
    email = "auth-test@kelviontech.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": "super_admin"},
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert resp.status_code == 200, resp.text
    tokens = resp.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200, resp.text


async def test_login_rejects_wrong_password(client):
    email = "auth-test-2@kelviontech.dev"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": "super_admin"},
    )
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "WrongPassword"})
    assert resp.status_code == 401


async def test_patch_restaurant_serializes_after_update(client):
    """A PATCH must be able to serialize the updated row in the same request --
    this is exactly the path that crashed with MissingGreenlet before the fix."""
    admin_email = "patch-test-admin@kelviontech.dev"
    await client.post(
        "/api/v1/auth/register",
        json={"email": admin_email, "password": "TestPass123!", "role": "super_admin"},
    )
    login = await client.post("/api/v1/auth/login", json={"email": admin_email, "password": "TestPass123!"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    create = await client.post(
        "/api/v1/restaurants",
        json={"name": "Patch Test Diner", "slug": "patch-test-diner"},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    restaurant_id = create.json()["id"]

    patch = await client.patch(
        f"/api/v1/restaurants/{restaurant_id}",
        json={"delivery_charge": 42},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["delivery_charge"] == 42
    assert patch.json()["updated_at"]


def _setup_token_from_url(setup_url: str) -> str:
    return parse_qs(urlparse(setup_url).query)["token"][0]


async def _register_super_admin_and_login(client, email="setup-flow-admin@kelviontech.dev"):
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "TestPass123!", "role": "super_admin"}
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_create_restaurant_returns_setup_url_not_password(client):
    headers = await _register_super_admin_and_login(client)

    resp = await client.post(
        "/api/v1/restaurants",
        json={"name": "Setup Flow Diner", "slug": "setup-flow-diner"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "owner_temporary_password" not in body
    assert body["setup_url"].startswith("http")
    assert "token=" in body["setup_url"]


async def test_setup_completes_and_then_login_succeeds(client):
    headers = await _register_super_admin_and_login(client, email="setup-flow-admin-2@kelviontech.dev")
    create = await client.post(
        "/api/v1/restaurants",
        json={"name": "Setup Complete Diner", "slug": "setup-complete-diner"},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    token = _setup_token_from_url(body["setup_url"])

    setup = await client.post("/api/v1/auth/setup", json={"token": token, "password": "OwnerPass123!"})
    assert setup.status_code == 204, setup.text

    login = await client.post(
        "/api/v1/auth/login", json={"email": body["owner_email"], "password": "OwnerPass123!"}
    )
    assert login.status_code == 200, login.text
    assert "access_token" in login.json()


async def test_login_fails_before_setup_is_completed(client):
    headers = await _register_super_admin_and_login(client, email="setup-flow-admin-3@kelviontech.dev")
    create = await client.post(
        "/api/v1/restaurants",
        json={"name": "Not Yet Set Up Diner", "slug": "not-yet-set-up-diner"},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    owner_email = create.json()["owner_email"]

    # No password could possibly be correct here -- the account's hashed_password was
    # never derived from anything the caller could know.
    resp = await client.post("/api/v1/auth/login", json={"email": owner_email, "password": "guess"})
    assert resp.status_code == 401, resp.text


async def test_setup_rejects_already_used_token(client):
    headers = await _register_super_admin_and_login(client, email="setup-flow-admin-4@kelviontech.dev")
    create = await client.post(
        "/api/v1/restaurants",
        json={"name": "Reused Token Diner", "slug": "reused-token-diner"},
        headers=headers,
    )
    body = create.json()
    token = _setup_token_from_url(body["setup_url"])

    first = await client.post("/api/v1/auth/setup", json={"token": token, "password": "OwnerPass123!"})
    assert first.status_code == 204, first.text

    second = await client.post("/api/v1/auth/setup", json={"token": token, "password": "AnotherPass123!"})
    assert second.status_code == 400, second.text


async def test_setup_rejects_expired_token(client, db_session):
    headers = await _register_super_admin_and_login(client, email="setup-flow-admin-5@kelviontech.dev")
    create = await client.post(
        "/api/v1/restaurants",
        json={"name": "Expired Token Diner", "slug": "expired-token-diner"},
        headers=headers,
    )
    body = create.json()
    token = _setup_token_from_url(body["setup_url"])

    repo = UserRepository(db_session)
    owner = await repo.get_by_email(body["owner_email"])
    owner.setup_token_expires_at = datetime.utcnow() - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post("/api/v1/auth/setup", json={"token": token, "password": "OwnerPass123!"})
    assert resp.status_code == 400, resp.text
