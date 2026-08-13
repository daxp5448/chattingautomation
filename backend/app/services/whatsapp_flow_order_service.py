"""Data-exchange logic for the shared "order" WhatsApp Flow -- serves all 5 order-type
niches (restaurant, jewellers, retail, grocery, electronics) identically; only the
CatalogCategory/CatalogItem *content* differs per restaurant, never the screen layout (see
the approved "WhatsApp Flows for Ordering" plan, §2C -- one JSON authored once, matching
this project's own "the niche differs in content, never in code" instinct).

Screen flow: CATEGORY_SCREEN -> ITEM_SCREEN -> REVIEW_SCREEN (loops back to
CATEGORY_SCREEN for "add another item", or forward to SUCCESS_SCREEN on "place order") ->
SUCCESS_SCREEN (terminal).

Cart state is NOT threaded through the Flow's own `data` between screens (that would mean
re-echoing a growing JSON blob every round-trip) -- it's kept in the customer's real,
already-persisted GenericConversationState.context["cart"], the exact same field the chat-
based flow engine already uses. This means the final "place order" action can call
generic_flow_engine.py's own _Engine._create_engagement directly: the exact same order-
creation, stock-decrement, and confirmation-message logic the chat flow already uses and
already has test coverage for, not a second implementation of "what is an order."
"""

import uuid
from typing import Any

from app.repositories.catalog_repository import CatalogCategoryRepository, CatalogItemRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.generic_conversation_repository import GenericConversationStateRepository
from app.services.generic_flow_engine import _Engine, _price_label
from app.services.whatsapp_client import WhatsAppSender

ORDER_FLOW_JSON: dict[str, Any] = {
    "version": "5.1",
    "data_api_version": "3.0",
    # Required whenever screen transitions are decided by a data_exchange response rather
    # than a static "navigate" action -- Meta's validator can't infer connectivity from a
    # fully server-decided graph, so it must be declared explicitly (confirmed directly
    # against the real validator: omitting this produced INVALID_ROUTING_MODEL).
    # Declared as an acyclic DAG (confirmed against the real validator: a REVIEW_SCREEN ->
    # CATEGORY_SCREEN back-edge for the "add another item" loop made every screen have an
    # inbound edge, and the validator rejected that with "No entry screen found" -- it
    # needs one screen with zero inbound edges to treat as the entry point). The actual
    # runtime "add another item" loop-back still works: routing_model only affects Meta's
    # static graph validation, not what screen name a data_exchange response is allowed to
    # return -- see handle_data_exchange's "add_more" branch, verified against a real Flow
    # session once publishing is unblocked (see the manual spike's known integrity block).
    "routing_model": {
        "CATEGORY_SCREEN": ["ITEM_SCREEN"],
        "ITEM_SCREEN": ["REVIEW_SCREEN"],
        "REVIEW_SCREEN": ["SUCCESS_SCREEN"],
        "SUCCESS_SCREEN": [],
    },
    "screens": [
        {
            "id": "CATEGORY_SCREEN",
            "title": "Browse",
            "data": {
                "categories": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"}}},
                    "__example__": [{"id": "cat-1", "title": "Starters"}],
                },
            },
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextHeading", "text": "What would you like to browse?"},
                    {"type": "RadioButtonsGroup", "name": "category_id", "label": "Category", "data-source": "${data.categories}", "required": True},
                    {
                        "type": "Footer", "label": "Next",
                        "on-click-action": {"name": "data_exchange", "payload": {"action": "select_category", "category_id": "${form.category_id}"}},
                    },
                ],
            },
        },
        {
            "id": "ITEM_SCREEN",
            "title": "Pick an item",
            "data": {
                "items": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"}}},
                    "__example__": [{"id": "item-1", "title": "Paneer Tikka", "description": "250"}],
                },
            },
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "Dropdown", "name": "item_id", "label": "Item", "data-source": "${data.items}", "required": True},
                    {"type": "TextInput", "name": "quantity", "label": "Quantity", "input-type": "number", "required": True, "init-value": "1"},
                    {
                        "type": "Footer", "label": "Add to cart",
                        "on-click-action": {"name": "data_exchange", "payload": {"action": "add_to_cart", "item_id": "${form.item_id}", "quantity": "${form.quantity}"}},
                    },
                ],
            },
        },
        {
            "id": "REVIEW_SCREEN",
            "title": "Review & Checkout",
            "data": {
                "cart_summary": {"type": "string", "__example__": "Paneer Tikka x1 - 250"},
                "cart_total": {"type": "string", "__example__": "250"},
            },
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextBody", "text": "${data.cart_summary}"},
                    {"type": "TextBody", "text": "Total: ${data.cart_total}"},
                    {"type": "TextArea", "name": "address", "label": "Delivery address (optional)", "required": False},
                    {
                        "type": "RadioButtonsGroup", "name": "next_action", "label": "What next?", "required": True,
                        "data-source": [
                            {"id": "add_more", "title": "➕ Add another item"},
                            {"id": "place_order", "title": "✅ Place order"},
                        ],
                    },
                    {
                        "type": "Footer", "label": "Continue",
                        "on-click-action": {"name": "data_exchange", "payload": {"action": "${form.next_action}", "address": "${form.address}"}},
                    },
                ],
            },
        },
        {
            "id": "SUCCESS_SCREEN",
            "title": "Order placed!",
            "terminal": True,
            "data": {"confirmation_message": {"type": "string", "__example__": "Order #ABC123 confirmed!"}},
            "layout": {
                "type": "SingleColumnLayout",
                "children": [
                    {"type": "TextHeading", "text": "\U0001f389 Order placed!"},
                    {"type": "TextBody", "text": "${data.confirmation_message}"},
                    {"type": "Footer", "label": "Done", "on-click-action": {"name": "complete", "payload": {}}},
                ],
            },
        },
    ],
}


