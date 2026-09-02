"""Electronics & Mobile Store niche template -- an `action_type="order"` niche (cart +
quantity + checkout + payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). Shares the Restaurant order-flow shape
(app/niche_seeds/restaurant.py) -- same flow shape, electronics content.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_electronics.py for an end-to-end proof this drives a real
conversation through the real engine, including cart, checkout, and a payment link.

Order-flow shape (context keys a completed order's Engagement.details carries):
  category_id -> item_id (via pending_item, not a bare capture_key) -> qty -> cart
  (list of {item_id, name, price, qty}) -> delivery_address (+ optional coords) ->
  cart_summary/cart_total (recomputed by the engine's add_to_cart/remove_cart_line verbs
  after every cart mutation -- see generic_flow_engine.py::_Engine._refresh_cart_summary).
`create_engagement` reads its EngagementType off the FlowDefinition itself (not off any
step) and sets requires_payment=True automatically whenever the cart is non-empty.

Brand/warranty are carried in each item's `attributes` JSON bag for admin/API use, but
surfaced to the customer via each item's plain `description` field -- the shared
engine's `_price_label` `include_attributes` special-case only understands
`duration_minutes` (a salon-specific concept), so this is the zero-engine-change way to
make brand/warranty visible in the item list. "Compare products" and "EMI" from the
product brief are NOT implemented here -- both need a comparison renderer / financing
data provider the engine doesn't have yet; deferred rather than faked.
"""

from app.niche_seeds._media import demo_image_base


_DEMO_IMG_BASE = demo_image_base("electronics")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_SMARTPHONES = f"{_DEMO_IMG_BASE}/smartphones.jpg"
_IMG_LAPTOPS = f"{_DEMO_IMG_BASE}/laptops.jpg"
_IMG_ACCESSORIES = f"{_DEMO_IMG_BASE}/accessories.jpg"
_IMG_APPLIANCES = f"{_DEMO_IMG_BASE}/appliances.jpg"

_WELCOME_TEXT = "\U0001f4f1 *Welcome to {{business_name}}!*\n\nShop the latest electronics in seconds."


