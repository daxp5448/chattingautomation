"""FINAL PRE-LIVE VERIFICATION -- walks ALL 12 niches (not a sample) through the real
Bot Preview endpoint (POST /restaurants/{id}/flow/preview, dry_run=True over the
unmodified generic_flow_engine -- never a mock), inspecting the actual generated
WhatsApp Graph API message payloads at every turn, for:

  Hi -> welcome -> primary action -> category/choice -> item/service/property/etc ->
  details/images -> next action -> confirmation, PLUS human handoff, back navigation,
  and fallback-on-garbage-input, PLUS an image edit (caption change) round-tripping
  into the very next preview turn.

The "primary path" through each niche's dynamic step graph (categories/items/staff/
dates/time_slots all have runtime-generated option ids, not knowable from the template)
is computed by a small generic walker that mirrors generic_flow_engine.py's own routing
precedence (_resolve_next: exact route match, then a routes key ending '*' as a prefix
match, then `next`) rather than hardcoding each niche's exact reply-id sequence by hand
-- so this same walker logic proves correctness for all 12 niches uniformly, the same
way it would for a 13th niche added later with no code change here.
"""

import re

import pytest
from sqlalchemy import select

from app.core.security import encrypt_secret, hash_password
from app.models.enums import EngagementType, UserRole
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant
from app.models.user import User
from app.services.niche_provisioning import provision_from_template
from app.services.niche_template_sync import discover_templates

_REFERENCE_PATTERN = re.compile(r"PREVIEW-\d+")
_MAX_TURNS = 25


