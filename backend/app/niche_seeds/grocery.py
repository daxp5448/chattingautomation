"""Grocery / Kirana Store niche template -- the `action_type="order"` niche (cart +
quantity + checkout + payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). This is a re-skin of the proven
Restaurant template (app/niche_seeds/restaurant.py) -- same flow shape, grocery content.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_grocery.py for an end-to-end proof this drives a real conversation
through the real engine, including a multi-item cart, checkout, and a Razorpay payment
link.

Order-flow shape (context keys a completed order's Engagement.details carries):
  category_id -> item_id (via pending_item, not a bare capture_key) -> qty -> cart
  (list of {item_id, name, price, qty}) -> delivery_address (+ optional coords) ->
  cart_summary/cart_total (recomputed by the engine's add_to_cart/remove_cart_line verbs
  after every cart mutation -- see generic_flow_engine.py::_Engine._refresh_cart_summary).
`create_engagement` reads its EngagementType off the FlowDefinition itself (not off any
step) and sets requires_payment=True automatically whenever the cart is non-empty.
"""

from app.niche_seeds._media import demo_image_base


_PLACEHOLDER = "https://placehold.co/{size}?text={text}"


def _img(size: str, text: str) -> str:
    return _PLACEHOLDER.format(size=size, text=text.replace(" ", "+").replace("&", "%26"))


# Real demo photos (Wikimedia Commons, free-licensed), uploaded to this deployment's own
# S3/MinIO bucket for a permanent (non-expiring) URL -- see
# backend/scripts/demo_asset_upload.py. The base URL comes from
# settings.PUBLIC_MEDIA_BASE_URL (see app/niche_seeds/_media.py) -- defaults to raw
# MinIO (only reachable from this machine); point it at a publicly-tunnelled URL or a
# real bucket before testing on a real WhatsApp number (same requirement GOING_LIVE.md
# documents for the webhook itself), then re-run sync_niche_templates once.
_DEMO_IMG_BASE = demo_image_base("grocery")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_VEGETABLES = f"{_DEMO_IMG_BASE}/vegetables.jpg"
_IMG_DAIRY = f"{_DEMO_IMG_BASE}/dairy.jpg"
_IMG_STAPLES = f"{_DEMO_IMG_BASE}/staples.jpg"
_IMG_SNACKS = f"{_DEMO_IMG_BASE}/snacks.jpg"


