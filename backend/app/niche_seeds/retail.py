"""Retail / Fashion / Boutique niche template -- a second `action_type="order"` niche
(cart + quantity + checkout + payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). Shares the Restaurant order-flow shape
(app/niche_seeds/restaurant.py) -- no new engine capability is required -- but with its
own terminology, welcome menu, and apparel-specific catalog copy.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_retail.py for an end-to-end proof this drives a real conversation
through the real engine, including cart, checkout, and a Razorpay payment link.

Order-flow shape (context keys a completed order's Engagement.details carries):
  category_id -> item_id (via pending_item, not a bare capture_key) -> qty -> cart
  (list of {item_id, name, price, qty}) -> delivery_address (+ optional coords) ->
  cart_summary/cart_total (recomputed by the engine's add_to_cart/remove_cart_line verbs
  after every cart mutation -- see generic_flow_engine.py::_Engine._refresh_cart_summary).
`create_engagement` reads its EngagementType off the FlowDefinition itself (not off any
step) and sets requires_payment=True automatically whenever the cart is non-empty.

Size/colour are carried in each item's `attributes` JSON bag for admin/API use, but
surfaced to the customer via each item's plain `description` field -- the shared
engine's `_price_label` `include_attributes` special-case only understands
`duration_minutes` (a salon-specific concept), so this is the zero-engine-change way to
make sizes/colours visible in the item list (see generic_flow_engine.py, which this file
must not edit).
"""

from app.niche_seeds._media import demo_image_base


_DEMO_IMG_BASE = demo_image_base("retail")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_MENS = f"{_DEMO_IMG_BASE}/mens.jpg"
_IMG_WOMENS = f"{_DEMO_IMG_BASE}/womens.jpg"
_IMG_FOOTWEAR = f"{_DEMO_IMG_BASE}/footwear.jpg"
_IMG_ACCESSORIES = f"{_DEMO_IMG_BASE}/accessories.jpg"

_WELCOME_TEXT = "\U0001f455 Welcome to {{business_name}}! Shop the latest styles in seconds."


