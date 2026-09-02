"""Automobile Showroom & Service Center niche template -- an `action_type="appointment"`
niche (service advisor + date + time-slot booking) for the generic conversation engine
(see app/services/generic_flow_engine.py, whose module docstring and step-shape contract
this file's `default_flow_steps` implements exactly). Structurally identical to
app/niche_seeds/salon.py (the original "appointment" proof niche) -- "staff" here means
Service Advisors and "service" means the Service/Repair/Test-Drive type being booked --
with exactly one deliberate difference: `default_modules["staff_selection"]` is False
here (every other appointment niche built so far defaults it True), so the `staff_select`
step's `skip_if_module_off="staff_selection"` branch in generic_flow_engine.py's
`_Engine._advance` (auto-skip straight to `next` when the module is off) gets exercised
by a real niche for the first time.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- a super-admin
seed script constructs a `NicheTemplate(**TEMPLATE)` row from this dict (after coercing
`action_type` to the `EngagementType` enum), and app/services/niche_provisioning.py
copies it into a brand-new business's own catalog_categories/catalog_items/flow_definitions
rows at creation time. See app/tests/test_niche_automobile.py for an end-to-end proof this
actually drives a real conversation through the real engine, including the module-off
skip.

IMPORTANT caveat discovered while building this niche (see that test file's docstring for
the full explanation): `provision_from_template` does NOT copy `NicheTemplate.default_modules`
onto the new business's `Restaurant.loyalty_settings` -- so `default_modules` here is
documentation of the *intended* default only. In the engine, an unset module flag reads as
True (see `_Engine._advance`'s `.get(module_flag, True)` fallback), so a real business
provisioned from this template, with no `loyalty_settings` override at all, currently gets
staff_selection ON (module-gated step rendered), not OFF as this dict implies -- exactly
the same gap app/tests/test_niche_salon.py's fixture comment already flags for the reverse
case (salon needs it forced True there for the identical reason). This is a
provisioning-layer gap, not something fixable from a niche-seed file alone.

Booking-flow shape (context keys a completed booking's Engagement.details carries):
  category_id -> item_id -> [staff_id, only when staff_selection module is on] -> date ->
  time, plus an optional customer_name_override if the customer edited the
  WhatsApp-profile-sourced name.
No cart/add_to_cart/capture_pending_item is used anywhere in this flow -- a service/test-
drive booking has exactly one service, (optional) service advisor, date and time, captured
directly into named context keys via each menu_select step's `capture_key`, then read back
by the final `confirm_action` step's `create_engagement` action (which reads its
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
# documents for the webhook itself), then re-run sync_niche_templates once.
_DEMO_IMG_BASE = demo_image_base("automobile")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_CAR_SERVICE = f"{_DEMO_IMG_BASE}/car_service.jpg"
_IMG_BIKE_SERVICE = f"{_DEMO_IMG_BASE}/bike_service.jpg"
_IMG_TEST_DRIVE = f"{_DEMO_IMG_BASE}/test_drive.jpg"
_IMG_CAR_WASH = f"{_DEMO_IMG_BASE}/car_wash.jpg"


TEMPLATE = {
    "code": "automobile",
    "name": "Automobile Service & Showroom",
    "action_type": "appointment",
    "icon": "\U0001f697",  # 🚗
    "welcome_message": "\U0001f697 *Welcome to [Business Name]!*\n\nBook your service or test drive in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:book", "title": "\U0001f527 Book Service"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:showroom", "title": "\U0001f4cd Our Showroom"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Car Service",
            "icon_image": _IMG_CAR_SERVICE,
            "items": [
                {
                    "name": "General Service",
                    "description": "Complete multi-point car service and inspection.",
                    "price": 1500,
                    "price_type": "fixed",
                    "images": [_IMG_CAR_SERVICE],
                    "attributes": {"duration_minutes": 90},
                },
                {
                    "name": "Oil Change",
                    "description": "Engine oil and filter replacement.",
                    "price": 800,
                    "price_type": "fixed",
                    "images": [_IMG_CAR_SERVICE],
                    "attributes": {"duration_minutes": 30},
                },
            ],
        },
        {
            "name": "Bike Service",
            "icon_image": _IMG_BIKE_SERVICE,
            "items": [
                {
                    "name": "Bike Service",
                    "description": "Full two-wheeler service and tune-up.",
                    "price": 500,
                    "price_type": "fixed",
                    "images": [_IMG_BIKE_SERVICE],
                    "attributes": {"duration_minutes": 45},
                },
                {
                    "name": "Bike Oil Change",
                    "description": "Engine oil top-up and chain lubrication for two-wheelers.",
                    "price": 300,
                    "price_type": "fixed",
                    "images": [_IMG_BIKE_SERVICE],
                    "attributes": {"duration_minutes": 20},
                },
            ],
        },
        {
            "name": "Test Drive",
            "icon_image": _IMG_TEST_DRIVE,
            "items": [
                {
                    "name": "Test Drive Booking",
                    "description": "Book a free test drive of any showroom model.",
                    "price": 0,
                    "price_type": "free",
                    "images": [_IMG_TEST_DRIVE],
                    "attributes": {"duration_minutes": 30},
                },
            ],
        },
        {
            "name": "Car Wash",
            "icon_image": _IMG_CAR_WASH,
            "items": [
                {
                    "name": "Car Wash",
                    "description": "Exterior wash and dry.",
                    "price": 300,
                    "price_type": "fixed",
                    "images": [_IMG_CAR_WASH],
                    "attributes": {"duration_minutes": 20},
                },
                {
                    "name": "Deep Cleaning",
                    "description": "Interior and exterior deep-cleaning detail.",
                    "price": 1200,
                    "price_type": "fixed",
                    "images": [_IMG_CAR_WASH],
                    "attributes": {"duration_minutes": 90},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map 1:1 onto
    # the same 9-step spec salon.py uses (welcome -> category -> service -> staff -> date
    # -> time -> name confirm -> booking confirm -> confirmed), plus three simple
    # side-branch "message" steps off the welcome menu (Offers / Showroom / Contact) that
    # don't lead into the booking chain. staff_select carries `skip_if_module_off` per
    # spec -- see this file's module docstring for the exact default-module caveat.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f697 *Welcome to {{restaurant_name}}!*\n\nBook your service or test drive in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:book", "title": "\U0001f527 Book Service"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:showroom", "title": "\U0001f4cd Our Showroom"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
                {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
            ],
            "routes": {
                "welcome:book": "category_select",
                "welcome:offers": "offers_info",
                "welcome:showroom": "showroom_info",
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
            "message": "\U0001f9d1 *Connecting you with our team*\n\nSomeone at {{business_name}} will reply here shortly.",
            "back_target": "welcome",
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f381 *Offers*\n\nAsk our team about current service offers and showroom deals any time you book!",
            "back_target": "welcome",
        },
        {
            "step_id": "showroom_info",
            "type": "message",
            "prompt": "\U0001f4cd *Our Showroom*\n\nYou'll find {{restaurant_name}}'s details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de *Contact Us*\n\nYou can reach {{restaurant_name}}'s service desk right here on WhatsApp, any time.",
            "back_target": "welcome",
        },
        {
            # Spec step 2: "Book Service"/"Test Drive" tapped -> Category list.
            # [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f527 *Which type of service would you like to book?*",
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
            "prompt": "\U0001f527 *{{category_id_label}}*\n\nHere are our options -- tap one to select:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "back_target": "category_select",
            "next": "staff_select",
            "show_image": True,
            "section_title": "Services",
        },
        {
            # Spec step 4: Service tapped -> "Choose Service Advisor" (Any Available /
            # named advisor), only shown when the staff_selection module is on --
            # defaults OFF for this niche (see module docstring), so this step is
            # normally auto-skipped straight to date_select. [Back -> Service list]
            "step_id": "staff_select",
            "type": "menu_select",
            "prompt": "Great choice -- *{{item_id_label}}*!\n\n\U0001f9d1 Which service advisor would you like?",
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
            # Spec step 6: Time slot buttons from real availability (falls back to a
            # default 09:00-18:00 window when no specific advisor was selected -- see
            # generic_flow_engine.py::_time_slot_options). [Back -> date buttons]
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
            # Spec step 8: Booking confirmation card (service, advisor, date, time) ->
            # "Confirm Booking" button. [Back -> name confirmation]
            "step_id": "booking_confirm",
            "type": "confirm_action",
            "prompt": (
                "\U0001f4cb *Please review your booking:*\n\n"
                "\U0001f527 Service: {{item_id_label}}\n"
                "\U0001f9d1 Service Advisor: {{staff_id_label}}\n"
                "\U0001f4c5 Date: {{date_label}}\n"
                "⏰ Time: {{time_label}}\n\n"
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
                "✅ *Your booking is confirmed!*\n\n"
                "Reference: {{last_reference_number}}\n\n"
                "We'll send you a reminder before your appointment. See you soon at "
                "{{restaurant_name}}!"
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "Requested",
            "confirmed": "Confirmed",
            "in_progress": "In Progress",
            "completed": "Completed",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Services",
        "category_label": "Service Type",
        "item_label": "Service",
        "staff_label": "Service Advisor",
    },
    # NOTE: this alone does not make a freshly-provisioned business's staff_selection
    # module OFF at runtime -- see this file's module docstring for the provisioning
    # gap. Documents the *intended* default for this niche only.
    "default_modules": {
        "staff_selection": False,
    },
    "default_personality": {
        "tone": "professional_trustworthy",
        "language": "auto",
        "emoji_level": "low",
        "response_length": "short",
        "business_personality": "automobile",
    },
}
