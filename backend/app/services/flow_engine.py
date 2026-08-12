import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.core.security import decrypt_secret
from app.core.ws_manager import manager as ws_manager
from app.models.branch import Branch
from app.models.category import Category
from app.models.conversation_state import ConversationState
from app.models.enums import BranchStatus, ConversationStep, FulfillmentType, MessageDirection, MessageSender, PaymentMethod
from app.models.message import Message
from app.models.order import Order
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.repositories.bot_config_repository import BotButtonRepository, BotMessageRepository
from app.repositories.branch_repository import BranchRepository
from app.repositories.coupon_repository import CouponRedemptionRepository, CouponRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.faq_repository import FaqRepository
from app.repositories.loyalty_repository import LoyaltyTransactionRepository
from app.repositories.menu_repository import CategoryRepository, ProductRepository
from app.repositories.message_repository import MessageRepository
from app.repositories.order_repository import OrderRepository
from app.services import coupon_service, invoice_service, loyalty_service, nlu_service, order_service, storage_service
from app.services.invoice_numbering import assign_invoice_number
from app.services.payment.razorpay import RazorpayGateway
from app.services.template_engine import render_template
from app.services.whatsapp_client import OutboundMessage, WhatsAppSender

logger = logging.getLogger(__name__)


class _OutOfStock(Exception):
    """Raised inside the `_confirm_order` SAVEPOINT when a cart line can't be satisfied --
    lets the caller roll back any stock already decremented for earlier lines in the same
    confirm attempt (see `FlowEngine._reserve_cart_stock`)."""

    def __init__(self, product_name: str, requested_qty: int):
        self.product_name = product_name
        self.requested_qty = requested_qty
        super().__init__(f"Insufficient stock for {product_name} (wanted {requested_qty})")


class _CouponNoLongerValid(Exception):
    """Raised inside the `_confirm_order` SAVEPOINT when the coupon locked at confirm time
    no longer supports the discount quoted to the customer (see `coupon_service.redeem`)."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _PaymentSetupFailed(Exception):
    """Raised inside the `_confirm_order` SAVEPOINT when `RazorpayGateway.create_payment`
    raises for any reason (bad credentials, Razorpay API error/outage, rejected amount,
    ...), so the whole attempt (order, stock, coupon/loyalty redemption) rolls back
    together and the customer can safely retry "Confirm Order" without risking a duplicate."""


# Generic, restaurant-agnostic copy shown until the admin configures bot_messages for
# these keys via the dashboard. Every token here is a fallback, never a hardcoded
# restaurant identity/menu value.
#
# NOTE (target-experience polish): the reference copy for the category-selection prompt
# ("Great! 😍 Please choose a category..."), the product-listing intro
# ("Here are our delicious {{category_name}} 🍕"), and the payment prompt/button
# ("How would you like to pay?" / "💳 Pay Securely Now") is not sourced from this dict --
# `_send_category_list`, `_send_product_list`, and `_send_order_summary` build that copy
# as inline literals instead of via `_message()`/DEFAULT_MESSAGES. Wiring those through a
# proper bot_messages key is a function-body change outside this dict's scope, so it's
# left as-is here rather than adding unused dict entries.
DEFAULT_MESSAGES: dict[str, str] = {
    "welcome": "👋 Welcome to {{restaurant_name}}! Order delicious food in seconds. How can we help you today?",
    "ask_quantity": "How many of *{{product_name}}* would you like? Reply with a number.",
    "ask_fulfillment": "Would you like delivery, or pickup from the restaurant?",
    "ask_coupon": "Have a coupon code? Enter it, reply REDEEM <points> to use loyalty points, or reply SKIP.",
    "ask_address": (
        "Please share your delivery address or send your location 📍\n"
        "(Tip: add any special instructions for the kitchen on a new line, e.g. \"no onions\".)"
    ),
    "order_confirmed": (
        "✅ Payment Successful! Thank you! Your order has been confirmed.\n"
        "Order ID: #{{order_number}}\nTotal: {{currency}} {{total}}\n"
        "Estimated delivery: {{delivery_time}}\n"
        "We have received your order and it will be prepared shortly."
    ),
    "invalid_input": "Sorry, I didn't understand that. Please pick one of the options shown.",
    "order_cancelled": "Your order has been cancelled. Send *hi* anytime to start a new order.",
    "restaurant_closed": "We're currently closed. Please check back during our opening hours.",
    "contact_us": "You can reach {{restaurant_name}} at {{support_number}}.",
    "handover": "Connecting you with our team -- someone will reply here shortly.",
    "today_special_empty": "No specials are marked right now -- check back soon!",
}

# Sensible out-of-the-box welcome menu for a freshly onboarded restaurant -- every entry
# maps to a real, working flow below (not just a placeholder message), and every entry is
# fully overridable/removable from the dashboard's Bot Builder once the restaurant wants
# something different.
DEFAULT_BUTTONS: list[dict[str, str]] = [
    {"id": "button:order_food", "title": "🍕 Order Food"},
    {"id": "button:view_menu", "title": "📋 View Menu"},
    {"id": "button:today_special", "title": "⭐ Today's Special"},
    {"id": "button:our_location", "title": "📍 Our Location"},
    {"id": "button:contact_restaurant", "title": "📞 Contact Restaurant"},
]

# Button actions with real, built-in behavior (branch-aware ordering/browsing/location/
# contact). Anything else is treated as a custom action and just resolves to an
# admin-editable bot_message key, same as Phase 1/2 -- so admins can still add arbitrary
# buttons without needing new code.
_MENU_BROWSE_ACTIONS = {"order_food", "view_menu"}

_HANDOVER_KEYWORDS = {"agent", "manager", "human", "support", "help me", "talk to someone", "representative"}
_GREETING_WORDS = {"hi", "hello", "hey", "hii", "hola", "start", "menu", "yo", "sup", "namaste"}


def _looks_like_greeting(text: str) -> bool:
    """Plain "hi"/"menu"/etc. should (re)show the welcome menu, not fall through to
    NLU/handover -- only route genuinely open-ended text through NLU matching."""
    normalized = re.sub(r"[^a-z\s]", "", text.lower()).strip()
    if not normalized:
        return True
    words = normalized.split()
    return len(words) <= 2 and all(w in _GREETING_WORDS for w in words)


@dataclass
class InboundInteraction:
    """Normalized shape of an inbound WhatsApp message, independent of Meta's payload format."""

    kind: str  # "text" | "list_reply" | "button_reply" | "location"
    text: str | None = None
    reply_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


