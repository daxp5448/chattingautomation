"""Retail / Fashion / Boutique niche template -- a second `action_type="order"` niche
(cart + quantity + checkout + payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). This is a straight re-skin of the proven
Restaurant order-flow template (app/niche_seeds/restaurant.py) onto apparel/footwear/
accessories catalog and copy -- no new engine capability is required.

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
_DEMO_IMG_BASE = demo_image_base("retail")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_MENS = f"{_DEMO_IMG_BASE}/mens.jpg"
_IMG_WOMENS = f"{_DEMO_IMG_BASE}/womens.jpg"
_IMG_FOOTWEAR = f"{_DEMO_IMG_BASE}/footwear.jpg"
_IMG_ACCESSORIES = f"{_DEMO_IMG_BASE}/accessories.jpg"


TEMPLATE = {
    "code": "retail",
    "name": "Retail & Fashion",
    "action_type": "order",
    "icon": "\U0001f455",  # 👕
    "welcome_message": "\U0001f455 Welcome to [Business Name]! Shop the latest styles in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:shop", "title": "\U0001f6cd️ Shop Now"},
        {"id": "welcome:new", "title": "✨ New Arrivals"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:store", "title": "\U0001f3ea Our Store"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
    ],
    "default_catalog": [
        {
            "name": "Men's Wear",
            "icon_image": _IMG_MENS,
            "items": [
                {
                    "name": "Casual Shirt",
                    "description": "Breathable cotton shirt for everyday wear.",
                    "price": 899,
                    "price_type": "fixed",
                    "images": [_IMG_MENS],
                    "attributes": {"category": "men", "sizes": ["S", "M", "L", "XL"]},
                },
                {
                    "name": "Formal Trousers",
                    "description": "Tailored fit trousers, perfect for office wear.",
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
                    "description": "Lightweight rayon kurti with block print detailing.",
                    "price": 799,
                    "price_type": "fixed",
                    "images": [_IMG_WOMENS],
                    "attributes": {"category": "women", "sizes": ["S", "M", "L", "XL"]},
                },
                {
                    "name": "Party Dress",
                    "description": "Flowy evening dress with a flattering silhouette.",
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
                    "description": "Cushioned everyday sneakers with a grippy sole.",
                    "price": 1999,
                    "price_type": "fixed",
                    "images": [_IMG_FOOTWEAR],
                    "attributes": {"category": "footwear", "sizes": ["7", "8", "9", "10"]},
                },
                {
                    "name": "Sandals",
                    "description": "Comfortable everyday sandals, easy slip-on fit.",
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
            "prompt": "\U0001f455 Welcome to {{restaurant_name}}! Shop the latest styles in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:shop", "title": "\U0001f6cd️ Shop Now"},
                {"id": "welcome:new", "title": "✨ New Arrivals"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:store", "title": "\U0001f3ea Our Store"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
            ],
            "routes": {
                "welcome:shop": "category_select",
                "welcome:new": "category_select",
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
            "prompt": "\U0001f381 Ask our team about today's seasonal discounts and combo offers any time you shop!",
            "back_target": "welcome",
        },
        {
            "step_id": "store_info",
            "type": "message",
            "prompt": "\U0001f3ea You'll find {{restaurant_name}} details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de You can reach {{restaurant_name}} right here on WhatsApp any time.",
            "back_target": "welcome",
        },
        {
            # Step 2: "Shop Now"/"New Arrivals" tapped -> Category list. [Back -> Welcome]
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
            # Step 6: Delivery address -- free text or native WhatsApp location share,
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
            "in_progress": "Packed",
            "completed": "Delivered",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Collection",
        "category_label": "Category",
        "item_label": "Item",
        "staff_label": "Staff",
    },
    "default_modules": {},
}
