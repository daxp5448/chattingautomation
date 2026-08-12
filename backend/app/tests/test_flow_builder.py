"""Proof for Phase 2, Item 3: Drag & Drop Flow Builder -- the new auto-advancing step
types (condition/delay/api_call/ai_response), the hop-cap fail-safe, human handoff
(pause + live-chat + resume), the flow-shape graph validator, and -- the highest-risk new
code -- the SSRF protections on API_CALL, including a DNS-rebinding-style simulation
proving validation is bound to the actual connected address, not a separate pre-check.

Backward compatibility with every pre-existing niche (all 5 old step types, none
auto-advancing) is proven by the full existing suite staying green, not duplicated here --
see the approved plan's Testing Plan.
"""

import itertools
import json
import socket

import httpcore
import httpx
import pytest
from httpcore._backends.anyio import AnyIOBackend
from sqlalchemy import select

import app.services.generic_flow_engine as generic_flow_engine
from app.core.security import encrypt_secret
from app.models.api_endpoint import ApiEndpoint
from app.models.customer import Customer
from app.models.enums import EngagementType
from app.models.flow_definition import FlowDefinition
from app.models.generic_conversation_state import GenericConversationState
from app.models.restaurant import Restaurant
from app.services import api_endpoint_client
from app.services.flow_shape_validation import FlowShapeError, validate_flow_graph
from app.services.generic_flow_engine import GenericInteraction, process_inbound_message
from app.services.whatsapp_client import InMemoryWhatsAppSender

PHONE_NUMBER_ID = "FLOWBUILDER_TEST_PHONE_NUMBER_ID"
CUSTOMER_PHONE = "919000011111"

_wamid_counter = itertools.count(1)


def _next_wamid() -> str:
    return f"wamid.flowbuilder.test.{next(_wamid_counter)}"


async def _make_restaurant(db_session, slug: str) -> Restaurant:
    restaurant = Restaurant(
        name=f"Flow Builder Test {slug}", slug=f"flow-builder-test-{slug}",
        whatsapp_phone_number_id=f"{PHONE_NUMBER_ID}_{slug}",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
    )
    db_session.add(restaurant)
    await db_session.flush()
    return restaurant


async def _setup_flow(db_session, restaurant, steps, entry_step_id="welcome", context=None):
    customer = Customer(restaurant_id=restaurant.id, phone=CUSTOMER_PHONE)
    db_session.add(customer)
    await db_session.flush()
    flow = FlowDefinition(
        restaurant_id=restaurant.id, niche_code="test", action_type=EngagementType.INQUIRY,
        entry_step_id=entry_step_id, steps=steps,
    )
    db_session.add(flow)
    state = GenericConversationState(
        restaurant_id=restaurant.id, customer_id=customer.id, current_step=entry_step_id, context=context or {}
    )
    db_session.add(state)
    await db_session.commit()
    return customer, flow, state


def _welcome_step(routes: dict) -> dict:
    return {
        "step_id": "welcome", "type": "menu_select", "prompt": "Hi! Pick one:", "buttons_from": "static",
        "static_options": [{"id": rid, "title": rid} for rid in routes], "routes": routes, "back_target": None,
    }


# --- CONDITION -----------------------------------------------------------------------------


async def test_condition_step_branches_true(db_session):
    restaurant = await _make_restaurant(db_session, "condtrue")
    steps = [
        _welcome_step({"welcome:go": "check"}),
        {"step_id": "check", "type": "condition", "condition": {"context_key": "vip", "operator": "equals", "value": True}, "then_step": "vip_msg", "else_step": "regular_msg"},
        {"step_id": "vip_msg", "type": "message", "prompt": "Welcome VIP!"},
        {"step_id": "regular_msg", "type": "message", "prompt": "Welcome regular!"},
    ]
    customer, _, _ = await _setup_flow(db_session, restaurant, steps, context={"vip": True})

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "VIP" in sender.sent[-1].payload["text"]["body"]