@dataclass
class FlowContext:
    restaurant: Restaurant
    customer_id: uuid.UUID
    from_phone: str
    session: Any = field(default=None)  # AsyncSession, typed loosely to avoid circular import


class FlowEngine:
    def __init__(self, session, sender: WhatsAppSender):
        self.session = session
        self.sender = sender
        self.branch_repo = BranchRepository(session)
        self.category_repo = CategoryRepository(session)
        self.product_repo = ProductRepository(session)
        self.bot_message_repo = BotMessageRepository(session)
        self.bot_button_repo = BotButtonRepository(session)
        self.order_repo = OrderRepository(session)
        self.coupon_repo = CouponRepository(session)
        self.coupon_redemption_repo = CouponRedemptionRepository(session)
        self.faq_repo = FaqRepository(session)
        self.loyalty_repo = LoyaltyTransactionRepository(session)
        self.customer_repo = CustomerRepository(session)
        self.message_repo = MessageRepository(session)

    # --- messaging helpers -----------------------------------------------------------

    async def _message(self, restaurant: Restaurant, key: str, extra_context: dict[str, Any]) -> str:
        stored = await self.bot_message_repo.get_by_key(restaurant.id, key)
        template = stored.content if stored else DEFAULT_MESSAGES.get(key, "")
        context = {
            "restaurant_name": restaurant.name,
            "support_number": restaurant.support_number or "",
            "currency": restaurant.currency,
            **extra_context,
        }
        return render_template(template, context)

    @staticmethod
    def _loggable_body(message: OutboundMessage) -> str:
        payload = message.payload
        msg_type = payload.get("type")
        if msg_type == "text":
            return payload["text"]["body"]
        if msg_type == "interactive":
            return payload["interactive"].get("body", {}).get("text", "")
        if msg_type == "document":
            return payload["document"].get("caption") or payload["document"].get("filename", "[document]")
        if msg_type == "location":
            return payload["location"].get("name") or payload["location"].get("address") or "[location]"
        if msg_type == "image":
            return payload["image"].get("caption") or "[image]"
        return "[message]"

    async def _log_message(
        self,
        restaurant: Restaurant,
        customer_id: uuid.UUID,
        direction: MessageDirection,
        sent_by: MessageSender,
        body: str,
        staff_user_id: uuid.UUID | None = None,
        wa_message_id: str | None = None,
    ) -> None:
        self.session.add(
            Message(
                restaurant_id=restaurant.id,
                customer_id=customer_id,
                direction=direction,
                sent_by=sent_by,
                staff_user_id=staff_user_id,
                body=body[:4096],
                wa_message_id=wa_message_id,
            )
        )
        await self.session.flush()

    async def _send(self, restaurant: Restaurant, customer_id: uuid.UUID, message: OutboundMessage) -> None:
        access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
        try:
            await self.sender.send(restaurant.whatsapp_phone_number_id or "", access_token, message)
        except Exception:
            # Meta rejecting a send (bad image URL, recipient not allowed, transient API
            # error, ...) must not crash the whole webhook request -- that would leave the
            # customer's conversation state stuck and 500 the request Meta is waiting on.
            logger.warning("WhatsApp send failed for restaurant %s", restaurant.id, exc_info=True)
        await self._log_message(
            restaurant, customer_id, MessageDirection.OUTBOUND, MessageSender.BOT, self._loggable_body(message)
        )

    async def _send_welcome(self, restaurant: Restaurant, to: str, customer_id: uuid.UUID) -> None:
        cover_image = restaurant.cover_image_url or restaurant.logo_url
        if cover_image:
            await self._send(restaurant, customer_id, OutboundMessage.image(to, cover_image))
        body = await self._message(restaurant, "welcome", {})
        buttons = await self.bot_button_repo.list_visible(restaurant.id)
        rows = (
            [{"id": f"button:{b.action}", "title": f"{b.emoji or ''} {b.title}".strip()} for b in buttons]
            if buttons
            else [{"id": d["id"], "title": d["title"]} for d in DEFAULT_BUTTONS]
        )
        await self._send(restaurant, customer_id, OutboundMessage.interactive_list(to, body, "Select", rows, "Menu"))

    async def _send_branch_list(self, restaurant: Restaurant, to: str, customer_id: uuid.UUID) -> None:
        branches = await self.branch_repo.list(restaurant_id=restaurant.id)
        open_branches = [b for b in branches if b.status == BranchStatus.OPEN]
        if not open_branches:
            msg = await self._message(restaurant, "restaurant_closed", {})
            await self._send(restaurant, customer_id, OutboundMessage.text(to, msg))
            return
        rows = [{"id": f"branch:{b.id}", "title": b.name, "description": b.address or ""} for b in open_branches]
        await self._send(
            restaurant, customer_id, OutboundMessage.interactive_list(to, "Select a branch:", "Select", rows, "Branches")
        )

    async def _open_branches(self, restaurant: Restaurant) -> list[Branch]:
        branches = await self.branch_repo.list(restaurant_id=restaurant.id)
        return [b for b in branches if b.status == BranchStatus.OPEN]

    @staticmethod
    def _reset_context(context: dict[str, Any]) -> dict[str, Any]:
        """Wipe per-order state (cart/address/coupon/...) but keep the customer's chosen
        branch, so a repeat order in the same chat doesn't re-ask a multi-branch customer
        which branch they want every single time."""
        branch_id = context.get("branch_id")
        return {"branch_id": branch_id} if branch_id else {}

    async def _enter_welcome(
        self, restaurant: Restaurant, to: str, state: ConversationState, context: dict[str, Any]
    ) -> None:
        """Entry point for "hi"/a fresh conversation. A restaurant with more than one open
        branch must pick a branch before anything else (menu/hours/location/contact all
        depend on which branch), fully driven by that restaurant's own branch list --
        nothing hardcoded. A single-branch restaurant is auto-assigned its one branch so it
        sees zero extra friction."""
        if context.get("branch_id"):
            state.current_step = ConversationStep.WELCOME
            state.context = context
            await self._send_welcome(restaurant, to, state.customer_id)
            return

        open_branches = await self._open_branches(restaurant)
        if not open_branches:
            msg = await self._message(restaurant, "restaurant_closed", {})
            await self._send(restaurant, state.customer_id, OutboundMessage.text(to, msg))
            return

        if len(open_branches) == 1:
            context["branch_id"] = str(open_branches[0].id)
            state.current_step = ConversationStep.WELCOME
            state.context = context
            await self._send_welcome(restaurant, to, state.customer_id)
            return

        context["post_branch"] = "welcome"
        state.current_step = ConversationStep.SELECT_BRANCH
        state.context = context
        await self._send_branch_list(restaurant, to, state.customer_id)

    async def _require_branch_then(self, restaurant: Restaurant, to: str, state: ConversationState, context: dict[str, Any], post_branch: str) -> bool:
        """Returns True if a branch is already chosen. Otherwise prompts for one (or a
        single open branch is auto-assigned) and returns False, so the caller can bail out
        -- the SELECT_BRANCH handler resumes `post_branch` once a branch is picked."""
        if context.get("branch_id"):
            return True
        open_branches = await self._open_branches(restaurant)
        if not open_branches:
            msg = await self._message(restaurant, "restaurant_closed", {})
            await self._send(restaurant, state.customer_id, OutboundMessage.text(to, msg))
            return False
        if len(open_branches) == 1:
            context["branch_id"] = str(open_branches[0].id)
            state.context = context
            return True
        context["post_branch"] = post_branch
        state.current_step = ConversationStep.SELECT_BRANCH
        state.context = context
        await self._send_branch_list(restaurant, to, state.customer_id)
        return False

    async def _show_today_special(self, restaurant: Restaurant, to: str, state: ConversationState, context: dict[str, Any]) -> None:
        branch_id = uuid.UUID(context["branch_id"]) if context.get("branch_id") else None
        products = await self.product_repo.list_featured(restaurant.id, branch_id)
        if not products:
            msg = await self._message(restaurant, "today_special_empty", {})
            await self._send(restaurant, state.customer_id, OutboundMessage.text(to, msg))
            return
        rows = [
            {"id": f"product:{p.id}", "title": p.name, "description": f"{restaurant.currency} {p.discount_price or p.price}"}
            for p in products
        ]
        state.current_step = ConversationStep.SELECT_PRODUCT
        state.context = context
        await self._send(restaurant, state.customer_id, OutboundMessage.interactive_list(to, "⭐ Today's Special:", "Select", rows, "Special"))

    async def _send_location(self, restaurant: Restaurant, to: str, state: ConversationState, context: dict[str, Any]) -> None:
        branch = await self.branch_repo.get(uuid.UUID(context["branch_id"]), restaurant.id) if context.get("branch_id") else None
        address = (branch.address if branch else None) or restaurant.address
        if branch and branch.latitude is not None and branch.longitude is not None:
            await self._send(
                restaurant,
                state.customer_id,
                OutboundMessage.location(to, branch.latitude, branch.longitude, branch.name, address or ""),
            )
            return
        lines = [address or "Address not configured yet."]
        map_link = (branch.google_map_link if branch else None)
        if map_link:
            lines.append(map_link)
        await self._send(restaurant, state.customer_id, OutboundMessage.text(to, "\n".join(lines)))

    async def _send_contact(self, restaurant: Restaurant, to: str, state: ConversationState, context: dict[str, Any]) -> None:
        branch = await self.branch_repo.get(uuid.UUID(context["branch_id"]), restaurant.id) if context.get("branch_id") else None
        phone = (branch.phone if branch else None) or restaurant.support_number or "not configured yet"
        msg = await self._message(restaurant, "contact_us", {"support_number": phone})
        await self._send(restaurant, state.customer_id, OutboundMessage.text(to, msg))

    async def _send_fulfillment_prompt(self, restaurant: Restaurant, to: str, customer_id: uuid.UUID) -> None:
        body = await self._message(restaurant, "ask_fulfillment", {})
        buttons = [
            {"id": "fulfillment:delivery", "title": "🚚 Delivery"},
            {"id": "fulfillment:pickup", "title": "🏪 Pickup"},
        ]
        await self._send(restaurant, customer_id, OutboundMessage.interactive_buttons(to, body, buttons))

    async def _handle_change_branch(self, restaurant: Restaurant, to: str, state: ConversationState, context: dict[str, Any]) -> None:
        open_branches = await self._open_branches(restaurant)
        if len(open_branches) <= 1:
            await self._send(restaurant, state.customer_id, OutboundMessage.text(to, "There's only one branch available right now."))
            return
        context.pop("branch_id", None)
        context["post_branch"] = "welcome"
        state.current_step = ConversationStep.SELECT_BRANCH
        state.context = context
        await self._send_branch_list(restaurant, to, state.customer_id)

    async def _send_category_list(self, restaurant: Restaurant, to: str, customer_id: uuid.UUID) -> None:
        categories = await self.category_repo.list(restaurant_id=restaurant.id, visible=True)
        categories = sorted(categories, key=lambda c: c.display_order)
        if not categories:
            await self._send(restaurant, customer_id, OutboundMessage.text(to, "No categories are configured yet."))
            return
        rows = [{"id": f"category:{c.id}", "title": c.name} for c in categories]
        await self._send(
            restaurant, customer_id, OutboundMessage.interactive_list(to, "Select a category:", "Select", rows, "Categories")
        )

    async def _send_product_list(
        self,
        restaurant: Restaurant,
        to: str,
        customer_id: uuid.UUID,
        category_id: uuid.UUID,
        branch_id: uuid.UUID | None = None,
    ) -> None:
        products = await self.product_repo.list_by_category(category_id, restaurant.id, branch_id)
        if not products:
            await self._send(restaurant, customer_id, OutboundMessage.text(to, "No items available in this category."))
            return
        rows = [
            {
                "id": f"product:{p.id}",
                "title": p.name,
                "description": f"{restaurant.currency} {p.discount_price or p.price}",
            }
            for p in products
        ]
        await self._send(
            restaurant, customer_id, OutboundMessage.interactive_list(to, "Select an item:", "Select", rows, "Menu")
        )

    async def _send_cart_summary(self, restaurant: Restaurant, to: str, customer_id: uuid.UUID, cart: list[dict[str, Any]]) -> None:
        if not cart:
            body = "🛒 Your cart is empty."
            buttons = [{"id": "cart:add_more", "title": "Add More"}]
            await self._send(restaurant, customer_id, OutboundMessage.interactive_buttons(to, body, buttons))
            return
        lines = [f"{item['qty']} x {item['name']} - {restaurant.currency} {item['price'] * item['qty']:.2f}" for item in cart]
        totals = order_service.compute_totals(restaurant, cart)
        body = "🛒 Your cart:\n" + "\n".join(lines) + f"\n\nSubtotal: {restaurant.currency} {totals['subtotal']:.2f}"
        # Meta caps interactive-button messages at 3 buttons -- this is exactly 3.
        buttons = [
            {"id": "cart:add_more", "title": "Add More"},
            {"id": "cart:edit", "title": "Edit Cart"},
            {"id": "cart:checkout", "title": "Checkout"},
        ]
        await self._send(restaurant, customer_id, OutboundMessage.interactive_buttons(to, body, buttons))

    async def _send_cart_edit_list(self, restaurant: Restaurant, to: str, customer_id: uuid.UUID, cart: list[dict[str, Any]]) -> None:
        rows = [
            {
                "id": f"cart:line:{i}",
                "title": f"{item['qty']} x {item['name']}",
                "description": f"{restaurant.currency} {item['price'] * item['qty']:.2f}",
            }
            for i, item in enumerate(cart)
        ]
        await self._send(
            restaurant, customer_id, OutboundMessage.interactive_list(to, "Which item would you like to change?", "Select", rows, "Your Cart")
        )

    async def _send_cart_line_options(
        self, restaurant: Restaurant, to: str, customer_id: uuid.UUID, item: dict[str, Any], line_index: int
    ) -> None:
        body = f"{item['qty']} x {item['name']} - {restaurant.currency} {item['price'] * item['qty']:.2f}"
        buttons = [
            {"id": f"cart:qty:{line_index}", "title": "Change Qty"},
            {"id": f"cart:remove:{line_index}", "title": "Remove"},
            {"id": "cart:back", "title": "Back to Cart"},
        ]
        await self._send(restaurant, customer_id, OutboundMessage.interactive_buttons(to, body, buttons))

    async def _send_order_summary(
        self,
        restaurant: Restaurant,
        to: str,
        customer_id: uuid.UUID,
        cart: list[dict[str, Any]],
        address: str,
        discount: float = 0.0,
        fulfillment_type: FulfillmentType = FulfillmentType.DELIVERY,
    ) -> None:
        totals = order_service.compute_totals(restaurant, cart, discount, fulfillment_type)
        payment_label = "Razorpay (payment link)" if self._uses_razorpay(restaurant) else "Cash on Delivery"
        location_line = f"Pickup from: {address}" if fulfillment_type == FulfillmentType.PICKUP else f"Delivering to: {address}"
        delivery_line = "" if fulfillment_type == FulfillmentType.PICKUP else f"Delivery: {restaurant.currency} {totals['delivery_charge']:.2f}\n"
        body = (
            f"{location_line}\n\n"
            f"Subtotal: {restaurant.currency} {totals['subtotal']:.2f}\n"
            f"Tax: {restaurant.currency} {totals['tax']:.2f}\n"
            f"{delivery_line}"
            f"Discount: -{restaurant.currency} {totals['discount']:.2f}\n"
            f"Total: {restaurant.currency} {totals['total']:.2f}\n\n"
            f"Payment: {payment_label}"
        )
        buttons = [
            {"id": "order:confirm", "title": "Confirm Order"},
            {"id": "order:cancel", "title": "Cancel"},
        ]
        await self._send(restaurant, customer_id, OutboundMessage.interactive_buttons(to, body, buttons))

    @staticmethod
    def _uses_razorpay(restaurant: Restaurant) -> bool:
        return restaurant.default_payment_method == "razorpay" and "razorpay" in (restaurant.payment_methods or [])

    async def _is_first_order(self, restaurant_id: uuid.UUID, customer_id: uuid.UUID) -> bool:
        existing = await self.order_repo.list(restaurant_id=restaurant_id, customer_id=customer_id)
        return len(existing) == 0

    # --- coupon / loyalty step -------------------------------------------------------

    async def _handle_collect_coupon(
        self, restaurant: Restaurant, state: ConversationState, from_phone: str, context: dict[str, Any], text: str
    ) -> None:
        cart = context.get("cart", [])
        subtotal = float(order_service.compute_totals(restaurant, cart)["subtotal"])
        stripped = text.strip()

        if stripped.lower() in ("skip", "no", "none", ""):
            is_first_order = await self._is_first_order(restaurant.id, state.customer_id)
            auto = await coupon_service.find_best_auto_coupon(
                self.coupon_repo, self.coupon_redemption_repo, restaurant.id, state.customer_id, subtotal, is_first_order
            )
            if auto:
                coupon, discount = auto
                context["coupon_id"] = str(coupon.id)
                context["coupon_code"] = coupon.code
                context["discount"] = discount
            await self._advance_to_address(restaurant, from_phone, state, context)
            return

        if stripped.upper().startswith("REDEEM"):
            parts = stripped.split()
            points = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            customer = await self.customer_repo.get(state.customer_id, restaurant.id)
            if not points or not customer or points > (customer.loyalty_points or 0):
                msg = "You don't have enough points for that. " + await self._message(restaurant, "ask_coupon", {})
                await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                return
            value_per_point = float((restaurant.loyalty_settings or {}).get("redemption_value_per_point", 0))
            context["redeem_points"] = points
            context["discount"] = round(points * value_per_point, 2)
            context.pop("coupon_id", None)
            await self._advance_to_address(restaurant, from_phone, state, context)
            return

        is_first_order = await self._is_first_order(restaurant.id, state.customer_id)
        try:
            coupon, discount = await coupon_service.validate_and_apply(
                self.coupon_repo, self.coupon_redemption_repo, restaurant.id, state.customer_id, subtotal, stripped, is_first_order
            )
        except coupon_service.CouponValidationError as exc:
            msg = f"{exc.reason}\nEnter another code, or reply SKIP."
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
            return

        context["coupon_id"] = str(coupon.id)
        context["coupon_code"] = coupon.code
        context["discount"] = discount
        context.pop("redeem_points", None)
        await self._advance_to_address(
            restaurant, from_phone, state, context, prefix=f"Coupon applied! You saved {restaurant.currency} {discount:.2f}.\n"
        )

    async def _advance_to_address(
        self, restaurant: Restaurant, from_phone: str, state: ConversationState, context: dict[str, Any], prefix: str = ""
    ) -> None:
        """Both fulfillment types route through `ConversationStep.COLLECT_ADDRESS` next --
        for pickup there's no address to collect (the pickup location is the branch itself,
        filled in automatically once a reply lands), so that step instead asks for cooking
        notes; for delivery it asks for the address (optionally followed by notes on a new
        line). See the `COLLECT_ADDRESS` handler in `handle()` for how each branch is
        parsed."""
        state.current_step = ConversationStep.COLLECT_ADDRESS
        state.context = context
        if prefix:
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, prefix.strip()))
        if context.get("fulfillment_type") == FulfillmentType.PICKUP.value:
            await self._send(
                restaurant,
                state.customer_id,
                OutboundMessage.text(from_phone, "Any special instructions for the kitchen? (or reply 'skip')"),
            )
            return
        body = await self._message(restaurant, "ask_address", {})
        await self._send(restaurant, state.customer_id, OutboundMessage.location_request(from_phone, body))

    # --- order confirmation ------------------------------------------------------------

    async def _reserve_cart_stock(self, restaurant: Restaurant, cart: list[dict[str, Any]]) -> None:
        """Atomically checks-and-decrements `Product.stock_quantity` for every cart line
        whose product tracks stock (`stock_quantity is not None`); unlimited-stock products
        (NULL) are skipped entirely. MUST be called from inside a SAVEPOINT (see
        `_confirm_order`) -- raising `_OutOfStock` partway through relies on that SAVEPOINT
        being rolled back by the caller so decrements already applied to earlier lines in
        this same call don't stick around after a later line fails.
        """
        for item in cart:
            product = await self.product_repo.get(uuid.UUID(item["product_id"]), restaurant.id)
            if product is None or product.stock_quantity is None:
                continue
            qty = int(item["qty"])
            ok = await self.product_repo.decrement_stock(product.id, qty)
            if not ok:
                raise _OutOfStock(item.get("name") or product.name, qty)

    async def _confirm_order(self, restaurant: Restaurant, state: ConversationState, from_phone: str, context: dict[str, Any]) -> None:
        cart = context.get("cart", [])
        discount = float(context.get("discount", 0) or 0)
        coupon_id = uuid.UUID(context["coupon_id"]) if context.get("coupon_id") else None
        payment_method = PaymentMethod.RAZORPAY if self._uses_razorpay(restaurant) else PaymentMethod.COD
        fulfillment_type = FulfillmentType(context.get("fulfillment_type", "delivery"))

        delivery_address: dict[str, Any] = {"address": context.get("address", "")}
        if context.get("address_lat") is not None:
            delivery_address["latitude"] = context["address_lat"]
            delivery_address["longitude"] = context["address_lng"]

        # Must be computed before the order below exists, or it would count as the
        # customer's own prior order and always report False.
        is_first_order = await self._is_first_order(restaurant.id, state.customer_id)

        order: Order | None = None
        try:
            # Everything that must succeed or fail together -- stock reservation, order
            # creation, coupon/loyalty redemption, and (if applicable) the Razorpay payment
            # link -- lives inside one SAVEPOINT. Raising out of this block rolls all of it
            # back, so a rejected confirm (out of stock / coupon no longer valid / payment
            # setup failed) never leaves a half-created order, a decremented-but-unsold
            # stock count, or a redemption row behind -- the customer's cart/context is
            # untouched and retrying "Confirm Order" is always safe.
            async with self.session.begin_nested():
                await self._reserve_cart_stock(restaurant, cart)

                order = await order_service.create_order_from_cart(
                    self.order_repo,
                    restaurant,
                    uuid.UUID(context["branch_id"]),
                    state.customer_id,
                    cart,
                    delivery_address,
                    notes=context.get("notes"),
                    discount=discount,
                    coupon_id=coupon_id,
                    payment_method=payment_method,
                    fulfillment_type=fulfillment_type,
                )

                if coupon_id and context.get("coupon_code"):
                    # Single source of truth for the discount: `redeem` validates the
                    # already-computed `discount` against the locked coupon row's current
                    # constraints instead of recomputing it (see coupon_service.redeem's
                    # docstring). If the coupon has become invalid/inactive since the
                    # customer entered it, the whole confirm is rejected below rather than
                    # best-effort-completing the order without a redemption row.
                    try:
                        await coupon_service.redeem(
                            self.coupon_repo,
                            self.coupon_redemption_repo,
                            restaurant.id,
                            state.customer_id,
                            order.id,
                            float(order.subtotal),
                            context["coupon_code"],
                            is_first_order,
                            discount,
                        )
                    except coupon_service.CouponValidationError as exc:
                        raise _CouponNoLongerValid(exc.reason) from exc
                elif context.get("redeem_points"):
                    customer = await self.customer_repo.get(state.customer_id, restaurant.id)
                    if customer:
                        try:
                            await loyalty_service.redeem_points(self.loyalty_repo, restaurant, customer, int(context["redeem_points"]))
                        except loyalty_service.LoyaltyError:
                            logger.warning("Loyalty redemption failed at confirm time for customer %s", state.customer_id)

                # Razorpay rejects amount=0 (and very small amounts) outright -- a coupon or
                # loyalty discount that fully covers the order is treated like a COD/free
                # order instead of attempting a payment link at all.
                if payment_method == PaymentMethod.RAZORPAY and order.total > 0:
                    try:
                        gateway = RazorpayGateway(restaurant)
                        payment_info = await gateway.create_payment(order)
                    except Exception as exc:
                        raise _PaymentSetupFailed() from exc
                    if payment_info.get("payment_link_url"):
                        order.gateway_metadata = payment_info
                    else:
                        # Razorpay not configured yet -- fall back to a COD-style
                        # confirmation rather than failing the order.
                        order.payment_method = PaymentMethod.COD
                        payment_method = PaymentMethod.COD
        except _OutOfStock as exc:
            msg = f"Sorry, *{exc.product_name}* is no longer available in that quantity. Please update your cart."
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
            state.current_step = ConversationStep.CART
            state.context = context
            await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
            return
        except _CouponNoLongerValid as exc:
            context.pop("coupon_id", None)
            context.pop("coupon_code", None)
            context.pop("discount", None)
            msg = f"Your coupon is no longer valid ({exc.reason}). Reply SKIP to continue without it, or enter a new code."
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
            state.current_step = ConversationStep.COLLECT_COUPON
            state.context = context
            return
        except _PaymentSetupFailed:
            logger.warning(
                "Razorpay payment link creation failed for restaurant %s -- order rolled back, retry-safe", restaurant.id, exc_info=True
            )
            msg = "Sorry, we couldn't set up payment right now -- please try confirming your order again in a moment."
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
            # The SAVEPOINT above was rolled back (order/stock/redemptions all undone), and
            # current_step/context are untouched -- the customer is still at CONFIRM_ORDER
            # and can safely tap "Confirm Order" again without risking a duplicate order.
            return

        assert order is not None
        await self._attach_invoice(restaurant, order)

        if payment_method == PaymentMethod.RAZORPAY and order.gateway_metadata.get("payment_link_url"):
            msg = (
                f"Order {order.order_number} created -- total {restaurant.currency} {order.total:.2f}.\n"
                f"Complete payment here: {order.gateway_metadata['payment_link_url']}"
            )
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
            await ws_manager.broadcast(restaurant.id, {"type": "order_created", "order_id": str(order.id)})
            state.current_step = ConversationStep.COMPLETED
            state.context = self._reset_context(context)
            return

        if order.total == 0:
            if fulfillment_type == FulfillmentType.PICKUP:
                msg = f"✅ Your order {order.order_number} is confirmed -- nothing to pay! We'll have it ready for pickup shortly."
            else:
                msg = f"✅ Your order {order.order_number} is confirmed -- nothing to pay! Estimated delivery: 30-45 mins."
        else:
            msg = await self._message(
                restaurant,
                "order_confirmed",
                {"order_number": order.order_number, "total": f"{order.total:.2f}", "delivery_time": "30-45 mins"},
            )
        await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
        await ws_manager.broadcast(restaurant.id, {"type": "order_created", "order_id": str(order.id)})
        state.current_step = ConversationStep.COMPLETED
        state.context = self._reset_context(context)

    async def _attach_invoice(self, restaurant: Restaurant, order) -> None:
        # Deliberately outside the try/except below and assigned first: a confirmed order
        # must get a permanent, GST-compliant, gap-free sequential invoice number even if
        # PDF generation or the S3 upload afterward fails -- see
        # app/services/invoice_numbering.py's docstring for why numbering and rendering
        # are independent steps.
        order.invoice_number = await assign_invoice_number(self.session, restaurant.id)
        await self.session.flush()
        try:
            branch = await self.branch_repo.get(order.branch_id, restaurant.id)
            pdf_bytes = invoice_service.generate_invoice_pdf(order, restaurant, branch)
            key = f"invoices/{restaurant.id}/{order.id}.pdf"
            # boto3 is synchronous/blocking; run it off the event loop so a slow or
            # unreachable storage backend doesn't stall every other in-flight request.
            url = await asyncio.to_thread(storage_service.upload_bytes, key, pdf_bytes, "application/pdf")
            order.invoice_url = url
            await self.session.flush()
        except Exception:
            # Object storage isn't reachable/configured yet in every environment --
            # the order still completes with a real invoice_number; only the
            # PDF/upload is best-effort, not load-bearing.
            logger.warning("Invoice generation/upload failed for order %s", order.order_number, exc_info=True)

    # --- main dispatch -----------------------------------------------------------------

    async def handle(
        self,
        restaurant: Restaurant,
        state: ConversationState,
        from_phone: str,
        interaction: InboundInteraction,
    ) -> None:
        context = dict(state.context or {})
        step = state.current_step
        reply_id = interaction.reply_id or ""

        if step == ConversationStep.HANDED_OVER:
            # A human is handling this conversation; the bot stays quiet until staff resolves it.
            return

        if step in (ConversationStep.WELCOME, ConversationStep.COMPLETED):
            # COMPLETED (a just-finished order) is treated identically to WELCOME here --
            # both are "nothing in progress" states, so a customer saying "hi" (or tapping
            # any welcome-menu button/list action) right after an order confirms starts a
            # fresh order the same way a brand new conversation would.
            if reply_id.startswith("button:"):
                action = reply_id.split(":", 1)[1]

                if action in _MENU_BROWSE_ACTIONS:
                    if not await self._require_branch_then(restaurant, from_phone, state, context, action):
                        return
                    context["cart"] = context.get("cart", [])
                    state.current_step = ConversationStep.SELECT_CATEGORY
                    state.context = context
                    await self._send_category_list(restaurant, from_phone, state.customer_id)
                    return

                if action == "today_special":
                    if not await self._require_branch_then(restaurant, from_phone, state, context, action):
                        return
                    await self._show_today_special(restaurant, from_phone, state, context)
                    return

                if action == "our_location":
                    await self._send_location(restaurant, from_phone, state, context)
                    return

                if action == "contact_restaurant":
                    await self._send_contact(restaurant, from_phone, state, context)
                    return

                if action == "change_branch":
                    await self._handle_change_branch(restaurant, from_phone, state, context)
                    return

                # Custom admin-defined button -- resolve to its bot_message key, same as before.
                msg = await self._message(restaurant, action, {})
                await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg or "Coming soon."))
                return

            text = (interaction.text or "").strip()
            if text and not _looks_like_greeting(text):
                lowered = text.lower()
                if any(keyword in lowered for keyword in _HANDOVER_KEYWORDS):
                    await self._handover(restaurant, state, from_phone)
                    return
                products = await self.product_repo.list(restaurant_id=restaurant.id)
                faq_entries = await self.faq_repo.list(restaurant_id=restaurant.id)
                answer = nlu_service.match(products, faq_entries, text, restaurant.currency, {"restaurant_name": restaurant.name})
                if answer:
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, answer))
                    return
                await self._handover(restaurant, state, from_phone)
                return

            await self._enter_welcome(restaurant, from_phone, state, context)
            return

        if step == ConversationStep.SELECT_BRANCH:
            if reply_id.startswith("branch:"):
                branch_id = reply_id.split(":", 1)[1]
                branch = await self.branch_repo.get(uuid.UUID(branch_id), restaurant.id)
                if not branch or branch.status != BranchStatus.OPEN:
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, await self._message(restaurant, "invalid_input", {})))
                    return
                context["branch_id"] = branch_id
                post_branch = context.pop("post_branch", "welcome")
                state.context = context

                if post_branch in _MENU_BROWSE_ACTIONS:
                    context["cart"] = context.get("cart", [])
                    state.current_step = ConversationStep.SELECT_CATEGORY
                    state.context = context
                    await self._send_category_list(restaurant, from_phone, state.customer_id)
                    return
                if post_branch == "today_special":
                    await self._show_today_special(restaurant, from_phone, state, context)
                    return

                state.current_step = ConversationStep.WELCOME
                await self._send_welcome(restaurant, from_phone, state.customer_id)
                return
            await self._send_branch_list(restaurant, from_phone, state.customer_id)
            return

        if step == ConversationStep.SELECT_CATEGORY:
            if reply_id.startswith("category:"):
                category_id = reply_id.split(":", 1)[1]
                context["category_id"] = category_id
                state.current_step = ConversationStep.SELECT_PRODUCT
                state.context = context
                branch_id = uuid.UUID(context["branch_id"]) if context.get("branch_id") else None
                await self._send_product_list(restaurant, from_phone, state.customer_id, uuid.UUID(category_id), branch_id)
                return
            await self._send_category_list(restaurant, from_phone, state.customer_id)
            return

        if step == ConversationStep.SELECT_PRODUCT:
            if reply_id.startswith("product:"):
                product_id = reply_id.split(":", 1)[1]
                product = await self.product_repo.get(uuid.UUID(product_id), restaurant.id)
                if not product:
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, await self._message(restaurant, "invalid_input", {})))
                    return
                context["pending_product"] = {
                    "product_id": product_id,
                    "name": product.name,
                    "price": float(product.discount_price or product.price),
                    "gst_percent": float(product.gst_percent or 0),
                }
                state.current_step = ConversationStep.SELECT_QUANTITY
                state.context = context
                msg = await self._message(restaurant, "ask_quantity", {"product_name": product.name})
                await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                return
            await self._send_category_list(restaurant, from_phone, state.customer_id)
            return

        if step == ConversationStep.SELECT_QUANTITY:
            text = (interaction.text or "").strip()
            if text.isdigit() and int(text) > 0:
                qty = int(text)
                pending = context.get("pending_product")
                if not pending:
                    state.current_step = ConversationStep.SELECT_CATEGORY
                    state.context = context
                    await self._send_category_list(restaurant, from_phone, state.customer_id)
                    return
                cart = context.get("cart", [])
                cart.append({**pending, "qty": qty})
                context["cart"] = cart
                context.pop("pending_product", None)
                state.current_step = ConversationStep.CART
                state.context = context
                await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                return
            msg = await self._message(restaurant, "invalid_input", {})
            await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
            return

        if step == ConversationStep.CART:
            cart = context.get("cart", [])

            if reply_id == "cart:add_more":
                context.pop("editing_line", None)
                state.current_step = ConversationStep.SELECT_CATEGORY
                state.context = context
                await self._send_category_list(restaurant, from_phone, state.customer_id)
                return

            if reply_id == "cart:checkout":
                if not cart:
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, "Your cart is empty -- add an item first."))
                    await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                    return
                context.pop("editing_line", None)
                state.current_step = ConversationStep.SELECT_FULFILLMENT
                state.context = context
                await self._send_fulfillment_prompt(restaurant, from_phone, state.customer_id)
                return

            if reply_id == "cart:edit":
                context.pop("editing_line", None)
                state.context = context
                await self._send_cart_edit_list(restaurant, from_phone, state.customer_id, cart)
                return

            if reply_id.startswith("cart:line:"):
                idx = int(reply_id.split(":", 2)[2])
                if 0 <= idx < len(cart):
                    await self._send_cart_line_options(restaurant, from_phone, state.customer_id, cart[idx], idx)
                else:
                    await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                return

            if reply_id.startswith("cart:remove:"):
                idx = int(reply_id.split(":", 2)[2])
                if 0 <= idx < len(cart):
                    removed = cart.pop(idx)
                    context["cart"] = cart
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, f"Removed {removed['name']} from your cart."))
                context.pop("editing_line", None)
                state.context = context
                await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                return

            if reply_id.startswith("cart:qty:"):
                idx = int(reply_id.split(":", 2)[2])
                if 0 <= idx < len(cart):
                    context["editing_line"] = idx
                    state.context = context
                    msg = f"How many *{cart[idx]['name']}* would you like? Reply with a number (0 removes it)."
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                else:
                    await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                return

            if reply_id == "cart:back":
                context.pop("editing_line", None)
                state.context = context
                await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                return

            if context.get("editing_line") is not None:
                idx = context["editing_line"]
                text = (interaction.text or "").strip()
                if text.isdigit() and 0 <= idx < len(cart):
                    qty = int(text)
                    if qty <= 0:
                        removed = cart.pop(idx)
                        msg = f"Removed {removed['name']} from your cart."
                    else:
                        cart[idx]["qty"] = qty
                        msg = f"Updated {cart[idx]['name']} to qty {qty}."
                    context["cart"] = cart
                    context.pop("editing_line", None)
                    state.context = context
                    await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                    await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
                    return
                msg = await self._message(restaurant, "invalid_input", {})
                await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                return

            await self._send_cart_summary(restaurant, from_phone, state.customer_id, cart)
            return

        if step == ConversationStep.SELECT_FULFILLMENT:
            if reply_id in ("fulfillment:delivery", "fulfillment:pickup"):
                context["fulfillment_type"] = reply_id.split(":", 1)[1]
                state.current_step = ConversationStep.COLLECT_COUPON
                state.context = context
                msg = await self._message(restaurant, "ask_coupon", {})
                await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                return
            await self._send_fulfillment_prompt(restaurant, from_phone, state.customer_id)
            return

        if step == ConversationStep.COLLECT_COUPON:
            await self._handle_collect_coupon(restaurant, state, from_phone, context, interaction.text or "")
            return

        if step == ConversationStep.COLLECT_ADDRESS:
            if context.get("fulfillment_type") == FulfillmentType.PICKUP.value:
                # Pickup has no address to collect -- this step instead asks for cooking
                # notes (see `_advance_to_address`); any reply other than skip/no/none/empty
                # is stored verbatim as the note.
                text = (interaction.text or "").strip()
                if text.lower() not in ("skip", "no", "none", ""):
                    context["notes"] = text
                branch = await self.branch_repo.get(uuid.UUID(context["branch_id"]), restaurant.id) if context.get("branch_id") else None
                pickup_address = branch.name if branch else restaurant.name
                context["address"] = pickup_address
                state.current_step = ConversationStep.CONFIRM_ORDER
                state.context = context
                await self._send_order_summary(
                    restaurant,
                    from_phone,
                    state.customer_id,
                    context.get("cart", []),
                    pickup_address,
                    float(context.get("discount", 0) or 0),
                    FulfillmentType.PICKUP,
                )
                return

            address_value: str | None = None
            if interaction.kind == "location" and interaction.latitude is not None and interaction.longitude is not None:
                maps_link = f"https://maps.google.com/?q={interaction.latitude},{interaction.longitude}"
                address_value = f"{interaction.text} ({maps_link})" if interaction.text else maps_link
                context["address_lat"] = interaction.latitude
                context["address_lng"] = interaction.longitude
            else:
                text = (interaction.text or "").strip()
                if text:
                    # Everything after the first line is treated as cooking notes (see the
                    # "ask_address" prompt copy), so a customer can send
                    # "12 Elm Street\nno onions please" in one message instead of two.
                    first_line, _, rest = text.partition("\n")
                    address_value = first_line.strip()
                    rest = rest.strip()
                    if rest:
                        context["notes"] = rest

            if address_value:
                context["address"] = address_value
                state.current_step = ConversationStep.CONFIRM_ORDER
                state.context = context
                await self._send_order_summary(
                    restaurant,
                    from_phone,
                    state.customer_id,
                    context.get("cart", []),
                    address_value,
                    float(context.get("discount", 0) or 0),
                    FulfillmentType.DELIVERY,
                )
                return
            msg = await self._message(restaurant, "ask_address", {})
            await self._send(restaurant, state.customer_id, OutboundMessage.location_request(from_phone, msg))
            return

        if step == ConversationStep.CONFIRM_ORDER:
            if reply_id == "order:confirm":
                await self._confirm_order(restaurant, state, from_phone, context)
                return
            if reply_id == "order:cancel":
                msg = await self._message(restaurant, "order_cancelled", {})
                await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
                state.current_step = ConversationStep.WELCOME
                state.context = self._reset_context(context)
                return
            await self._send_order_summary(
                restaurant,
                from_phone,
                state.customer_id,
                context.get("cart", []),
                context.get("address", ""),
                float(context.get("discount", 0) or 0),
                FulfillmentType(context.get("fulfillment_type", "delivery")),
            )
            return

        # Fallback: reset to welcome for any unrecognized state.
        state.current_step = ConversationStep.WELCOME
        state.context = self._reset_context(context)
        await self._enter_welcome(restaurant, from_phone, state, state.context)

    async def _handover(self, restaurant: Restaurant, state: ConversationState, from_phone: str) -> None:
        state.current_step = ConversationStep.HANDED_OVER
        msg = await self._message(restaurant, "handover", {})
        await self._send(restaurant, state.customer_id, OutboundMessage.text(from_phone, msg))
        await ws_manager.broadcast(restaurant.id, {"type": "handover", "customer_id": str(state.customer_id)})