async def initial_screen_data(session, restaurant) -> dict[str, Any]:
    """Populates CATEGORY_SCREEN's data at SEND time (flow_action="navigate") -- the very
    first screen doesn't need a data_exchange round-trip since the categories are already
    known when the outbound message is built.
    """
    categories = await CatalogCategoryRepository(session).list_visible(restaurant.id)
    return {"categories": [{"id": str(c.id), "title": c.name} for c in categories]}


def _cart_summary(cart: list[dict]) -> tuple[str, str]:
    lines = [f"{line['name']} x{line['qty']} - {line['price'] * line['qty']:.0f}" for line in cart]
    total = sum(line["price"] * line["qty"] for line in cart)
    return "\n".join(lines) or "(empty)", f"{total:.0f}"


async def handle_data_exchange(session, sender: WhatsAppSender, restaurant, flow_token: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`flow_token` is the customer's phone number (set when the Flow message was sent --
    see generic_flow_engine.py's send_whatsapp_flow step), letting this resolve the same
    Customer/GenericConversationState row the chat engine itself would use for this
    customer, without any new session/token table.
    """
    customer_repo = CustomerRepository(session)
    state_repo = GenericConversationStateRepository(session)
    customer = await customer_repo.get_or_create(restaurant.id, flow_token)
    state = await state_repo.get_by_customer(customer.id, restaurant.id)
    if state is None:
        from app.models.generic_conversation_state import GenericConversationState
        state = GenericConversationState(restaurant_id=restaurant.id, customer_id=customer.id, current_step="welcome", context={})
        session.add(state)
        await session.flush()

    action = payload.get("action")
    data = payload

    if action == "select_category":
        items = await CatalogItemRepository(session).list_by_category(uuid.UUID(data["category_id"]), restaurant.id)
        return {
            "screen": "ITEM_SCREEN",
            "data": {"items": [{"id": str(i.id), "title": i.name, "description": _price_label(restaurant, i, include_attributes=True)} for i in items]},
        }

    if action == "add_to_cart":
        item = await CatalogItemRepository(session).get(uuid.UUID(data["item_id"]), restaurant.id)
        qty = max(int(data.get("quantity") or 1), 1)
        cart = state.context.get("cart", [])
        cart.append({"item_id": str(item.id), "name": item.name, "price": float(item.price or 0), "qty": qty})
        state.context["cart"] = cart
        await session.commit()
        summary, total = _cart_summary(cart)
        return {"screen": "REVIEW_SCREEN", "data": {"cart_summary": summary, "cart_total": total}}

    if action == "add_more":
        categories = await CatalogCategoryRepository(session).list_visible(restaurant.id)
        return {"screen": "CATEGORY_SCREEN", "data": {"categories": [{"id": str(c.id), "title": c.name} for c in categories]}}

    if action == "place_order":
        state.context["delivery_address"] = data.get("address") or None
        engine = _Engine(session, sender)
        ok = await engine._create_engagement(restaurant, customer, state, flow_token, state.context)
        if not ok:
            summary, total = _cart_summary(state.context.get("cart", []))
            return {"screen": "REVIEW_SCREEN", "data": {"cart_summary": summary, "cart_total": total}}
        return {"screen": "SUCCESS_SCREEN", "data": {"confirmation_message": "Your order has been placed -- we'll confirm shortly on WhatsApp."}}

    raise ValueError(f"Unknown Flow data_exchange action: {action!r}")