TEMPLATE = {
    "code": "grocery",
    "name": "Grocery & Kirana Store",
    "action_type": "order",
    "icon": "\U0001f6d2",  # 🛒
    "welcome_message": "\U0001f6d2 Welcome to [Business Name]! Get your daily groceries delivered fast.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:order", "title": "\U0001f6d2 Order Now"},
        {"id": "welcome:browse", "title": "\U0001f4e6 Browse Products"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:store", "title": "\U0001f3ec Our Store"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
    ],
    "default_catalog": [
        {
            "name": "Fruits & Vegetables",
            "icon_image": _IMG_VEGETABLES,
            "items": [
                {
                    "name": "Vegetable Pack",
                    "description": "Fresh seasonal vegetables, hand-picked daily.",
                    "price": 150,
                    "price_type": "fixed",
                    "images": [_IMG_VEGETABLES],
                    "attributes": {"veg": True},
                },
                {
                    "name": "Fruit Basket",
                    "description": "A mixed basket of fresh seasonal fruits.",
                    "price": 250,
                    "price_type": "fixed",
                    "images": [_IMG_VEGETABLES],
                    "attributes": {"veg": True},
                },
            ],
        },
        {
            "name": "Dairy & Bakery",
            "icon_image": _IMG_DAIRY,
            "items": [
                {
                    "name": "Milk 1L",
                    "description": "Fresh full-cream dairy milk, 1 litre pack.",
                    "price": 60,
                    "price_type": "fixed",
                    "images": [_IMG_DAIRY],
                    "attributes": {"veg": True},
                },
                {
                    "name": "Bread Loaf",
                    "description": "Soft white sandwich bread, freshly baked.",
                    "price": 40,
                    "price_type": "fixed",
                    "images": [_IMG_DAIRY],
                    "attributes": {"veg": True},
                },
            ],
        },
        {
            "name": "Staples & Grains",
            "icon_image": _IMG_STAPLES,
            "items": [
                {
                    "name": "Basmati Rice 5kg",
                    "description": "Premium long-grain basmati rice, 5kg bag.",
                    "price": 450,
                    "price_type": "fixed",
                    "images": [_IMG_STAPLES],
                    "attributes": {"veg": True},
                },
                {
                    "name": "Wheat Flour 5kg",
                    "description": "Stone-ground whole wheat atta, 5kg bag.",
                    "price": 250,
                    "price_type": "fixed",
                    "images": [_IMG_STAPLES],
                    "attributes": {"veg": True},
                },
            ],
        },
        {
            "name": "Snacks & Beverages",
            "icon_image": _IMG_SNACKS,
            "items": [
                {
                    "name": "Biscuits Pack",
                    "description": "Assorted glucose and cream biscuits pack.",
                    "price": 40,
                    "price_type": "fixed",
                    "images": [_IMG_SNACKS],
                    "attributes": {"veg": True},
                },
                {
                    "name": "Cold Drink 1L",
                    "description": "Chilled carbonated soft drink, 1 litre bottle.",
                    "price": 90,
                    "price_type": "fixed",
                    "images": [_IMG_SNACKS],
                    "attributes": {"veg": True},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f6d2 Welcome to {{restaurant_name}}! Get your daily groceries delivered fast.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:order", "title": "\U0001f6d2 Order Now"},
                {"id": "welcome:browse", "title": "\U0001f4e6 Browse Products"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:store", "title": "\U0001f3ec Our Store"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
            ],
            "routes": {
                "welcome:order": "category_select",
                "welcome:browse": "category_select",
                "welcome:offers": "offers_info",
                "welcome:store": "store_info",
                "welcome:contact": "contact_info",
            },
            "next": "category_select",
            "back_target": None,
            "show_image": True,
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f381 Ask our team about today's discounts and combo offers any time you order!",
            "back_target": "welcome",
        },
        {
            "step_id": "store_info",
            "type": "message",
            "prompt": "\U0001f3ec You'll find {{restaurant_name}} details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de You can reach {{restaurant_name}} right here on WhatsApp any time.",
            "back_target": "welcome",
        },
        {
            # Step 2: "Order Now"/"Browse Products" tapped -> Category list. [Back -> Welcome]
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
            # Step 3: Category tapped -> Item list (name + price, tap = select).
            # [Back -> Category list]
            "step_id": "item_select",
            "type": "menu_select",
            "prompt": "Here's our {{category_id_label}} range -- tap an item to add it:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "action": "capture_pending_item",
            "back_target": "category_select",
            "next": "quantity_select",
            "show_image": True,
            "section_title": "Items",
        },
        {
            # Step 4: Item tapped -> Quantity buttons (1/2/3/Custom), adds to cart.
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
            # Step 5: Cart menu -- Add More Items / Checkout. [Back -> Category list]
            "step_id": "cart_menu",
            "type": "menu_select",
            "prompt": "\U0001f6d2 Your cart so far:\n\n{{cart_summary}}\n\nTotal: {{currency}} {{cart_total}}\n\nWhat next?",
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
            # Step 6: Delivery address -- free text or native WhatsApp location share,
            # skippable for in-store pickup. [Back -> Cart menu]
            "step_id": "address_capture",
            "type": "free_text_input",
            "prompt": "Please share your delivery address (or tap Skip for in-store pickup):",
            "capture_key": "delivery_address",
            "allow_skip": True,
            "accepts_location": True,
            "back_target": "cart_menu",
            "next": "order_confirm",
        },
        {
            # Step 7: Order confirmation card (items, total, address) -> "Place Order".
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
            # Step 8: Confirmed -> confirmation + payment link (create_engagement
            # generates a real Razorpay payment link whenever the cart total is
            # non-zero -- see app/services/payment/generic_razorpay.py);
            # notify_business() (called unconditionally inside create_engagement)
            # notifies staff. Flow complete -- terminal, no Back.
            "step_id": "order_confirmed",
            "type": "message",
            "prompt": (
                "✅ Order placed! Reference: {{last_reference_number}}.\n\n"
                "Total: {{currency}} {{last_total}}\n"
                "{{payment_link_url}}\n\n"
                "We'll start packing your order right away. Thank you for shopping with "
                "{{restaurant_name}}!"
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "Received",
            "confirmed": "Confirmed",
            "in_progress": "Packing",
            "completed": "Delivered",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Products",
        "category_label": "Category",
        "item_label": "Product",
        "staff_label": "Staff",
    },
    "default_modules": {},
}