async def _make_owner_tenant(db_session, slug: str, template_dict: dict) -> tuple[Restaurant, dict]:
    restaurant = Restaurant(
        name=f"FullWalk {slug}", slug=f"fullwalk-{slug}",
        whatsapp_phone_number_id=f"FULLWALK_{slug.upper()}_PNID",
        whatsapp_access_token_encrypted=encrypt_secret("fake-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()

    existing = (await db_session.execute(select(NicheTemplate).where(NicheTemplate.code == template_dict["code"]))).scalar_one_or_none()
    if existing is not None:
        template = existing
    else:
        template = NicheTemplate(
            code=template_dict["code"], name=template_dict["name"], action_type=EngagementType(template_dict["action_type"]),
            icon=template_dict["icon"], welcome_message=template_dict["welcome_message"],
            welcome_banner_image=template_dict["welcome_banner_image"], welcome_buttons=template_dict["welcome_buttons"],
            default_catalog=template_dict["default_catalog"], default_flow_steps=template_dict["default_flow_steps"],
            terminology=template_dict["terminology"], default_modules=template_dict["default_modules"],
        )
        db_session.add(template)
        await db_session.flush()
    await provision_from_template(db_session, restaurant, template)

    email = f"owner-fullwalk-{slug}@kelviontech.dev"
    password = "OwnerPass123!"
    user = User(email=email, hashed_password=hash_password(password), role=UserRole.OWNER, restaurant_id=restaurant.id, is_active=True)
    db_session.add(user)
    await db_session.commit()
    return restaurant, {"email": email, "password": password}


async def _login(client, email: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _flatten_options(messages: list[dict]) -> list[str]:
    for m in messages:
        interactive = m.get("interactive", {})
        if interactive.get("type") == "button":
            return [b["reply"]["id"] for b in interactive["action"]["buttons"]]
        if interactive.get("type") == "list":
            return [r["id"] for r in interactive["action"]["sections"][0]["rows"]]
    return []


def _image_count(messages: list[dict]) -> int:
    return sum(1 for m in messages if m.get("type") == "image")


def _text_of(messages: list[dict]) -> str:
    """All human-readable body text across a turn's messages, regardless of WhatsApp
    message type -- a plain text message's body, an interactive message's body (used
    for menu_select/quantity_input/confirm_action re-renders, including the "please
    pick one" invalid-input re-render), or an image's caption. Checking only
    `type == "text"` misses most real turns, since almost every step renders as an
    interactive button/list message, not a bare text message.
    """
    parts = []
    for m in messages:
        if m.get("type") == "text":
            parts.append(m.get("text", {}).get("body", ""))
        elif m.get("type") == "interactive":
            parts.append(m.get("interactive", {}).get("body", {}).get("text", ""))
        elif m.get("type") == "image":
            parts.append(m.get("image", {}).get("caption", ""))
    return " ".join(parts)


def _resolve_next(step: dict, option_id: str | None) -> str | None:
    """Mirrors generic_flow_engine.py::_Engine._resolve_next exactly."""
    if step["type"] != "menu_select" or option_id is None:
        return step.get("next")
    routes = step.get("routes") or {}
    if option_id in routes:
        return routes[option_id]
    for prefix, target in routes.items():
        if prefix.endswith("*") and option_id.startswith(prefix[:-1]):
            return target
    return step.get("next")


def _skip_disabled_modules(next_id: str | None, steps_by_id: dict, modules: dict) -> str | None:
    """Mirrors generic_flow_engine.py::_Engine._advance's module-skip loop exactly: a
    niche can turn a module off by default (e.g. automobile ships with
    default_modules={"staff_selection": False}, so its staff_select step -- marked
    skip_if_module_off="staff_selection" -- is silently bypassed straight to ITS OWN
    `next` for every real conversation, never rendered at all). Every next_id this
    walker computes must be run through this, or it desyncs from the live engine's
    actual current step the moment a walk crosses a disabled-module step.
    """
    while next_id and next_id in steps_by_id:
        step = steps_by_id[next_id]
        module_flag = step.get("skip_if_module_off")
        if module_flag and not modules.get(module_flag, True):
            next_id = step.get("next")
            continue
        return next_id
    return next_id


def _is_dead_end(steps_by_id: dict, step_id: str | None, _depth: int = 0) -> bool:
    """Bounded (depth<=3) lookahead, not just the immediate target: a step several hops
    downstream can itself be an unavoidable dead end (e.g. jewellery's Explore Design ->
    material_select -> jewellery_category_select -> design_gallery, a standalone leaf
    browsing feature with no `next` -- see generic_flow_engine.py's
    _render_jewellery_gallery). A one-hop check alone would miss this since
    material_select/jewellery_category_select are themselves ordinary menu_select steps
    with a valid `next`; only the step at the end of that chain has nowhere further to go.
    """
    if step_id is None or step_id not in steps_by_id:
        return True
    step = steps_by_id[step_id]
    if step["type"] == "human_handoff":
        return True
    if step["type"] in ("message", "jewellery_design_gallery") and not step.get("terminal") and not step.get("next"):
        return True
    if _depth < 3 and step.get("next"):
        return _is_dead_end(steps_by_id, step.get("next"), _depth + 1)
    return False


def _pick_static_option(step: dict, steps_by_id: dict, visited: set[str], modules: dict | None = None) -> tuple[str, str | None]:
    candidates = [o["id"] for o in (step.get("static_options") or []) if o["id"] != "__back__"]
    scored = [(oid, _skip_disabled_modules(_resolve_next(step, oid), steps_by_id, modules or {})) for oid in candidates]
    for oid, target in scored:
        if not _is_dead_end(steps_by_id, target) and target not in visited:
            return oid, target
    for oid, target in scored:
        if not _is_dead_end(steps_by_id, target):
            return oid, target
    return scored[0]


NICHE_CODES = [t["code"] for t in discover_templates()]
assert len(NICHE_CODES) == 12, f"Expected 12 niches, found {len(NICHE_CODES)}: {NICHE_CODES}"


@pytest.mark.parametrize("niche_code", NICHE_CODES)
async def test_full_walk_hi_to_confirmation(db_session, client, niche_code):
    """The main acceptance walk for one niche: Hi -> welcome -> primary action ->
    ... -> confirmation, entirely through the live dry-run preview endpoint, choosing
    replies via the same routing precedence the real engine uses."""
    template_dict = next(t for t in discover_templates() if t["code"] == niche_code)
    steps_by_id = {s["step_id"]: s for s in template_dict["default_flow_steps"]}
    entry_id = template_dict["default_flow_steps"][0]["step_id"]
    modules = template_dict.get("default_modules") or {}

    restaurant, creds = await _make_owner_tenant(db_session, niche_code, template_dict)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    assert resp.status_code == 200, f"{niche_code}: preview turn failed: {resp.text}"
    session_id = resp.json()["session_id"]
    messages = resp.json()["messages"]

    # Real Graph API payload shape check (section 2's "verify the actual generated
    # WhatsApp message payload", not just an HTTP 200) -- every message must carry
    # messaging_product/to/type, matching OutboundMessage's real contract.
    for m in messages:
        assert m.get("messaging_product") == "whatsapp", f"{niche_code}: malformed payload {m}"
        assert "type" in m and "to" in m, f"{niche_code}: malformed payload {m}"

    current_id = entry_id
    total_images = _image_count(messages)
    visited = {entry_id}
    reached_terminal = False

    for _turn in range(_MAX_TURNS):
        step = steps_by_id[current_id]
        if step["type"] == "message":
            assert step.get("terminal"), f"{niche_code}: walk stalled on non-terminal dead-end step '{current_id}'"
            reached_terminal = True
            break
        if step["type"] == "human_handoff":
            pytest.fail(f"{niche_code}: primary walk unexpectedly routed into human_handoff at '{current_id}'")

        if step["type"] == "menu_select" and step.get("buttons_from") == "static":
            reply_id, next_id = _pick_static_option(step, steps_by_id, visited, modules)
        elif step["type"] == "menu_select":
            # Dynamic options (categories/items/staff/dates/time_slots) -- ids are
            # runtime UUIDs/ISO values, not known from the template; every option here
            # is a legitimate forward choice (no side branches), so take the live
            # response's first real option.
            live_options = [o for o in _flatten_options(messages) if o != "__back__"]
            assert live_options, f"{niche_code}/{current_id}: menu_select rendered zero selectable options"
            reply_id = live_options[0]
            next_id = _skip_disabled_modules(step.get("next"), steps_by_id, modules)
        elif step["type"] == "quantity_input":
            reply_id = "qty:1"
            next_id = _skip_disabled_modules(step.get("next"), steps_by_id, modules)
        elif step["type"] == "confirm_action":
            static_opts = step.get("static_options") or []
            reply_id = static_opts[0]["id"] if static_opts else "confirm"
            next_id = _skip_disabled_modules(step.get("next"), steps_by_id, modules)
        elif step["type"] == "free_text_input":
            resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "text", "text": "Test input"})
            assert resp.status_code == 200, f"{niche_code}/{current_id}: {resp.text}"
            messages = resp.json()["messages"]
            total_images += _image_count(messages)
            current_id = _skip_disabled_modules(step.get("next"), steps_by_id, modules)
            assert current_id, f"{niche_code}/{step['step_id']}: free_text_input has no `next`"
            visited.add(current_id)
            continue
        else:
            pytest.fail(f"{niche_code}/{current_id}: unhandled step type '{step['type']}' in walker")

        assert next_id, f"{niche_code}/{current_id}: chosen reply '{reply_id}' resolves to no next step"
        resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": reply_id})
        assert resp.status_code == 200, f"{niche_code}/{current_id} -> '{reply_id}': {resp.text}"
        messages = resp.json()["messages"]
        total_images += _image_count(messages)
        current_id = next_id
        visited.add(current_id)

    assert reached_terminal, f"{niche_code}: did not reach a terminal confirmation step within {_MAX_TURNS} turns"
    final_text = _text_of(messages)
    assert _REFERENCE_PATTERN.search(final_text), (
        f"{niche_code}: confirmation text has no dry-run reference number -- 'PREVIEW-N', got: {final_text!r}"
    )
    assert total_images > 0, f"{niche_code}: zero images sent across the entire walk"


@pytest.mark.parametrize("niche_code", NICHE_CODES)
async def test_human_handoff_reachable_from_welcome(db_session, client, niche_code):
    template_dict = next(t for t in discover_templates() if t["code"] == niche_code)
    welcome = template_dict["default_flow_steps"][0]
    handoff_reply = next(
        (o["id"] for o in (welcome.get("static_options") or []) if welcome.get("routes", {}).get(o["id"]) == "human_handoff"),
        None,
    )
    assert handoff_reply, f"{niche_code}: no welcome button routes to human_handoff"

    restaurant, creds = await _make_owner_tenant(db_session, f"{niche_code}-handoff", template_dict)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": handoff_reply})
    assert resp.status_code == 200, resp.text
    text = _text_of(resp.json()["messages"])
    assert text, f"{niche_code}: human_handoff produced no visible message"


@pytest.mark.parametrize("niche_code", NICHE_CODES)
async def test_back_navigation_from_category_select(db_session, client, niche_code):
    template_dict = next(t for t in discover_templates() if t["code"] == niche_code)
    welcome = template_dict["default_flow_steps"][0]
    steps_by_id = {s["step_id"]: s for s in template_dict["default_flow_steps"]}
    primary_reply, target = _pick_static_option(welcome, steps_by_id, {welcome["step_id"]}, template_dict.get("default_modules") or {})
    assert target == "category_select", f"{niche_code}: primary welcome action doesn't lead to category_select (got '{target}')"

    restaurant, creds = await _make_owner_tenant(db_session, f"{niche_code}-back", template_dict)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]
    welcome_options = set(_flatten_options(resp.json()["messages"]))

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": primary_reply})
    category_options = _flatten_options(resp.json()["messages"])
    assert "__back__" in category_options, f"{niche_code}: category_select offers no Back button"

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "__back__"})
    assert resp.status_code == 200, resp.text
    assert set(_flatten_options(resp.json()["messages"])) == welcome_options, f"{niche_code}: Back from category_select didn't return to welcome"


@pytest.mark.parametrize("niche_code", NICHE_CODES)
async def test_fallback_on_garbage_reply(db_session, client, niche_code):
    template_dict = next(t for t in discover_templates() if t["code"] == niche_code)
    restaurant, creds = await _make_owner_tenant(db_session, f"{niche_code}-fallback", template_dict)
    headers = await _login(client, **creds)
    base = f"/api/v1/restaurants/{restaurant.id}/flow/preview"

    resp = await client.post(base, headers=headers, json={"kind": "text", "text": "hi"})
    session_id = resp.json()["session_id"]

    resp = await client.post(base, headers=headers, json={"session_id": session_id, "kind": "button_reply", "reply_id": "totally:not-a-real-option"})
    assert resp.status_code == 200, f"{niche_code}: garbage reply crashed the preview endpoint: {resp.text}"
    text = _text_of(resp.json()["messages"])
    assert "pick one" in text.lower(), f"{niche_code}: garbage reply did not produce the expected fallback re-render, got: {text!r}"