TEMPLATE = {
    "code": "retail",
    "name": "Retail & Fashion",
    "action_type": "order",
    "icon": "\U0001f455",  # 👕
    "welcome_message": _WELCOME_TEXT,
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:shop", "title": "\U0001f6cd️ Shop Now"},
        {"id": "welcome:cart", "title": "\U0001f6cd️ View Cart"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:store", "title": "\U0001f3ea Our Store"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Men's Wear",
            "icon_image": _IMG_MENS,
            "items": [
                {
                    "name": "Casual Shirt",
                    "description": "Breathable cotton shirt for everyday wear. Sizes: S, M, L, XL.",
                    "price": 899,
                    "price_type": "fixed",
                    "images": [_IMG_MENS],
                    "attributes": {"category": "men", "sizes": ["S", "M", "L", "XL"]},
                },
                {
                    "name": "Formal Trousers",
                    "description": "Tailored fit trousers, perfect for office wear. Sizes: 30, 32, 34, 36.",
                    "price": 1299,
                    "price_type": "fixed",
                    "images": [_IMG_MENS],
                    "attributes": {"category": "men", "sizes": ["30", "32", "34", "36"]},
                },
            ],
        },
        {
            "name": "Women's Wear",
            "icon_image": _IMG_WOMENS,
            "items": [
                {
                    "name": "Printed Kurti",
                    "description": "Lightweight rayon kurti with block print detailing. Sizes: S, M, L, XL.",
                    "price": 799,
                    "price_type": "fixed",
                    "images": [_IMG_WOMENS],
                    "attributes": {"category": "women", "sizes": ["S", "M", "L", "XL"]},
                },
                {
                    "name": "Party Dress",
                    "description": "Flowy evening dress with a flattering silhouette. Sizes: S, M, L.",
                    "price": 1899,
                    "price_type": "fixed",
                    "images": [_IMG_WOMENS],
                    "attributes": {"category": "women", "sizes": ["S", "M", "L"]},
                },
            ],
        },
        {
            "name": "Footwear",
            "icon_image": _IMG_FOOTWEAR,
            "items": [
                {
                    "name": "Sneakers",
                    "description": "Cushioned everyday sneakers with a grippy sole. Sizes: 7, 8, 9, 10.",
                    "price": 1999,
                    "price_type": "fixed",
                    "images": [_IMG_FOOTWEAR],
                    "attributes": {"category": "footwear", "sizes": ["7", "8", "9", "10"]},
                },
                {
                    "name": "Sandals",
                    "description": "Comfortable everyday sandals, easy slip-on fit. Sizes: 7, 8, 9, 10.",
                    "price": 699,
                    "price_type": "fixed",
                    "images": [_IMG_FOOTWEAR],
                    "attributes": {"category": "footwear", "sizes": ["7", "8", "9", "10"]},
                },
            ],
        },
        {
            "name": "Accessories",
            "icon_image": _IMG_ACCESSORIES,
            "items": [
                {
                    "name": "Handbag",
                    "description": "Structured handbag with adjustable strap.",
                    "price": 1499,
                    "price_type": "fixed",
                    "images": [_IMG_ACCESSORIES],
                    "attributes": {"category": "accessories"},
                },
                {
                    "name": "Sunglasses",
                    "description": "UV-protected sunglasses with a classic frame.",
                    "price": 599,
                    "price_type": "fixed",
                    "images": [_IMG_ACCESSORIES],
                    "attributes": {"category": "accessories"},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": _WELCOME_TEXT,
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:shop", "title": "\U0001f6cd️ Shop Now"},
                {"id": "welcome:cart", "title": "\U0001f6cd️ View Cart"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:store", "title": "\U0001f3ea Our Store"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
                {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
            ],
            "routes": {
                "welcome:shop": "category_select",
                "welcome:cart": "cart_menu",
                "welcome:offers": "offers_info",
                "welcome:store": "store_info",
                "welcome:contact": "contact_info",
                "welcome:human": "human_handoff",
            },
            "next": "category_select",
            "back_target": None,
            "show_image": True,
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f381 Ask our team about today's seasonal discounts and combo offers any time you shop!",
            "back_target": "welcome",
        },
        {
            "step_id": "store_info",
            "type": "message",
            "prompt": (
                "\U0001f3ea {{business_name}}\n\n[Address will appear here once the business "
                "adds it in Settings.]\n\nTap \U0001f9d1 Talk to a Human if you'd like directions right now."
            ),
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": (
                "\U0001f4de {{business_name}}\n\nPhone: [add your number in Settings]\n"
                "Hours: [add your hours in Settings]\n\n"
                "Or tap \U0001f9d1 Talk to a Human from the main menu to chat with our team right now."
            ),
            "back_target": "welcome",
        },
        {
            "step_id": "human_handoff",
            "type": "human_handoff",
            "message": "\U0001f9d1 Connecting you with our team at {{business_name}} -- someone will reply here shortly.",
            "back_target": "welcome",
        },
        {
            # "Shop Now" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "What would you like to shop for?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "item_select",
            "show_image": True,
            "section_title": "Categories",
        },
        {
            # Category tapped -> Item list (name + price, tap = select).
            # [Back -> Category list]
            "step_id": "item_select",
            "type": "menu_select",
            "prompt": "Here's our {{category_id_label}} collection -- tap an item to add it:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "action": "capture_pending_item",
            "back_target": "category_select",
            "next": "quantity_select",
            "show_image": True,
            "section_title": "Items",
        },
        {
            # Item tapped -> Quantity buttons (1/2/3/Custom), adds to cart.
            # [Back -> Item list]
            "step_id": "quantity_select",
            "type": "quantity_input",
            "prompt": "How many *{{pending_item_name}}* ({{pending_item_price}}) would you like?",
            "action": "add_to_cart",
            "back_target": "item_select",
            "next": "cart_menu",
            "show_image": False,
        },
        {
            # Cart menu -- Add More Items / Checkout. Reachable both from the order chain
            # and directly from welcome's "View Cart" button. [Back -> Category list]
            "step_id": "cart_menu",
            "type": "menu_select",
            "prompt": "\U0001f6cd️ Your bag so far:\n\n{{cart_summary}}\n\nTotal: {{currency}} {{cart_total}}\n\nWhat next?",
            "buttons_from": "static",
            "static_options": [
                {"id": "cart:add_more", "title": "➕ Add More Items"},
                {"id": "cart:checkout", "title": "✅ Checkout"},
            ],
            "routes": {
                "cart:add_more": "category_select",
                "cart:checkout": "address_capture",
            },
            "next": "address_capture",
            "back_target": "category_select",
            "show_image": False,
        },
        {
            # Delivery address -- free text or native WhatsApp location share,
            # skippable for store pickup. [Back -> Cart menu]
            "step_id": "address_capture",
            "type": "free_text_input",
            "prompt": "Please share your delivery address (or tap Skip for store pickup):",
            "capture_key": "delivery_address",
            "allow_skip": True,
            "accepts_location": True,
            "back_target": "cart_menu",
            "next": "order_confirm",
        },
        {
            # Order confirmation card (items, total, address) -> "Place Order".
            # [Back -> delivery address]
            "step_id": "order_confirm",
            "type": "confirm_action",
            "prompt": (
                "Please review your order:\n\n"
                "{{cart_summary}}\n\n"
                "Total: {{currency}} {{cart_total}}\n"
                "\U0001f4cd Delivery: {{delivery_address}}\n\n"
                "Tap below to place your order."
            ),
            "buttons_from": "static",
            "static_options": [{"id": "order:confirm", "title": "✅ Place Order"}],
            "action": "create_engagement",
            "back_target": "address_capture",
            "next": "order_confirmed",
            "show_image": False,
        },
        {
            # Confirmed -> confirmation + payment link (create_engagement generates a
            # real Razorpay payment link whenever the cart total is non-zero -- see
            # app/services/payment/generic_razorpay.py); notify_business() (called
            # unconditionally inside create_engagement) notifies staff. Flow complete --
            # terminal, no Back.
            "step_id": "order_confirmed",
            "type": "message",
            "prompt": (
                "✅ Order placed! Reference: {{last_reference_number}}.\n\n"
                "Total: {{currency}} {{last_total}}\n"
                "{{payment_link_url}}\n\n"
                "We'll start packing your order right away. Thank you for shopping with "
                "{{business_name}}!"
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "Received",
            "confirmed": "Confirmed",
            "in_progress": "Packed",
            "completed": "Delivered",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Collection",
        "category_label": "Clothing Category",
        "item_label": "Item",
    },
    "default_modules": {},
}
