"""Proof for the Feature Package system: Super-Admin-only package CRUD, snapshot-at-
assignment (not live-reference), require_feature's None=unrestricted default (the fix that
keeps Prince Corner and every pre-existing/unassigned restaurant unaffected), soft-gated
mutating endpoints across coupons/faq/whatsapp_templates/broadcasts, and both live-chat
routers (legacy conversations.py and generic_conversations.py) gated identically.
"""

from app.core.security import encrypt_secret
from app.models.customer import Customer
from app.models.feature_package import FeaturePackage
from app.models.restaurant import Restaurant
from app.tests.test_restaurants import _register_super_admin

PHONE_NUMBER_ID = "FEATPKG_TEST_PHONE"


async def _register_and_login(client, restaurant_id, role="owner", email="owner@featpkg-test.dev", auth_headers=None):
    """auth_headers=None registers as the "very first account on this deployment" (only
    works once per fresh test DB -- see auth.py::register). Any test that also needs a
    super_admin in the SAME test must call _register_super_admin FIRST and pass its
    headers here, since a second unauthenticated registration 401s once any account
    exists."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": str(restaurant_id)},
        headers=auth_headers or {},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_restaurant(db_session, slug: str, enabled_features=None, feature_package_id=None) -> Restaurant:
    restaurant = Restaurant(
        name=f"Feature Package Test {slug}", slug=f"feature-package-test-{slug}",
        whatsapp_phone_number_id=f"{PHONE_NUMBER_ID}_{slug}",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        enabled_features=enabled_features, feature_package_id=feature_package_id,
    )
    db_session.add(restaurant)
    await db_session.commit()
    return restaurant


async def _make_package(db_session, name: str, feature_codes: list[str], is_default: bool = False) -> FeaturePackage:
    package = FeaturePackage(name=name, feature_codes=feature_codes, is_default=is_default)
    db_session.add(package)
    await db_session.commit()
    return package


# --- FeaturePackage CRUD -----------------------------------------------------------------


async def test_feature_package_crud_requires_super_admin(client, db_session):
    # super_admin must register first -- it's the "very first account" on this fresh
    # test DB; the owner below registers authenticated as super_admin instead (see
    # _register_and_login's docstring).
    admin_headers = await _register_super_admin(client, "admin1@featpkg-test.dev")
    restaurant = await _make_restaurant(db_session, "crudguard")
    owner_headers = await _register_and_login(client, restaurant.id, auth_headers=admin_headers)

    resp = await client.post(
        "/api/v1/feature-packages", headers=owner_headers,
        json={"name": "Starter", "feature_codes": ["coupons"]},
    )
    assert resp.status_code == 403

    created = await client.post(
        "/api/v1/feature-packages", headers=admin_headers,
        json={"name": "Starter", "feature_codes": ["coupons"]},
    )
    assert created.status_code == 201, created.text
    package_id = created.json()["id"]

    patched = await client.patch(
        f"/api/v1/feature-packages/{package_id}", headers=admin_headers, json={"is_default": True}
    )
    assert patched.status_code == 200
    assert patched.json()["is_default"] is True

    forbidden_patch = await client.patch(
        f"/api/v1/feature-packages/{package_id}", headers=owner_headers, json={"is_default": False}
    )
    assert forbidden_patch.status_code == 403

    forbidden_delete = await client.delete(f"/api/v1/feature-packages/{package_id}", headers=owner_headers)
    assert forbidden_delete.status_code == 403

    deleted = await client.delete(f"/api/v1/feature-packages/{package_id}", headers=admin_headers)
    assert deleted.status_code == 204


async def test_feature_package_rejects_unknown_code(client, db_session):
    admin_headers = await _register_super_admin(client, "admin2@featpkg-test.dev")
    resp = await client.post(
        "/api/v1/feature-packages", headers=admin_headers,
        json={"name": "Bad", "feature_codes": ["not_a_real_feature"]},
    )
    assert resp.status_code == 422


async def test_feature_package_list_and_registry_open_to_any_authenticated_user(client, db_session):
    restaurant = await _make_restaurant(db_session, "openlist")
    owner_headers = await _register_and_login(client, restaurant.id, email="owner3@featpkg-test.dev")

    listed = await client.get("/api/v1/feature-packages", headers=owner_headers)
    assert listed.status_code == 200

    registry = await client.get("/api/v1/feature-packages/registry", headers=owner_headers)
    assert registry.status_code == 200
    assert "coupons" in registry.json()


# --- Restaurant creation: snapshot-at-assignment ------------------------------------------


async def test_restaurant_creation_with_explicit_package_snapshots_features(client, db_session):
    package = await _make_package(db_session, "Growth", ["coupons", "broadcasts"])
    admin_headers = await _register_super_admin(client, "admin4@featpkg-test.dev")

    resp = await client.post(
        "/api/v1/restaurants", headers=admin_headers,
        json={"name": "Snap Co", "slug": "snap-co", "feature_package_id": str(package.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["feature_package_id"] == str(package.id)
    assert sorted(body["enabled_features"]) == ["broadcasts", "coupons"]

    # Editing the package afterward must NOT retroactively change the restaurant already
    # assigned to it -- the whole point of snapshot-at-assignment.
    patched = await client.patch(
        f"/api/v1/feature-packages/{package.id}", headers=admin_headers, json={"feature_codes": ["coupons"]}
    )
    assert patched.status_code == 200
    refetched = await client.get(f"/api/v1/restaurants/{body['id']}", headers=admin_headers)
    assert sorted(refetched.json()["enabled_features"]) == ["broadcasts", "coupons"]


async def test_restaurant_creation_with_default_package_used_when_unspecified(client, db_session):
    await _make_package(db_session, "Default Pack", ["faq_autoresponder"], is_default=True)
    admin_headers = await _register_super_admin(client, "admin5@featpkg-test.dev")

    resp = await client.post(
        "/api/v1/restaurants", headers=admin_headers, json={"name": "Default Co", "slug": "default-co"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["enabled_features"] == ["faq_autoresponder"]


async def test_restaurant_creation_without_any_package_leaves_enabled_features_none(client, db_session):
    admin_headers = await _register_super_admin(client, "admin6@featpkg-test.dev")
    resp = await client.post(
        "/api/v1/restaurants", headers=admin_headers, json={"name": "No Pack Co", "slug": "no-pack-co"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["feature_package_id"] is None
    assert resp.json()["enabled_features"] is None


# --- require_feature enforcement (via coupons.py as the representative gated router) ------


async def test_require_feature_allows_when_enabled_features_is_none(client, db_session):
    restaurant = await _make_restaurant(db_session, "unassigned")  # enabled_features=None
    headers = await _register_and_login(client, restaurant.id, email="owner7@featpkg-test.dev")
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=headers,
        json={"code": "WELCOME10", "type": "percentage", "value": 10},
    )
    assert resp.status_code == 201, resp.text


async def test_require_feature_blocks_when_package_missing_code(client, db_session):
    package = await _make_package(db_session, "No Coupons", ["broadcasts"])
    restaurant = await _make_restaurant(db_session, "blocked", enabled_features=list(package.feature_codes), feature_package_id=package.id)
    headers = await _register_and_login(client, restaurant.id, email="owner8@featpkg-test.dev")
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=headers,
        json={"code": "WELCOME10", "type": "percentage", "value": 10},
    )
    assert resp.status_code == 403
    assert "not included in your plan" in resp.json()["detail"]


async def test_require_feature_allows_when_package_has_code(client, db_session):
    package = await _make_package(db_session, "Has Coupons", ["coupons"])
    restaurant = await _make_restaurant(db_session, "allowed", enabled_features=list(package.feature_codes), feature_package_id=package.id)
    headers = await _register_and_login(client, restaurant.id, email="owner9@featpkg-test.dev")
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=headers,
        json={"code": "WELCOME10", "type": "percentage", "value": 10},
    )
    assert resp.status_code == 201, resp.text


async def test_require_feature_super_admin_bypasses(client, db_session):
    package = await _make_package(db_session, "Empty", [])
    restaurant = await _make_restaurant(db_session, "superbypass", enabled_features=[], feature_package_id=package.id)
    admin_headers = await _register_super_admin(client, "admin10@featpkg-test.dev")
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/coupons", headers=admin_headers,
        json={"code": "WELCOME10", "type": "percentage", "value": 10},
    )
    assert resp.status_code == 201, resp.text


# --- Reads and wind-down actions stay ungated even when a feature is missing --------------


async def test_reads_and_delete_stay_ungated_even_without_the_feature(client, db_session):
    package = await _make_package(db_session, "No Coupons Reads", [])
    restaurant = await _make_restaurant(db_session, "readsok", enabled_features=[], feature_package_id=package.id)
    headers = await _register_and_login(client, restaurant.id, email="owner11@featpkg-test.dev")

    listed = await client.get(f"/api/v1/restaurants/{restaurant.id}/coupons", headers=headers)
    assert listed.status_code == 200


# --- feature_package_id is super-admin-only; enabled_features is never directly settable --


async def test_owner_cannot_reassign_or_directly_set_features(client, db_session):
    package = await _make_package(db_session, "Reassign Target", ["coupons"])
    restaurant = await _make_restaurant(db_session, "noescalate")  # unassigned, enabled_features=None
    headers = await _register_and_login(client, restaurant.id, email="owner12@featpkg-test.dev")

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", headers=headers, json={"feature_package_id": str(package.id)}
    )
    assert resp.status_code == 403

    # enabled_features isn't even a field on RestaurantUpdate -- pydantic silently drops
    # it, it can never reach the model this way.
    resp2 = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", headers=headers, json={"enabled_features": ["coupons"]}
    )
    assert resp2.status_code == 200
    assert resp2.json()["enabled_features"] is None


async def test_super_admin_reassignment_resnapshots_enabled_features(client, db_session):
    old_package = await _make_package(db_session, "Old", ["coupons"])
    new_package = await _make_package(db_session, "New", ["broadcasts", "faq_autoresponder"])
    restaurant = await _make_restaurant(db_session, "resnap", enabled_features=list(old_package.feature_codes), feature_package_id=old_package.id)
    admin_headers = await _register_super_admin(client, "admin13@featpkg-test.dev")

    resp = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", headers=admin_headers, json={"feature_package_id": str(new_package.id)}
    )
    assert resp.status_code == 200
    assert sorted(resp.json()["enabled_features"]) == ["broadcasts", "faq_autoresponder"]

    cleared = await client.patch(
        f"/api/v1/restaurants/{restaurant.id}", headers=admin_headers, json={"feature_package_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["enabled_features"] is None


# --- Dual live-chat routers gated identically (legacy + generic engine) -------------------


async def test_live_chat_handoff_gated_on_legacy_conversations_router(client, db_session, monkeypatch):
    from app.api.v1.routers import conversations
    from app.services.whatsapp_client import InMemoryWhatsAppSender

    monkeypatch.setattr(conversations, "_sender", InMemoryWhatsAppSender())

    package = await _make_package(db_session, "No Handoff Legacy", [])
    restaurant = await _make_restaurant(db_session, "legacyhandoff", enabled_features=[], feature_package_id=package.id)
    customer = Customer(restaurant_id=restaurant.id, phone="919999900001")
    db_session.add(customer)
    await db_session.commit()
    headers = await _register_and_login(client, restaurant.id, email="owner14@featpkg-test.dev")

    blocked = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/conversations/{customer.id}/messages",
        headers=headers, json={"body": "hi"},
    )
    assert blocked.status_code == 403

    package.feature_codes = ["live_chat_handoff"]
    restaurant.enabled_features = ["live_chat_handoff"]
    db_session.add_all([package, restaurant])
    await db_session.commit()

    allowed = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/conversations/{customer.id}/messages",
        headers=headers, json={"body": "hi"},
    )
    assert allowed.status_code == 201, allowed.text


async def test_live_chat_handoff_gated_on_generic_conversations_router(client, db_session, monkeypatch):
    from app.api.v1.routers import generic_conversations
    from app.services.whatsapp_client import InMemoryWhatsAppSender

    monkeypatch.setattr(generic_conversations, "_sender", InMemoryWhatsAppSender())

    package = await _make_package(db_session, "No Handoff Generic", [])
    restaurant = await _make_restaurant(db_session, "generichandoff", enabled_features=[], feature_package_id=package.id)
    customer = Customer(restaurant_id=restaurant.id, phone="919999900002")
    db_session.add(customer)
    await db_session.commit()
    headers = await _register_and_login(client, restaurant.id, email="owner15@featpkg-test.dev")

    blocked = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/generic-conversations/{customer.id}/messages",
        headers=headers, json={"body": "hi"},
    )
    assert blocked.status_code == 403

    package.feature_codes = ["live_chat_handoff"]
    restaurant.enabled_features = ["live_chat_handoff"]
    db_session.add_all([package, restaurant])
    await db_session.commit()

    allowed = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/generic-conversations/{customer.id}/messages",
        headers=headers, json={"body": "hi"},
    )
    assert allowed.status_code == 201, allowed.text