async def test_condition_step_branches_false(db_session):
    restaurant = await _make_restaurant(db_session, "condfalse")
    steps = [
        _welcome_step({"welcome:go": "check"}),
        {"step_id": "check", "type": "condition", "condition": {"context_key": "vip", "operator": "equals", "value": True}, "then_step": "vip_msg", "else_step": "regular_msg"},
        {"step_id": "vip_msg", "type": "message", "prompt": "Welcome VIP!"},
        {"step_id": "regular_msg", "type": "message", "prompt": "Welcome regular!"},
    ]
    await _setup_flow(db_session, restaurant, steps, context={"vip": False})

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "regular" in sender.sent[-1].payload["text"]["body"].lower()


async def test_condition_greater_than_operator(db_session):
    restaurant = await _make_restaurant(db_session, "condgt")
    steps = [
        _welcome_step({"welcome:go": "check"}),
        {"step_id": "check", "type": "condition", "condition": {"context_key": "cart_total", "operator": "greater_than", "value": 500}, "then_step": "big_msg", "else_step": "small_msg"},
        {"step_id": "big_msg", "type": "message", "prompt": "Big order!"},
        {"step_id": "small_msg", "type": "message", "prompt": "Small order"},
    ]
    await _setup_flow(db_session, restaurant, steps, context={"cart_total": "750"})

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "Big" in sender.sent[-1].payload["text"]["body"]


# --- DELAY ---------------------------------------------------------------------------------


async def test_delay_step_auto_advances(db_session):
    restaurant = await _make_restaurant(db_session, "delay")
    steps = [
        _welcome_step({"welcome:go": "wait"}),
        {"step_id": "wait", "type": "delay", "delay_seconds": 0.01, "next": "after_wait"},
        {"step_id": "after_wait", "type": "message", "prompt": "Done waiting!"},
    ]
    await _setup_flow(db_session, restaurant, steps)

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "Done waiting" in sender.sent[-1].payload["text"]["body"]


# --- AI_RESPONSE placeholder -----------------------------------------------------------------


async def test_ai_response_placeholder_sends_fallback_and_continues(db_session):
    restaurant = await _make_restaurant(db_session, "airesp")
    steps = [
        _welcome_step({"welcome:go": "ask_ai"}),
        {"step_id": "ask_ai", "type": "ai_response", "next": "after_ai"},
        {"step_id": "after_ai", "type": "message", "prompt": "After AI"},
    ]
    await _setup_flow(db_session, restaurant, steps)

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    bodies = [m.payload["text"]["body"] for m in sender.sent]
    assert any("configured" in b.lower() for b in bodies)
    assert "After AI" in bodies[-1]


# --- hop cap fail-safe -----------------------------------------------------------------------


async def test_auto_advance_hop_cap_fails_safely_on_a_cycle(db_session):
    restaurant = await _make_restaurant(db_session, "hopcap")
    loop_steps = [
        {"step_id": f"loop{i}", "type": "delay", "delay_seconds": 0, "next": f"loop{(i + 1) % 3}"} for i in range(3)
    ]
    steps = [_welcome_step({"welcome:go": "loop0"}), *loop_steps]
    await _setup_flow(db_session, restaurant, steps)

    sender = InMemoryWhatsAppSender()
    # Must return (not hang/crash) even though loop0->loop1->loop2->loop0->... never
    # reaches an interactive/terminal step -- the _MAX_AUTO_ADVANCE_HOPS cap bounds it.
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "something went wrong" in sender.sent[-1].payload["text"]["body"].lower()


# --- API_CALL step integration (engine level -- call_api_endpoint itself tested below) ------


