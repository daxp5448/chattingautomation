"""Restaurant niche template -- the `action_type="order"` proof niche (cart + payment)
for the generic conversation engine (see app/services/generic_flow_engine.py, whose
module docstring and step-shape contract this file's `default_flow_steps` implements
exactly). This is a NEW business template on the generic engine and is completely
independent of the legacy, restaurant-only app/services/flow_engine.py path Prince
Corner (and any other Restaurant.uses_generic_engine=False business) runs on -- see that
module's docstring for why no code or state is shared between the two.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_restaurant.py for an end-to-end proof this drives a real
conversation through the real engine, including cart, checkout, and a Razorpay payment
link.

Order-flow shape (context keys a completed order's Engagement.details carries):
  category_id -> item_id (via pending_item, not a bare capture_key) -> qty -> cart
  (list of {item_id, name, price, qty}) -> delivery_address (+ optional coords) ->
  cart_summary/cart_total (recomputed by the engine's add_to_cart/remove_cart_line verbs
  after every cart mutation -- see generic_flow_engine.py::_Engine._refresh_cart_summary).
`create_engagement` reads its EngagementType off the FlowDefinition itself (not off any
step) and sets requires_payment=True automatically whenever the cart is non-empty.

The welcome menu routes straight to a single primary action (no redundant second button
pointing at the same category_select destination), plus a direct "View Cart" entry (so
the cart is reachable without walking the full browse chain -- reuses the existing
cart_menu step unchanged) and a "Talk to a Human" entry using the engine's
human_handoff step type (see generic_flow_engine.py's HUMAN_HANDOFF handling), which no
niche used before this redesign.
"""

from app.niche_seeds._media import demo_image_base


_DEMO_IMG_BASE = demo_image_base("restaurant")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_STARTERS = f"{_DEMO_IMG_BASE}/starters.jpg"
_IMG_MAIN_COURSE = f"{_DEMO_IMG_BASE}/main_course.jpg"
_IMG_BEVERAGES = f"{_DEMO_IMG_BASE}/beverages.jpg"
_IMG_DESSERTS = f"{_DEMO_IMG_BASE}/desserts.jpg"

_WELCOME_TEXT = "\U0001f37d *Welcome to {{business_name}}!*\nOrder your favourites in seconds."


