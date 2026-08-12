"""Electronics & Mobile Store niche template -- an `action_type="order"` niche (cart +
quantity + checkout + payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). This is a re-skin of the proven Restaurant
template (app/niche_seeds/restaurant.py) -- same flow shape, electronics content.

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
_DEMO_IMG_BASE = demo_image_base("electronics")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_SMARTPHONES = f"{_DEMO_IMG_BASE}/smartphones.jpg"
_IMG_LAPTOPS = f"{_DEMO_IMG_BASE}/laptops.jpg"
_IMG_ACCESSORIES = f"{_DEMO_IMG_BASE}/accessories.jpg"
_IMG_APPLIANCES = f"{_DEMO_IMG_BASE}/appliances.jpg"


TEMPLATE = {
    "code": "electronics",
    "name": "Electronics & Mobile Store",
    "action_type": "order",
    "icon": "\U0001f4f1",  # 📱
    "welcome_message": "\U0001f4f1 Welcome to [Business Name]! Shop the latest electronics in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:shop", "title": "\U0001f6d2 Shop Now"},
        {"id": "welcome:catalog", "title": "\U0001f4f1 Browse Catalog"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:store", "title": "\U0001f3ec Our Store"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
    ],
    "default_catalog": [
        {
            "name": "Smartphones",
            "icon_image": _IMG_SMARTPHONES,
            "items": [
                {
                    "name": "Smartphone X100",
                    "description": "6.7in AMOLED display, 5G, 128GB storage, triple camera.",
                    "price": 15999,
                    "price_type": "fixed",
                    "images": [_IMG_SMARTPHONES],
                    "attributes": {"brand": "Voltex", "warranty_months": 12},
                },
                {
                    "name": "Smartphone Lite",
                    "description": "Budget-friendly 6.1in display, 64GB storage, dual camera.",
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
                    "description": "14in Retina-class display, 16GB RAM, 512GB SSD.",
                    "price": 54999,
                    "price_type": "fixed",
                    "images": [_IMG_LAPTOPS],
                    "attributes": {"brand": "Nexbook", "warranty_months": 24},
                },
                {
                    "name": "Laptop Air 13",
                    "description": "13in ultralight design, 8GB RAM, 256GB SSD.",
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
                    "description": "Active noise cancellation, 30hr battery with case.",
                    "price": 1999,
                    "price_type": "fixed",
                    "images": [_IMG_ACCESSORIES],
                    "attributes": {"brand": "Voltex", "warranty_months": 6},
                },
                {
                    "name": "Power Bank 10K",
                    "description": "10000mAh fast-charging power bank, dual USB output.",
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
                    "description": "43in 4K UHD smart TV with built-in streaming apps.",
                    "price": 22999,
                    "price_type": "fixed",
                    "images": [_IMG_APPLIANCES],
                    "attributes": {"brand": "Nexbook", "warranty_months": 12},
                },
                {
                    "name": "Air Fryer",
                    "description": "4L digital air fryer with 8 preset cooking modes.",
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
            "prompt": "\U0001f4f1 Welcome to {{restaurant_name}}! Shop the latest electronics in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:shop", "title": "\U0001f6d2 Shop Now"},
                {"id": "welcome:catalog", "title": "\U0001f4f1 Browse Catalog"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:store", "title": "\U0001f3ec Our Store"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
            ],
            "routes": {
                "welcome:shop": "category_select",
                "welcome:catalog": "category_select",
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
            "prompt": "\U0001f381 Ask our team about today's deals and bundle offers any time you shop!",
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
            # Step 2: "Shop Now"/"Browse Catalog" tapped -> Category list. [Back -> Welcome]
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
            # generates a real payment link whenever the cart total is non-zero -- see
            # app/services/payment/generic_razorpay.py); notify_business() (called
            # unconditionally inside create_engagement) notifies staff. Flow complete --
            # terminal, no Back.
            "step_id": "order_confirmed",
            "type": "message",
            "prompt": (
                "✅ Order placed! Reference: {{last_reference_number}}.\n\n"
                "Total: {{currency}} {{last_total}}\n"
                "{{payment_link_url}}\n\n"
                "We'll get your order ready right away. Thank you for shopping with "
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
            "in_progress": "Processing",
            "completed": "Delivered",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Catalog",
        "category_label": "Category",
        "item_label": "Item",
        "staff_label": "Staff",
    },
    "default_modules": {},
}
