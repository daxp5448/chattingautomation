"""Salon & Spa niche template -- the `action_type="appointment"` proof niche (staff
selection + date + time-slot booking) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly).

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- a super-admin
seed script constructs a `NicheTemplate(**TEMPLATE)` row from this dict (after coercing
`action_type` to the `EngagementType` enum), and app/services/niche_provisioning.py
copies it into a brand-new business's own catalog_categories/catalog_items/flow_definitions
rows at creation time. See app/tests/test_niche_salon.py for an end-to-end proof this
actually drives a real conversation through the real engine.

Booking-flow shape (context keys a completed booking's Engagement.details carries):
  category_id -> item_id -> staff_id -> date -> time, plus an optional
  customer_name_override if the customer edited the WhatsApp-profile-sourced name.
No cart/add_to_cart/capture_pending_item is used anywhere in this flow -- a service
booking has exactly one service, staff member, date and time, captured directly into
named context keys via each menu_select step's `capture_key`, then read back by the
final `confirm_action` step's `create_engagement` action (which reads its
EngagementType off the FlowDefinition itself, not off any step).
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
# documents for the webhook itself), then re-run sync_niche_templates once. Bridal Packages reuses the Makeup photo (no dedicated
# free bridal-makeup lead image was found) -- close enough for a demo catalog photo.
_DEMO_IMG_BASE = demo_image_base("salon")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_HAIRCUT = f"{_DEMO_IMG_BASE}/haircut.jpg"
_IMG_FACIAL = f"{_DEMO_IMG_BASE}/facial.jpg"
_IMG_BRIDAL = f"{_DEMO_IMG_BASE}/makeup.jpg"
_IMG_MASSAGE = f"{_DEMO_IMG_BASE}/massage.jpg"
_IMG_NAILS = f"{_DEMO_IMG_BASE}/nails.jpg"
_IMG_MAKEUP = f"{_DEMO_IMG_BASE}/makeup.jpg"


TEMPLATE = {
    "code": "salon",
    "name": "Salon & Spa",
    "action_type": "appointment",
    "icon": "\U0001f487",  # 💇
    "welcome_message": "\U0001f487 *Welcome to [Business Name]!*\nBook your appointment in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:book", "title": "\U0001f487 Book Appointment"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Salon"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Haircut & Styling",
            "icon_image": _IMG_HAIRCUT,
            "items": [
                {
                    "name": "Haircut",
                    "description": "Classic wash, cut and style.",
                    "price": 300,
                    "price_type": "fixed",
                    "images": [_IMG_HAIRCUT],
                    "attributes": {"duration_minutes": 30},
                },
                {
                    "name": "Hair Spa",
                    "description": "Deep-conditioning hair spa treatment.",
                    "price": 800,
                    "price_type": "fixed",
                    "images": [_IMG_HAIRCUT],
                    "attributes": {"duration_minutes": 45},
                },
            ],
        },
        {
            "name": "Facial & Skincare",
            "icon_image": _IMG_FACIAL,
            "items": [
                {
                    "name": "Gold Facial",
                    "description": "Radiance-boosting 24k gold facial.",
                    "price": 1200,
                    "price_type": "fixed",
                    "images": [_IMG_FACIAL],
                    "attributes": {"duration_minutes": 60},
                },
                {
                    "name": "Cleanup",
                    "description": "Quick refresh cleanup for everyday glow.",
                    "price": 500,
                    "price_type": "fixed",
                    "images": [_IMG_FACIAL],
                    "attributes": {"duration_minutes": 30},
                },
            ],
        },
        {
            "name": "Bridal Packages",
            "icon_image": _IMG_BRIDAL,
            "items": [
                {
                    "name": "Full Bridal Package",
                    "description": "Complete bridal look: hair, makeup, draping & touch-ups.",
                    "price": 15000,
                    "price_type": "fixed",
                    "images": [_IMG_BRIDAL],
                    "attributes": {"duration_minutes": 240},
                },
                {
                    "name": "Pre-Bridal Package",
                    "description": "Skin polishing, hair spa and mehendi prep sessions spread across the week before the wedding.",
                    "price": 9000,
                    "price_type": "fixed",
                    "images": [_IMG_BRIDAL],
                    "attributes": {"duration_minutes": 180},
                },
            ],
        },
        {
            "name": "Massage & Spa",
            "icon_image": _IMG_MASSAGE,
            "items": [
                {
                    "name": "Swedish Massage",
                    "description": "Full-body relaxation massage.",
                    "price": 1500,
                    "price_type": "fixed",
                    "images": [_IMG_MASSAGE],
                    "attributes": {"duration_minutes": 60},
                },
                {
                    "name": "Deep Tissue Massage",
                    "description": "Firm-pressure massage targeting muscle knots and chronic tension.",
                    "price": 1800,
                    "price_type": "fixed",
                    "images": [_IMG_MASSAGE],
                    "attributes": {"duration_minutes": 60},
                },
            ],
        },
        {
            "name": "Nail Care",
            "icon_image": _IMG_NAILS,
            "items": [
                {
                    "name": "Manicure",
                    "description": "Nail shaping, cuticle care and polish.",
                    "price": 400,
                    "price_type": "fixed",
                    "images": [_IMG_NAILS],
                    "attributes": {"duration_minutes": 30},
                },
                {
                    "name": "Pedicure",
                    "description": "Foot soak, scrub, and polish.",
                    "price": 500,
                    "price_type": "fixed",
                    "images": [_IMG_NAILS],
                    "attributes": {"duration_minutes": 40},
                },
            ],
        },
        {
            "name": "Makeup",
            "icon_image": _IMG_MAKEUP,
            "items": [
                {
                    "name": "Party Makeup",
                    "description": "Event-ready glam makeup.",
                    "price": 2000,
                    "price_type": "fixed",
                    "images": [_IMG_MAKEUP],
                    "attributes": {"duration_minutes": 60},
                },
                {
                    "name": "HD Makeup",
                    "description": "High-definition, long-lasting makeup for photography and video-ready looks.",
                    "price": 3500,
                    "price_type": "fixed",
                    "images": [_IMG_MAKEUP],
                    "attributes": {"duration_minutes": 75},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map 1:1 onto
    # the 9-step spec (welcome -> category -> service -> staff -> date -> time -> name
    # confirm -> booking confirm -> confirmed), plus three simple side-branch "message"
    # steps off the welcome menu (Offers / Location / Contact) that don't lead into the
    # booking chain.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f487 *Welcome to {{restaurant_name}}!*\nBook your appointment in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:book", "title": "\U0001f487 Book Appointment"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Salon"},
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
            "message": "\U0001f9d1 Connecting you with our team at *{{business_name}}* -- someone will reply here shortly.",
            "back_target": "welcome",
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f381 *Current Offers*\n\nAsk our team about current offers and seasonal packages any time you book!",
            "back_target": "welcome",
        },
        {
            "step_id": "location_info",
            "type": "message",
            "prompt": "\U0001f4cd *{{restaurant_name}}*\n\nYou'll find our details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de *{{restaurant_name}}*\n\nYou can reach our front desk right here on WhatsApp any time.",
            "back_target": "welcome",
        },
        {
            # Spec step 2: "Book Appointment" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f487 Which type of service would you like to book?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "service_select",
            "show_image": True,
            "section_title": "Service Types",
        },
        {
            # Spec step 3: Category tapped -> Service list (name + duration + price,
            # tap = select). [Back -> Category list]
            "step_id": "service_select",
            "type": "menu_select",
            "prompt": "Here are our *{{category_id_label}}* services -- tap one to select:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "back_target": "category_select",
            "next": "staff_select",
            "show_image": True,
            "section_title": "Services",
        },
        {
            # Spec step 4: Service tapped -> "Choose Staff" (Any Available / named staff),
            # only shown when the staff_selection module is on. [Back -> Service list]
            "step_id": "staff_select",
            "type": "menu_select",
            "prompt": "Great choice -- *{{item_id_label}}*!\n\nWho would you like to book with?",
            "buttons_from": "staff",
            "capture_key": "staff_id",
            "back_target": "service_select",
            "next": "date_select",
            "skip_if_module_off": "staff_selection",
            "show_image": False,
        },
        {
            # Spec step 5: Date buttons -- Today / Tomorrow / Pick a Date.
            # [Back -> staff selection]
            "step_id": "date_select",
            "type": "menu_select",
            "prompt": "\U0001f4c5 When would you like to come in?",
            "buttons_from": "dates",
            "capture_key": "date",
            "back_target": "staff_select",
            "next": "time_select",
            "show_image": False,
        },
        {
            # Spec step 6: Time slot buttons from real staff/salon availability.
            # [Back -> date buttons]
            "step_id": "time_select",
            "type": "menu_select",
            "prompt": "⏰ Available time slots for *{{date_label}}*:",
            "buttons_from": "time_slots",
            "capture_key": "time",
            "back_target": "date_select",
            "next": "name_confirm",
            "show_image": False,
        },
        {
            # Spec step 7: Name confirmation, auto-pulled from the WhatsApp profile and
            # editable via a button. [Back -> time slot]
            "step_id": "name_confirm",
            "type": "menu_select",
            "prompt": "\U0001f9d1 Please confirm the name for this booking:\n\n*{{customer_name}}*",
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
            "back_target": "time_select",
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
            # Spec step 8: Booking confirmation card (service, staff, date, time) ->
            # "Confirm Booking" button. [Back -> name confirmation]
            "step_id": "booking_confirm",
            "type": "confirm_action",
            "prompt": (
                "\U0001f487 *Review Your Booking*\n\n"
                "\U0001f487 *Service:* {{item_id_label}}\n"
                "\U0001f9d1 *Staff:* {{staff_id_label}}\n"
                "\U0001f4c5 *Date:* {{date_label}}\n"
                "⏰ *Time:* {{time_label}}\n\n"
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
            # Spec step 9: Confirmed -> confirmation message (mentions a reminder will be
            # sent); notify_business() (called unconditionally inside
            # _create_engagement's create_engagement action, step above) notifies staff.
            # Flow complete -- terminal, no Back.
            "step_id": "booking_confirmed",
            "type": "message",
            "prompt": (
                "✅ *You're all set!* Your appointment is confirmed.\nReference: {{last_reference_number}}\n\n"
                "We'll send you a reminder before your appointment. See you soon at "
                "*{{restaurant_name}}*!"
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "Requested",
            "confirmed": "Confirmed",
            "in_progress": "In Session",
            "completed": "Completed",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Services",
        "category_label": "Service Type",
        "item_label": "Service",
        "staff_label": "Stylist",
    },
    "default_modules": {
        "staff_selection": True,
    },
    "default_personality": {
        "tone": "warm_friendly_conversational",
        "language": "auto",
        "emoji_level": "high",
        "response_length": "short",
        "business_personality": "salon",
    },
}