async def send_unavailable_notice(sender: WhatsAppSender, restaurant: Restaurant, from_phone: str) -> None:
    """For a suspended/cancelled restaurant (see app/api/v1/routers/webhook.py) -- a
    plain, un-logged, state-free send. Deliberately doesn't touch ConversationState or
    Message history: a blocked account shouldn't accumulate conversation state, and there
    is nothing useful to resume once it's reactivated (the customer just says "hi" again).
    """
    access_token = decrypt_secret(restaurant.whatsapp_access_token_encrypted or "")
    try:
        await sender.send(
            restaurant.whatsapp_phone_number_id or "",
            access_token,
            OutboundMessage.text(
                from_phone,
                "We're sorry, this restaurant isn't taking WhatsApp orders right now. Please check back later.",
            ),
        )
    except Exception:
        logger.warning("Failed to send unavailable-notice for restaurant %s", restaurant.id, exc_info=True)


async def process_inbound_message(
    session,
    sender: WhatsAppSender,
    restaurant: Restaurant,
    from_phone: str,
    interaction: InboundInteraction,
    wa_message_id: str | None = None,
) -> None:
    """Entry point called by the webhook router for every inbound customer message.

    `wa_message_id`: Meta's stable per-message id, used to make webhook processing
    idempotent -- Meta may redeliver the same webhook event (retries on timeout/5xx), and
    without this a redelivery would be reprocessed into a second order. The webhook router
    (`app/api/v1/routers/webhook.py`) extracts it from the inbound payload as
    `entry[].changes[].value.messages[].id` (a string like "wamid.xxx", present per-element
    of that `messages` list) and passes it on every call -- one call to
    `process_inbound_message` per inbound message, each with its own id. The parameter still
    defaults to None for callers that construct an `InboundInteraction` directly (e.g.
    tests, `scripts/smoke_test.py`) without a real wa_message_id to hand in, in which case
    this idempotency check is simply skipped.
    """
    message_repo = MessageRepository(session)
    if wa_message_id:
        existing = await message_repo.get_by_wa_message_id(wa_message_id)
        if existing is not None:
            # Already processed this exact WhatsApp message -- idempotent no-op: no
            # reprocessing, no resend, no duplicate order.
            return

    customer_repo = CustomerRepository(session)
    customer = await customer_repo.get_or_create(restaurant.id, from_phone)

    # Locks the customer's conversation-state row for the duration of this transaction, so
    # two inbound messages for the same customer arriving concurrently (e.g. a duplicate
    # webhook delivery racing the original, or the customer double-tapping "Confirm Order")
    # serialize instead of both reading the same pre-transition state and both advancing it
    # (which is how a customer could end up with two orders from one "Confirm"). SQLite
    # (used in tests) accepts `.with_for_update()` as a no-op rather than erroring, so no
    # dialect guard is needed here.
    result = await session.execute(
        select(ConversationState).where(ConversationState.customer_id == customer.id).with_for_update()
    )
    state = result.scalar_one_or_none()
    if state is None:
        state = ConversationState(
            restaurant_id=restaurant.id,
            customer_id=customer.id,
            current_step=ConversationStep.WELCOME,
            context={},
        )
        session.add(state)
        await session.flush()

    engine = FlowEngine(session, sender)
    if interaction.kind == "location" and interaction.latitude is not None:
        inbound_body = interaction.text or f"📍 Shared location ({interaction.latitude:.4f}, {interaction.longitude:.4f})"
    else:
        inbound_body = interaction.text or interaction.reply_id or "[unsupported message]"
    await engine._log_message(
        restaurant,
        customer.id,
        MessageDirection.INBOUND,
        MessageSender.CUSTOMER,
        inbound_body,
        wa_message_id=wa_message_id,
    )

    await engine.handle(restaurant, state, from_phone, interaction)
    await session.commit()
