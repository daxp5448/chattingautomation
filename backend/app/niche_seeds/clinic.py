"""Clinic & Healthcare niche template -- an `action_type="appointment"` niche (doctor
selection + date + time-slot booking) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). This is a direct re-skin of the proven
Salon & Spa template (app/niche_seeds/salon.py) -- doctors instead of stylists,
consultations instead of services -- driving the identical `action_type="appointment"`
booking chain through the same shared engine.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- a super-admin
seed script constructs a `NicheTemplate(**TEMPLATE)` row from this dict (after coercing
`action_type` to the `EngagementType` enum), and app/services/niche_provisioning.py
copies it into a brand-new business's own catalog_categories/catalog_items/flow_definitions
rows at creation time. See app/tests/test_niche_clinic.py for an end-to-end proof this
actually drives a real conversation through the real engine.

Booking-flow shape (context keys a completed booking's Engagement.details carries):
  category_id -> item_id -> staff_id -> date -> time, plus an optional
  customer_name_override if the customer edited the WhatsApp-profile-sourced name.
No cart/add_to_cart/capture_pending_item is used anywhere in this flow -- a clinic
booking has exactly one consultation type, doctor, date and time, captured directly into
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
# documents for the webhook itself), then re-run sync_niche_templates once.
_DEMO_IMG_BASE = demo_image_base("clinic")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_GENERAL = f"{_DEMO_IMG_BASE}/general.jpg"
_IMG_DENTAL = f"{_DEMO_IMG_BASE}/dental.jpg"
_IMG_DERMATOLOGY = f"{_DEMO_IMG_BASE}/dermatology.jpg"
_IMG_GYNECOLOGY = f"{_DEMO_IMG_BASE}/gynecology.jpg"
_IMG_EYECARE = f"{_DEMO_IMG_BASE}/eyecare.jpg"


TEMPLATE = {
    "code": "clinic",
    "name": "Clinic & Healthcare",
    "action_type": "appointment",
    "icon": "\U0001f3e5",  # 🏥
    "welcome_message": "\U0001f3e5 Welcome to [Business Name]! Book your appointment in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:book", "title": "\U0001f4c5 Book Appointment"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Clinic"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "General Physician",
            "icon_image": _IMG_GENERAL,
            "items": [
                {
                    "name": "General Consult",
                    "description": "General physician consultation for common ailments.",
                    "price": 500,
                    "price_type": "fixed",
                    "images": [_IMG_GENERAL],
                    "attributes": {"duration_minutes": 20},
                },
                {
                    "name": "Health Checkup",
                    "description": "Comprehensive full-body health checkup.",
                    "price": 1500,
                    "price_type": "fixed",
                    "images": [_IMG_GENERAL],
                    "attributes": {"duration_minutes": 45},
                },
            ],
        },
        {
            "name": "Dental",
            "icon_image": _IMG_DENTAL,
            "items": [
                {
                    "name": "Dental Checkup",
                    "description": "Routine dental examination and diagnosis.",
                    "price": 800,
                    "price_type": "fixed",
                    "images": [_IMG_DENTAL],
                    "attributes": {"duration_minutes": 30},
                },
                {
                    "name": "Teeth Cleaning",
                    "description": "Professional scaling and teeth cleaning.",
                    "price": 1200,
                    "price_type": "fixed",
                    "images": [_IMG_DENTAL],
                    "attributes": {"duration_minutes": 45},
                },
            ],
        },
        {
            "name": "Dermatology",
            "icon_image": _IMG_DERMATOLOGY,
            "items": [
                {
                    "name": "Skin Consultation",
                    "description": "Dermatologist consultation for skin concerns.",
                    "price": 700,
                    "price_type": "fixed",
                    "images": [_IMG_DERMATOLOGY],
                    "attributes": {"duration_minutes": 20},
                },
                {
                    "name": "Acne & Scar Treatment",
                    "description": "Targeted in-clinic treatment session for acne and scarring.",
                    "price": 1800,
                    "price_type": "fixed",
                    "images": [_IMG_DERMATOLOGY],
                    "attributes": {"duration_minutes": 40},
                },
            ],
        },
        {
            "name": "Gynecology",
            "icon_image": _IMG_GYNECOLOGY,
            "items": [
                {
                    "name": "Gynec Consultation",
                    "description": "Gynecologist consultation.",
                    "price": 800,
                    "price_type": "fixed",
                    "images": [_IMG_GYNECOLOGY],
                    "attributes": {"duration_minutes": 30},
                },
                {
                    "name": "Pregnancy Checkup",
                    "description": "Routine prenatal checkup and consultation.",
                    "price": 1000,
                    "price_type": "fixed",
                    "images": [_IMG_GYNECOLOGY],
                    "attributes": {"duration_minutes": 30},
                },
            ],
        },
        {
            "name": "Eye Care",
            "icon_image": _IMG_EYECARE,
            "items": [
                {
                    "name": "Eye Checkup",
                    "description": "Routine eye examination.",
                    "price": 500,
                    "price_type": "fixed",
                    "images": [_IMG_EYECARE],
                    "attributes": {"duration_minutes": 20},
                },
                {
                    "name": "Eye Test + Glasses",
                    "description": "Eye test with prescription for glasses.",
                    "price": 900,
                    "price_type": "fixed",
                    "images": [_IMG_EYECARE],
                    "attributes": {"duration_minutes": 30},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map 1:1 onto
    # the 9-step spec (welcome -> category -> service -> staff -> date -> time -> name
    # confirm -> booking confirm -> confirmed), plus three simple side-branch "message"
    # steps off the welcome menu (Offers / Location / Contact) that don't lead into the
    # booking chain. Identical shape to app/niche_seeds/salon.py, re-skinned: "staff" here
    # means doctors, "service" here means consultation type.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f3e5 Welcome to {{restaurant_name}}! Book your appointment in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:book", "title": "\U0001f4c5 Book Appointment"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Clinic"},
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
            "prompt": "\U0001f381 Ask our front desk about current health-checkup offers and packages any time you book!",
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
            # Spec step 2: "Book Appointment" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "Which type of consultation would you like to book?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "service_select",
            "show_image": True,
            "section_title": "Consultation Types",
        },
        {
            # Spec step 3: Category tapped -> Consultation list (name + duration + price,
            # tap = select). [Back -> Category list]
            "step_id": "service_select",
            "type": "menu_select",
            "prompt": "Here are our {{category_id_label}} consultations -- tap one to select:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "back_target": "category_select",
            "next": "staff_select",
            "show_image": True,
            "section_title": "Consultations",
        },
        {
            # Spec step 4: Consultation tapped -> "Choose Doctor" (Any Available / named
            # doctor), only shown when the staff_selection module is on.
            # [Back -> Consultation list]
            "step_id": "staff_select",
            "type": "menu_select",
            "prompt": "Great choice -- *{{item_id_label}}*. Which doctor would you like to see?",
            "buttons_from": "staff",
            "capture_key": "staff_id",
            "back_target": "service_select",
            "next": "date_select",
            "skip_if_module_off": "staff_selection",
            "show_image": False,
        },
        {
            # Spec step 5: Date buttons -- Today / Tomorrow / Pick a Date.
            # [Back -> doctor selection]
            "step_id": "date_select",
            "type": "menu_select",
            "prompt": "When would you like to come in?",
            "buttons_from": "dates",
            "capture_key": "date",
            "back_target": "staff_select",
            "next": "time_select",
            "show_image": False,
        },
        {
            # Spec step 6: Time slot buttons from real doctor/clinic availability.
            # [Back -> date buttons]
            "step_id": "time_select",
            "type": "menu_select",
            "prompt": "Available time slots for *{{date_label}}*:",
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
            # Spec step 8: Booking confirmation card (consultation, doctor, date, time) ->
            # "Confirm Booking" button. [Back -> name confirmation]
            "step_id": "booking_confirm",
            "type": "confirm_action",
            "prompt": (
                "Please review your appointment:\n\n"
                "\U0001fa7a Consultation: {{item_id_label}}\n"
                "\U0001f468‍⚕️ Doctor: {{staff_id_label}}\n"
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
                "✅ Your appointment is confirmed! Reference: {{last_reference_number}}.\n\n"
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
        "catalog_label": "Consultations",
        "category_label": "Consultation Type",
        "item_label": "Consultation",
        "staff_label": "Doctor",
    },
    "default_modules": {
        "staff_selection": True,
    },
}
