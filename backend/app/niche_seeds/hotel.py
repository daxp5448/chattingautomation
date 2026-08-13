"""Hotel / Guesthouse niche template -- the `action_type="booking"` proof niche
(date-range stay: check-in -> check-out, priced by nights) for the generic conversation
engine (see app/services/generic_flow_engine.py, whose module docstring and step-shape
contract this file's `default_flow_steps` implements exactly).

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- a super-admin
seed script constructs a `NicheTemplate(**TEMPLATE)` row from this dict (after coercing
`action_type` to the `EngagementType` enum), and app/services/niche_provisioning.py
copies it into a brand-new business's own catalog_categories/catalog_items/flow_definitions
rows at creation time. See app/tests/test_niche_hotel.py for an end-to-end proof this
actually drives a real conversation through the real engine.

Booking-flow shape (context keys a completed booking's Engagement.details carries):
  category_id -> item_id (via pending_item, captured by "capture_pending_item" on the
  room_select step, same as Restaurant's item_select) -> check_in -> check_out -> guests
  -> cart (built in one shot by the "add_to_cart_for_date_range" action on the
  guests_select step, once room + both dates are known -- see
  generic_flow_engine.py::_run_action's add_to_cart_for_date_range branch) ->
  cart_summary/cart_total/nights (recomputed by that same action -- see
  _Engine._refresh_cart_summary), plus an optional customer_name_override.
Each room's `price` in `default_catalog` below is a PER-NIGHT rate; the cart line's
`qty` is set to the number of nights, so `create_engagement`'s
`subtotal = sum(line["price"] * line["qty"] for line in cart)` naturally comes out as
nights x per-night rate -- the exact same cart-subtotal logic Restaurant's order flow
uses, just with a single line. `create_engagement` reads its EngagementType off the
FlowDefinition itself (not off any step) and sets requires_payment=True automatically
whenever the cart is non-empty (always true here, since a booking always has one room
line), so a real Razorpay payment-link attempt is made exactly like Restaurant's order
flow -- see app/services/payment/generic_razorpay.py's docstring for why the terminal
message below only ever says a link was sent, never that payment succeeded.

There is no staff/time-slot selection anywhere in this flow -- those are appointment-only
concepts (Salon). Checkout date options are constrained to strictly after check-in via
`after_context_key` on the checkout_select step (see _resolve_options's `source ==
"dates"` branch), not by any code added here.
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
_DEMO_IMG_BASE = demo_image_base("hotel")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_STANDARD = f"{_DEMO_IMG_BASE}/standard.jpg"
_IMG_DELUXE = f"{_DEMO_IMG_BASE}/deluxe.jpg"
_IMG_SUITES = f"{_DEMO_IMG_BASE}/suites.jpg"
_IMG_FAMILY = f"{_DEMO_IMG_BASE}/family.jpg"


TEMPLATE = {
    "code": "hotel",
    "name": "Hotel & Guesthouse",
    "action_type": "booking",
    "icon": "\U0001f3e8",  # 🏨
    "welcome_message": "\U0001f3e8 Welcome to [Business Name]! Book your stay in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:book", "title": "\U0001f6cf Book a Room"},
        {"id": "welcome:offers", "title": "\U0001f389 Offers"},
        {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Hotel"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Standard Rooms",
            "icon_image": _IMG_STANDARD,
            "items": [
                {
                    "name": "Standard Twin Room",
                    "description": "Cozy twin room with two single beds, sleeps up to 2 guests. Free WiFi & breakfast included.",
                    "price": 2500,
                    "price_type": "fixed",
                    "images": [_IMG_STANDARD],
                    "attributes": {"max_occupancy": 2, "bed_type": "Twin"},
                },
                {
                    "name": "Standard Double Room",
                    "description": "Comfortable double-bed room, sleeps up to 2 guests. Free WiFi & breakfast included.",
                    "price": 2800,
                    "price_type": "fixed",
                    "images": [_IMG_STANDARD],
                    "attributes": {"max_occupancy": 2, "bed_type": "Double"},
                },
            ],
        },
        {
            "name": "Deluxe Rooms",
            "icon_image": _IMG_DELUXE,
            "items": [
                {
                    "name": "Deluxe Room",
                    "description": "Spacious deluxe room with city view, sleeps up to 3 guests. Free WiFi, breakfast & minibar included.",
                    "price": 4500,
                    "price_type": "fixed",
                    "images": [_IMG_DELUXE],
                    "attributes": {"max_occupancy": 3, "bed_type": "Queen"},
                },
                {
                    "name": "Deluxe Balcony Room",
                    "description": "Deluxe room with a private balcony and city view, sleeps up to 3 guests. Free WiFi, breakfast & minibar included.",
                    "price": 5200,
                    "price_type": "fixed",
                    "images": [_IMG_DELUXE],
                    "attributes": {"max_occupancy": 3, "bed_type": "Queen"},
                },
            ],
        },
        {
            "name": "Suites",
            "icon_image": _IMG_SUITES,
            "items": [
                {
                    "name": "Executive Suite",
                    "description": "Separate living area and king bed, sleeps up to 3 guests. Free WiFi, breakfast, minibar & airport pickup included.",
                    "price": 8500,
                    "price_type": "fixed",
                    "images": [_IMG_SUITES],
                    "attributes": {"max_occupancy": 3, "bed_type": "King"},
                },
                {
                    "name": "Presidential Suite",
                    "description": "Our largest suite -- private lounge, king bed & jacuzzi, sleeps up to 4 guests. All amenities plus a dedicated butler.",
                    "price": 12000,
                    "price_type": "fixed",
                    "images": [_IMG_SUITES],
                    "attributes": {"max_occupancy": 4, "bed_type": "King"},
                },
            ],
        },
        {
            "name": "Family Rooms",
            "icon_image": _IMG_FAMILY,
            "items": [
                {
                    "name": "Family Room",
                    "description": "Two queen beds, ideal for families, sleeps up to 4 guests. Free WiFi & breakfast included.",
                    "price": 6000,
                    "price_type": "fixed",
                    "images": [_IMG_FAMILY],
                    "attributes": {"max_occupancy": 4, "bed_type": "Two Queen"},
                },
                {
                    "name": "Family Suite",
                    "description": "Two connecting rooms with four queen beds, ideal for larger families, sleeps up to 6 guests. Free WiFi & breakfast included.",
                    "price": 9000,
                    "price_type": "fixed",
                    "images": [_IMG_FAMILY],
                    "attributes": {"max_occupancy": 6, "bed_type": "Four Queen"},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map onto a
    # 9-step spec (welcome -> category -> room -> check-in -> check-out -> guests -> name
    # confirm -> booking confirm -> confirmed), plus three simple side-branch "message"
    # steps off the welcome menu (Offers / Location / Contact) that don't lead into the
    # booking chain.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f3e8 Welcome to {{restaurant_name}}! Book your stay in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:book", "title": "\U0001f6cf Book a Room"},
                {"id": "welcome:offers", "title": "\U0001f389 Offers"},
                {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Hotel"},
                {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
            ],
            "routes": {
                "welcome:book": "category_select",
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
            "step_id": "human_handoff",
            "type": "human_handoff",
            "message": "\U0001f9d1 Connecting you with our team at {{business_name}} -- someone will reply here shortly.",
            "back_target": "welcome",
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f389 Ask our front desk about current seasonal offers and long-stay discounts any time you book!",
            "back_target": "welcome",
        },
        {
            "step_id": "location_info",
            "type": "message",
            "prompt": "\U0001f4cd You'll find {{restaurant_name}} details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de You can reach {{restaurant_name}}'s front desk right here on WhatsApp any time.",
            "back_target": "welcome",
        },
        {
            # Spec step 2: "Book a Room"/"View Rooms" tapped -> Category list.
            # [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "Which type of room would you like to book?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "room_select",
            "show_image": True,
            "section_title": "Room Types",
        },
        {
            # Spec step 3: Category tapped -> Room list (name + per-night price, tap =
            # select a pending room). [Back -> Category list]
            "step_id": "room_select",
            "type": "menu_select",
            "prompt": "Here are our {{category_id_label}} -- tap one to select:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "action": "capture_pending_item",
            "back_target": "category_select",
            "next": "checkin_select",
            "show_image": True,
            "section_title": "Rooms",
        },
        {
            # Spec step 4: Check-in date buttons -- Today / Tomorrow / pick a date.
            # [Back -> Room list]
            "step_id": "checkin_select",
            "type": "menu_select",
            "prompt": "Great choice -- *{{pending_item_name}}* ({{pending_item_price}}/night). When would you like to check in?",
            "buttons_from": "dates",
            "capture_key": "check_in",
            "back_target": "room_select",
            "next": "checkout_select",
            "show_image": False,
        },
        {
            # Spec step 5: Check-out date buttons -- only dates strictly after check-in
            # are offered (after_context_key). [Back -> check-in buttons]
            "step_id": "checkout_select",
            "type": "menu_select",
            "prompt": "Checking in on *{{check_in_label}}*. When would you like to check out?",
            "buttons_from": "dates",
            "after_context_key": "check_in",
            "capture_key": "check_out",
            "back_target": "checkin_select",
            "next": "guests_select",
            "show_image": False,
        },
        {
            # Spec step 6: Guest count -> the room is actually added to the cart here,
            # priced by nights (add_to_cart_for_date_range needs both dates + the pending
            # room, both already in context by this point). [Back -> check-out buttons]
            "step_id": "guests_select",
            "type": "menu_select",
            "prompt": "How many guests will be staying?",
            "buttons_from": "static",
            "static_options": [
                {"id": "guests:1", "title": "1 Guest"},
                {"id": "guests:2", "title": "2 Guests"},
                {"id": "guests:3", "title": "3 Guests"},
                {"id": "guests:4plus", "title": "4+ Guests"},
            ],
            "capture_key": "guests",
            "action": "add_to_cart_for_date_range",
            "back_target": "checkout_select",
            "next": "name_confirm",
            "show_image": False,
        },
        {
            # Spec step 7: Name confirmation, auto-pulled from the WhatsApp profile and
            # editable via a button. [Back -> guest count]
            "step_id": "name_confirm",
            "type": "menu_select",
            "prompt": "Please confirm the name for this booking: *{{customer_name}}*",
            "buttons_from": "static",
            "static_options": [
                {"id": "name:confirm", "title": "Looks Good"},
                {"id": "name:edit", "title": "Edit Name"},
            ],
            "routes": {
                "name:confirm": "booking_confirm",
                "name:edit": "name_edit",
            },
            "next": "booking_confirm",
            "back_target": "guests_select",
            "show_image": False,
        },
        {
            "step_id": "name_edit",
            "type": "free_text_input",
            "prompt": "Please type the name we should use for this booking:",
            "capture_key": "customer_name_override",
            "allow_skip": False,
            "next": "booking_confirm",
            "back_target": "name_confirm",
        },
        {
            # Spec step 8: Booking confirmation card (room, check-in, check-out, nights,
            # guests, total) -> "Confirm Booking" button. [Back -> name confirmation]
            "step_id": "booking_confirm",
            "type": "confirm_action",
            "prompt": (
                "Please review your stay:\n\n"
                "{{cart_summary}}\n\n"
                "\U0001f4c5 Check-in: {{check_in_label}}\n"
                "\U0001f4c5 Check-out: {{check_out_label}}\n"
                "\U0001f319 Nights: {{nights}}\n"
                "\U0001f465 Guests: {{guests_label}}\n"
                "Total: {{currency}} {{cart_total}}\n\n"
                "Tap below to confirm."
            ),
            "buttons_from": "static",
            "static_options": [{"id": "booking:confirm", "title": "Confirm Booking"}],
            "action": "create_engagement",
            "back_target": "name_confirm",
            "next": "booking_confirmed",
            "show_image": False,
        },
        {
            # Spec step 9: Confirmed -> confirmation message + payment link (
            # create_engagement generates a real Razorpay payment link whenever the cart
            # total is non-zero -- see app/services/payment/generic_razorpay.py; never
            # claims the payment itself succeeded, only that a link was sent);
            # notify_business() (called unconditionally inside create_engagement)
            # notifies staff. Flow complete -- terminal, no Back.
            "step_id": "booking_confirmed",
            "type": "message",
            "prompt": (
                "✅ Your booking is confirmed! Reference: {{last_reference_number}}.\n\n"
                "Total: {{currency}} {{last_total}}\n"
                "{{payment_link_url}}\n\n"
                "We look forward to hosting you at {{restaurant_name}}!"
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "Requested",
            "confirmed": "Confirmed",
            "in_progress": "Checked In",
            "completed": "Checked Out",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Rooms",
        "category_label": "Room Type",
        "item_label": "Room",
        "staff_label": "Staff",
    },
    "default_modules": {},
}