async def test_api_call_step_captures_response_and_continues(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "apicallstep")
    steps = [
        _welcome_step({"welcome:go": "call_api"}),
        {"step_id": "call_api", "type": "api_call", "endpoint_id": "fake-endpoint-id", "capture_key": "api_result", "next": "done"},
        {"step_id": "done", "type": "message", "prompt": "Done"},
    ]
    customer, _, state = await _setup_flow(db_session, restaurant, steps)

    async def fake_call(session, endpoint_id, context, timeout_override=None):
        assert endpoint_id == "fake-endpoint-id"
        return {"status": "ok"}

    monkeypatch.setattr("app.services.api_endpoint_client.call_api_endpoint", fake_call)

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "Done" in sender.sent[-1].payload["text"]["body"]
    customer_id = customer.id  # captured before expire_all() below
    db_session.expire_all()
    refreshed = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_id))).scalar_one()
    assert refreshed.context["api_result"] == {"status": "ok"}


async def test_api_call_step_failure_does_not_stall_the_conversation(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "apicallfail")
    steps = [
        _welcome_step({"welcome:go": "call_api"}),
        {"step_id": "call_api", "type": "api_call", "endpoint_id": "fake-endpoint-id", "next": "done"},
        {"step_id": "done", "type": "message", "prompt": "Done"},
    ]
    await _setup_flow(db_session, restaurant, steps)

    async def failing_call(session, endpoint_id, context, timeout_override=None):
        raise RuntimeError("endpoint down")

    monkeypatch.setattr("app.services.api_endpoint_client.call_api_endpoint", failing_call)

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:go", text="Go"), wa_message_id=_next_wamid())

    assert "Done" in sender.sent[-1].payload["text"]["body"]  # continues to `next` regardless


# --- HUMAN_HANDOFF ---------------------------------------------------------------------------