TEMPLATE = {
    "code": "restaurant",
    "name": "Restaurant",
    "action_type": "order",
    "icon": "\U0001f37d",  # 🍽
    "welcome_message": _WELCOME_TEXT,
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:order", "title": "\U0001f6d2 Order Now"},
        {"id": "welcome:cart", "title": "\U0001f6d2 View Cart"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Starters",
            "icon_image": _IMG_STARTERS,
            "items": [
                {
                    "name": "Paneer Tikka",
                    "description": "Char-grilled cottage cheese with house spices. Veg · Medium spice.",
                    "price": 220,
                    "price_type": "fixed",
                    "images": [_IMG_STARTERS],
                    "attributes": {"veg": True, "spice_level": "medium"},
                },
                {
                    "name": "Chicken Seekh Kebab",
                    "description": "Minced chicken skewers, smoky tandoor finish. Non-veg · Medium spice.",
                    "price": 260,
                    "price_type": "fixed",
                    "images": [_IMG_STARTERS],
                    "attributes": {"veg": False, "spice_level": "medium"},
                },
            ],
        },
        {
            "name": "Main Course",
            "icon_image": _IMG_MAIN_COURSE,
            "items": [
                {
                    "name": "Butter Chicken",
                    "description": "Slow-cooked chicken in a rich tomato-butter gravy. Non-veg · Mild.",
                    "price": 380,
                    "price_type": "fixed",
                    "images": [_IMG_MAIN_COURSE],
                    "attributes": {"veg": False, "spice_level": "mild"},
                },
                {
                    "name": "Dal Makhani",
                    "description": "Slow-simmered black lentils finished with cream. Veg · Mild.",
                    "price": 260,
                    "price_type": "fixed",
                    "images": [_IMG_MAIN_COURSE],
                    "attributes": {"veg": True, "spice_level": "mild"},
                },
                {
                    "name": "Veg Biryani",
                    "description": "Fragrant basmati rice layered with garden vegetables. Veg · Medium spice.",
                    "price": 240,
                    "price_type": "fixed",
                    "images": [_IMG_MAIN_COURSE],
                    "attributes": {"veg": True, "spice_level": "medium"},
                },
            ],
        },
        {
            "name": "Beverages",
            "icon_image": _IMG_BEVERAGES,
            "items": [
                {
                    "name": "Masala Chaas",
                    "description": "Spiced buttermilk, served chilled. Veg.",
                    "price": 60,
                    "price_type": "fixed",
                    "images": [_IMG_BEVERAGES],
                    "attributes": {"veg": True},
                },
                {
                    "name": "Fresh Lime Soda",
                    "description": "Sweet, salted, or mixed -- your choice. Veg.",
                    "price": 80,
                    "price_type": "fixed",
                    "images": [_IMG_BEVERAGES],
                    "attributes": {"veg": True},
                },
            ],
        },
        {
            "name": "Desserts",
            "icon_image": _IMG_DESSERTS,
            "items": [
                {
                    "name": "Gulab Jamun (2 pcs)",
                    "description": "Warm milk-solid dumplings in sugar syrup. Veg.",
                    "price": 120,
                    "price_type": "fixed",
                    "images": [_IMG_DESSERTS],
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
            "prompt": _WELCOME_TEXT,
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:order", "title": "\U0001f6d2 Order Now"},
                {"id": "welcome:cart", "title": "\U0001f6d2 View Cart"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
                {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
            ],
            "routes": {
                "welcome:order": "category_select",
                "welcome:cart": "cart_menu",
                "welcome:offers": "offers_info",
                "welcome:location": "location_info",
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
            "prompt": "\U0001f381 *Today's Offers*\n\nAsk our team about today's specials and combo offers any time you order!",
            "back_target": "welcome",
        },
        {
            "step_id": "location_info",
            "type": "message",
            "prompt": (
                "\U0001f4cd *{{business_name}}*\n\n[Address will appear here once the business "
                "adds it in Settings.]\n\nTap \U0001f9d1 Talk to a Human if you'd like directions right now."
            ),
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": (
                "\U0001f4de *{{business_name}}*\n\n\U0001f4de Phone: [add your number in Settings]\n"
                "\U0001f550 Hours: [add your hours in Settings]\n\n"
                "Or tap \U0001f9d1 Talk to a Human from the main menu to chat with our team right now."
            ),
            "back_target": "welcome",
        },
        {
            "step_id": "human_handoff",
            "type": "human_handoff",
            "message": "\U0001f9d1 Connecting you with our team at *{{business_name}}* -- someone will reply here shortly.",
            "back_target": "welcome",
        },
        {
            # "Order Now" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f37d What would you like to order from?",
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
            "prompt": "Here's our *{{category_id_label}}* menu -- tap an item to add it:",
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
            "prompt": "How many *{{pending_item_name}}* would you like?\n\n\U0001f3f7️ *Price:* {{pending_item_price}} each",
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
            "prompt": "\U0001f6d2 *Your Cart*\n\n{{cart_summary}}\n\n\U0001f4b0 *Total: {{currency}} {{cart_total}}*\n\nWhat would you like to do next?",
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
            # skippable for dine-in/pickup. [Back -> Cart menu]
            "step_id": "address_capture",
            "type": "free_text_input",
            "prompt": "\U0001f4cd Please share your delivery address (or tap Skip for dine-in/pickup):",
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
                "\U0001f9fe *Review Your Order*\n\n"
                "{{cart_summary}}\n\n"
                "\U0001f4b0 *Total: {{currency}} {{cart_total}}*\n"
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
            # real Razorpay payment link whenever the cart total is non-zero -- see
            # app/services/payment/generic_razorpay.py); notify_business() (called
            # unconditionally inside create_engagement) notifies staff. Flow complete --
            # terminal, no Back.
            "step_id": "order_confirmed",
            "type": "message",
            "prompt": (
                "✅ *Order placed!* Reference: {{last_reference_number}}\n\n"
                "\U0001f4b0 *Total: {{currency}} {{last_total}}*\n"
                "{{payment_link_url}}\n\n"
                "We'll start preparing your order right away -- thank you for choosing "
                "*{{business_name}}*!"
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "Received",
            "confirmed": "Confirmed",
            "in_progress": "Preparing",
            "completed": "Delivered",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Menu",
        "category_label": "Menu Category",
        "item_label": "Dish",
    },
    "default_modules": {},
}
