"""Proof for generic_flow_engine.py's send_whatsapp_flow step type (see the approved
"WhatsApp Flows for Ordering" plan) -- gated entirely on restaurant.whatsapp_flow_order_id,
so a niche can route to this step unconditionally without a per-business branch in its own
flow graph. Drives _Engine._render_step directly (not through the full webhook chain) since
no niche's default_flow_steps references this step type yet -- deliberately not wired into
any live niche flow in this pass, since publishing is currently blocked by Meta's own
account-verification gate on the test WABA (see the manual spike), so a real end-to-end
send-and-interact test isn't possible yet; this proves the engine-side rendering logic is
correct and ready for that once unblocked.
"""

from app.core.security import encrypt_secret
from app.models.generic_conversation_state import GenericConversationState
from app.repositories.customer_repository import CustomerRepository
from app.services.generic_flow_engine import _Engine
from app.services.whatsapp_client import InMemoryWhatsAppSender
from app.tests.test_niche_jewellers import jewellers_tenant

CUSTOMER_PHONE = "919876511111"


def _step(**overrides) -> dict:
    base = {
        "step_id": "flow_order", "type": "send_whatsapp_flow", "prompt": "Ready to order?",
        "cta": "Order Now", "next": "category_select", "back_target": None,
    }
    base.update(overrides)
    return base


async def _customer_and_state(db_session, restaurant):
    customer = await CustomerRepository(db_session).get_or_create(restaurant.id, CUSTOMER_PHONE)
    state = GenericConversationState(restaurant_id=restaurant.id, customer_id=customer.id, current_step="welcome", context={})
    db_session.add(state)
    await db_session.flush()
    return customer, state


async def test_falls_back_to_next_step_when_flow_ordering_not_enabled(db_session, jewellers_tenant):
    restaurant = jewellers_tenant
    assert restaurant.whatsapp_flow_order_id is None
    sender = InMemoryWhatsAppSender()
    engine = _Engine(db_session, sender)
    customer, state = await _customer_and_state(db_session, restaurant)

    steps_by_id = {
        "flow_order": _step(),
        "category_select": {"step_id": "category_select", "type": "menu_select", "prompt": "Pick a category", "buttons_from": "categories", "back_target": None},
    }
    await engine._render_step(restaurant, customer, state, CUSTOMER_PHONE, steps_by_id["flow_order"], steps_by_id)

    # No interactive.type=="flow" message sent -- it fell back to rendering
    # category_select instead (a real interactive list/button message).
    assert not any(m.payload.get("interactive", {}).get("type") == "flow" for m in sender.sent)
    assert any(m.payload.get("type") == "interactive" for m in sender.sent)


async def test_sends_flow_message_with_live_catalog_data_when_enabled(db_session, jewellers_tenant):
    restaurant = jewellers_tenant
    restaurant.whatsapp_flow_order_id = "meta-flow-id-abc"
    restaurant.whatsapp_flow_private_key_encrypted = encrypt_secret("irrelevant-for-this-test")
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    engine = _Engine(db_session, sender)
    customer, state = await _customer_and_state(db_session, restaurant)
    steps_by_id = {"flow_order": _step()}

    await engine._render_step(restaurant, customer, state, CUSTOMER_PHONE, steps_by_id["flow_order"], steps_by_id)

    flow_messages = [m for m in sender.sent if m.payload.get("interactive", {}).get("type") == "flow"]
    assert len(flow_messages) == 1
    params = flow_messages[0].payload["interactive"]["action"]["parameters"]
    assert params["flow_id"] == "meta-flow-id-abc"
    assert params["flow_token"] == CUSTOMER_PHONE
    assert params["flow_cta"] == "Order Now"
    assert params["flow_action"] == "navigate"
    assert params["flow_action_payload"]["screen"] == "CATEGORY_SCREEN"
    category_titles = {c["title"] for c in params["flow_action_payload"]["data"]["categories"]}
    assert {"Gold Jewellery", "Diamond Jewellery", "Silver Jewellery", "Bridal Collection"} <= category_titles