async def test_human_handoff_pauses_automation_and_broadcasts(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "handoff")
    steps = [
        _welcome_step({"welcome:help": "handoff"}),
        {"step_id": "handoff", "type": "human_handoff", "message": "Connecting you now"},
    ]
    customer, _, _ = await _setup_flow(db_session, restaurant, steps)

    broadcasts = []

    async def fake_broadcast(restaurant_id, event):
        broadcasts.append(event)

    monkeypatch.setattr(generic_flow_engine.ws_manager, "broadcast", fake_broadcast)

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:help", text="Help"), wa_message_id=_next_wamid())

    assert "Connecting you now" in sender.sent[-1].payload["text"]["body"]
    assert any(e["type"] == "generic_handover" for e in broadcasts)

    customer_id = customer.id
    # populate_existing=True (not expire_all()) so this refreshes the identity-mapped
    # state object directly from the query results -- expire_all() would also expire
    # `restaurant`/`customer`, and the SECOND process_inbound_message call below still
    # needs to touch their attributes (e.g. restaurant.id), which would otherwise trigger
    # a sync lazy-reload outside the async greenlet context (MissingGreenlet).
    state = (
        await db_session.execute(
            select(GenericConversationState).where(GenericConversationState.customer_id == customer_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert state.is_handed_over is True
    assert state.current_step == "handoff"

    # A further inbound message must NOT advance the flow -- only log + broadcast.
    sent_before = len(sender.sent)
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="text", text="hello?"), wa_message_id=_next_wamid())
    assert len(sender.sent) == sent_before  # no automated reply sent
    assert any(e["type"] == "generic_inbound_while_handed_off" for e in broadcasts)

    state_after = (
        await db_session.execute(
            select(GenericConversationState).where(GenericConversationState.customer_id == customer_id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert state_after.current_step == "handoff"  # unchanged -- never advanced


# --- generic live-chat router ------------------------------------------------------------------


async def _register_and_login(client, restaurant_id, role="owner", email="owner@flowbuilder-test.dev"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": str(restaurant_id)},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_generic_live_chat_list_reply_and_resume(client, db_session):
    restaurant = await _make_restaurant(db_session, "livechat")
    steps = [
        _welcome_step({"welcome:help": "handoff"}),
        {"step_id": "handoff", "type": "human_handoff", "message": "Connecting you now"},
    ]
    customer, _, _ = await _setup_flow(db_session, restaurant, steps)

    sender = InMemoryWhatsAppSender()
    await process_inbound_message(db_session, sender, restaurant, CUSTOMER_PHONE, GenericInteraction(kind="button_reply", reply_id="welcome:help", text="Help"), wa_message_id=_next_wamid())

    headers = await _register_and_login(client, restaurant.id)

    listed = await client.get(f"/api/v1/restaurants/{restaurant.id}/generic-conversations", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["customer_id"] == str(customer.id)

    messages = await client.get(f"/api/v1/restaurants/{restaurant.id}/generic-conversations/{customer.id}/messages", headers=headers)
    assert messages.status_code == 200
    assert len(messages.json()) >= 2  # inbound tap + outbound handoff message

    replied = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/generic-conversations/{customer.id}/messages",
        json={"body": "Hi, how can I help?"}, headers=headers,
    )
    assert replied.status_code == 201, replied.text
    assert replied.json()["sent_by"] == "staff"

    resumed = await client.post(f"/api/v1/restaurants/{restaurant.id}/generic-conversations/{customer.id}/resume", headers=headers)
    assert resumed.status_code == 204

    customer_id = customer.id  # captured before expire_all() below
    db_session.expire_all()
    state = (await db_session.execute(select(GenericConversationState).where(GenericConversationState.customer_id == customer_id))).scalar_one()
    assert state.is_handed_over is False
    assert state.current_step == "welcome"


# --- flow_shape_validation.validate_flow_graph -----------------------------------------------


def test_validate_flow_graph_rejects_dangling_next():
    with pytest.raises(FlowShapeError, match="next"):
        validate_flow_graph([{"step_id": "a", "type": "message", "next": "nowhere"}])


def test_validate_flow_graph_rejects_dangling_condition_targets():
    with pytest.raises(FlowShapeError):
        validate_flow_graph([
            {"step_id": "a", "type": "condition", "condition": {"context_key": "x", "operator": "equals", "value": 1}, "then_step": "nowhere", "else_step": "b"},
            {"step_id": "b", "type": "message"},
        ])


def test_validate_flow_graph_rejects_delay_over_cap():
    with pytest.raises(FlowShapeError, match="exceeds"):
        validate_flow_graph([{"step_id": "a", "type": "delay", "delay_seconds": 999, "next": "a"}])


def test_validate_flow_graph_rejects_auto_advance_cycle():
    with pytest.raises(FlowShapeError, match="cycles"):
        validate_flow_graph([
            {"step_id": "a", "type": "delay", "delay_seconds": 0, "next": "b"},
            {"step_id": "b", "type": "delay", "delay_seconds": 0, "next": "a"},
        ])


def test_validate_flow_graph_accepts_well_formed_graph():
    validate_flow_graph([
        {"step_id": "welcome", "type": "menu_select", "routes": {"welcome:go": "check"}},
        {"step_id": "check", "type": "condition", "condition": {"context_key": "x", "operator": "equals", "value": 1}, "then_step": "done", "else_step": "done"},
        {"step_id": "done", "type": "message"},
    ])


# --- SSRF protection (the highest-risk new code) -----------------------------------------------


def test_is_globally_routable_blocks_private_and_metadata_ips():
    assert api_endpoint_client._is_globally_routable("127.0.0.1") is False
    assert api_endpoint_client._is_globally_routable("10.0.0.5") is False
    assert api_endpoint_client._is_globally_routable("169.254.169.254") is False  # cloud metadata
    assert api_endpoint_client._is_globally_routable("::1") is False
    assert api_endpoint_client._is_globally_routable("8.8.8.8") is True


async def test_ssrf_backend_rejects_direct_private_ip():
    backend = api_endpoint_client._SSRFSafeBackend()
    with pytest.raises(httpcore.ConnectError, match="non-public"):
        await backend.connect_tcp("127.0.0.1", 80)


async def test_ssrf_backend_rejects_dns_rebinding_to_private_ip(monkeypatch):
    """Simulates DNS rebinding: an approved-looking hostname resolves to a private IP.
    Proves validation is bound to whatever address resolution ACTUALLY returns, not a
    separate, earlier, spoofable pre-check."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(api_endpoint_client.socket, "getaddrinfo", fake_getaddrinfo)
    backend = api_endpoint_client._SSRFSafeBackend()
    with pytest.raises(httpcore.ConnectError, match="non-public"):
        await backend.connect_tcp("looks-legit.example.com", 443)


async def test_ssrf_backend_connects_to_validated_ip_literal_not_hostname(monkeypatch):
    """Proves the actual TCP connect targets the VALIDATED IP, not a second hostname
    resolution -- the core of closing the TOCTOU gap."""
    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(api_endpoint_client.socket, "getaddrinfo", fake_getaddrinfo)

    called_with = {}

    async def fake_super_connect(self, host, port, timeout=None, local_address=None, socket_options=None):
        called_with["host"] = host
        raise RuntimeError("stopped before a real network call")

    monkeypatch.setattr(AnyIOBackend, "connect_tcp", fake_super_connect)
    backend = api_endpoint_client._SSRFSafeBackend()
    with pytest.raises(RuntimeError, match="stopped before"):
        await backend.connect_tcp("legit.example.com", 443)
    assert called_with["host"] == "93.184.216.34"


async def test_call_api_endpoint_sends_only_capturable_context_keys(db_session, monkeypatch):
    endpoint = ApiEndpoint(
        name="Test", url="https://example.com/webhook", method="POST",
        capturable_context_keys=["customer_name"], timeout_seconds=5.0, response_size_cap_bytes=1024, is_active=True,
    )
    db_session.add(endpoint)
    await db_session.commit()

    captured_body = {}

    def handler(request):
        captured_body.update(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    def fake_build_client(timeout_seconds):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout_seconds)

    monkeypatch.setattr(api_endpoint_client, "_build_ssrf_safe_client", fake_build_client)

    result = await api_endpoint_client.call_api_endpoint(db_session, str(endpoint.id), {"customer_name": "Asha", "secret": "nope"})
    assert result == {"ok": True}
    assert captured_body == {"context": {"customer_name": "Asha"}}  # "secret" never sent


async def test_call_api_endpoint_enforces_response_size_cap(db_session, monkeypatch):
    endpoint = ApiEndpoint(name="Big", url="https://example.com/big", method="GET", capturable_context_keys=[], timeout_seconds=5.0, response_size_cap_bytes=10, is_active=True)
    db_session.add(endpoint)
    await db_session.commit()

    def handler(request):
        return httpx.Response(200, content=b"x" * 1000)

    monkeypatch.setattr(api_endpoint_client, "_build_ssrf_safe_client", lambda timeout_seconds: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout_seconds))

    with pytest.raises(ValueError, match="exceeded"):
        await api_endpoint_client.call_api_endpoint(db_session, str(endpoint.id), {})


async def test_call_api_endpoint_rejects_inactive_endpoint(db_session):
    endpoint = ApiEndpoint(name="Off", url="https://example.com", method="GET", is_active=False)
    db_session.add(endpoint)
    await db_session.commit()
    with pytest.raises(ValueError, match="missing or inactive"):
        await api_endpoint_client.call_api_endpoint(db_session, str(endpoint.id), {})


# --- api-endpoints router (Super Admin CRUD) ----------------------------------------------------


async def test_api_endpoint_crud_requires_super_admin(client, db_session):
    restaurant = await _make_restaurant(db_session, "endpointcrud")
    await db_session.commit()  # _make_restaurant only flushes; client hits a separate connection
    headers = await _register_and_login(client, restaurant.id)  # owner, not super_admin

    resp = await client.post(
        "/api/v1/api-endpoints", headers=headers,
        json={"name": "Test", "url": "https://example.com", "method": "POST"},
    )
    assert resp.status_code == 403


async def test_api_endpoint_list_open_to_any_authenticated_user(client, db_session):
    restaurant = await _make_restaurant(db_session, "endpointlist")
    await db_session.commit()  # _make_restaurant only flushes; client hits a separate connection
    headers = await _register_and_login(client, restaurant.id)
    resp = await client.get("/api/v1/api-endpoints", headers=headers)
    assert resp.status_code == 200