TEMPLATE = {
    "code": "electronics",
    "name": "Electronics & Mobile Store",
    "action_type": "order",
    "icon": "\U0001f4f1",  # 📱
    "welcome_message": _WELCOME_TEXT,
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:shop", "title": "\U0001f6d2 Shop Now"},
        {"id": "welcome:cart", "title": "\U0001f6d2 View Cart"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:store", "title": "\U0001f3ec Our Store"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Smartphones",
            "icon_image": _IMG_SMARTPHONES,
            "items": [
                {
                    "name": "Smartphone X100",
                    "description": "6.7in AMOLED display, 5G, 128GB storage, triple camera. Voltex · 12-month warranty.",
                    "price": 15999,
                    "price_type": "fixed",
                    "images": [_IMG_SMARTPHONES],
                    "attributes": {"brand": "Voltex", "warranty_months": 12},
                },
                {
                    "name": "Smartphone Lite",
                    "description": "Budget-friendly 6.1in display, 64GB storage, dual camera. Voltex · 12-month warranty.",
                    "price": 9999,
                    "price_type": "fixed",
                    "images": [_IMG_SMARTPHONES],
                    "attributes": {"brand": "Voltex", "warranty_months": 12},
                },
            ],
        },
        {
            "name": "Laptops",
            "icon_image": _IMG_LAPTOPS,
            "items": [
                {
                    "name": "Laptop Pro 14",
                    "description": "14in Retina-class display, 16GB RAM, 512GB SSD. Nexbook · 24-month warranty.",
                    "price": 54999,
                    "price_type": "fixed",
                    "images": [_IMG_LAPTOPS],
                    "attributes": {"brand": "Nexbook", "warranty_months": 24},
                },
                {
                    "name": "Laptop Air 13",
                    "description": "13in ultralight design, 8GB RAM, 256GB SSD. Nexbook · 24-month warranty.",
                    "price": 42999,
                    "price_type": "fixed",
                    "images": [_IMG_LAPTOPS],
                    "attributes": {"brand": "Nexbook", "warranty_months": 24},
                },
            ],
        },
        {
            "name": "Accessories",
            "icon_image": _IMG_ACCESSORIES,
            "items": [
                {
                    "name": "Wireless Earbuds",
                    "description": "Active noise cancellation, 30hr battery with case. Voltex · 6-month warranty.",
                    "price": 1999,
                    "price_type": "fixed",
                    "images": [_IMG_ACCESSORIES],
                    "attributes": {"brand": "Voltex", "warranty_months": 6},
                },
                {
                    "name": "Power Bank 10K",
                    "description": "10000mAh fast-charging power bank, dual USB output. Voltex · 6-month warranty.",
                    "price": 899,
                    "price_type": "fixed",
                    "images": [_IMG_ACCESSORIES],
                    "attributes": {"brand": "Voltex", "warranty_months": 6},
                },
            ],
        },
        {
            "name": "Home Appliances",
            "icon_image": _IMG_APPLIANCES,
            "items": [
                {
                    "name": "Smart TV 43in",
                    "description": "43in 4K UHD smart TV with built-in streaming apps. Nexbook · 12-month warranty.",
                    "price": 22999,
                    "price_type": "fixed",
                    "images": [_IMG_APPLIANCES],
                    "attributes": {"brand": "Nexbook", "warranty_months": 12},
                },
                {
                    "name": "Air Fryer",
                    "description": "4L digital air fryer with 8 preset cooking modes. Nexbook · 12-month warranty.",
                    "price": 4499,
                    "price_type": "fixed",
                    "images": [_IMG_APPLIANCES],
                    "attributes": {"brand": "Nexbook", "warranty_months": 12},
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
                {"id": "welcome:shop", "title": "\U0001f6d2 Shop Now"},
                {"id": "welcome:cart", "title": "\U0001f6d2 View Cart"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:store", "title": "\U0001f3ec Our Store"},
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
            "prompt": "\U0001f381 *Offers*\n\nAsk our team about today's deals and bundle offers any time you shop!",
            "back_target": "welcome",
        },
        {
            "step_id": "store_info",
            "type": "message",
            "prompt": (
                "\U0001f3ec *{{business_name}}*\n\n[Address will appear here once the business "
                "adds it in Settings.]\n\nTap \U0001f9d1 Talk to a Human if you'd like directions right now."
            ),
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": (
                "\U0001f4de *{{business_name}}*\n\n\U0001f4f1 Phone: [add your number in Settings]\n"
                "\U0001f552 Hours: [add your hours in Settings]\n\n"
                "Or tap \U0001f9d1 Talk to a Human from the main menu to chat with our team right now."
            ),
            "back_target": "welcome",
        },
        {
            "step_id": "human_handoff",
            "type": "human_handoff",
            "message": "\U0001f9d1 *Connecting you with our team*\n\nSomeone at {{business_name}} will reply here shortly.",
            "back_target": "welcome",
        },
        {
            # "Shop Now" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f4f1 *What would you like to shop for?*",
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
            "prompt": "\U0001f4f1 *{{category_id_label}}*\n\nTap an item below to add it:",
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
            "prompt": "How many *{{pending_item_name}}* would you like?\n\n\U0001f3f7️ *Price:* {{pending_item_price}}",
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
            "prompt": "\U0001f6d2 *Your Cart*\n\n{{cart_summary}}\n\n\U0001f3f7️ *Total:* {{currency}} {{cart_total}}\n\nWhat next?",
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
            # skippable for in-store pickup. [Back -> Cart menu]
            "step_id": "address_capture",
            "type": "free_text_input",
            "prompt": "\U0001f4cd Please share your delivery address (or tap Skip for in-store pickup):",
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
                "\U0001f4cb *Please review your order:*\n\n"
                "{{cart_summary}}\n\n"
                "\U0001f3f7️ *Total:* {{currency}} {{cart_total}}\n"
                "\U0001f4cd *Delivery:* {{delivery_address}}\n\n"
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
            # real payment link whenever the cart total is non-zero -- see
            # app/services/payment/generic_razorpay.py); notify_business() (called
            # unconditionally inside create_engagement) notifies staff. Flow complete --
            # terminal, no Back.
            "step_id": "order_confirmed",
            "type": "message",
            "prompt": (
                "✅ *Order placed!*\n\n"
                "Reference: {{last_reference_number}}\n"
                "\U0001f3f7️ *Total:* {{currency}} {{last_total}}\n"
                "{{payment_link_url}}\n\n"
                "We'll get your order ready right away. Thank you for shopping with "
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
            "in_progress": "Processing",
            "completed": "Delivered",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Catalog",
        "category_label": "Product Category",
        "item_label": "Product",
    },
    "default_modules": {},
    "default_personality": {
        "tone": "knowledgeable_practical",
        "language": "auto",
        "emoji_level": "low",
        "response_length": "short",
        "business_personality": "electronics",
    },
}
