"""Gym & Fitness Studio niche template -- an `action_type="appointment"` niche (trainer
selection + date + time-slot booking) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). This is a re-skin of the proven Salon &
Spa pattern (app/niche_seeds/salon.py): "staff" becomes Trainers, "service" becomes
Class/Session type -- otherwise the flow shape is identical.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- a super-admin
seed script constructs a `NicheTemplate(**TEMPLATE)` row from this dict (after coercing
`action_type` to the `EngagementType` enum), and app/services/niche_provisioning.py
copies it into a brand-new business's own catalog_categories/catalog_items/flow_definitions
rows at creation time. See app/tests/test_niche_gym.py for an end-to-end proof this
actually drives a real conversation through the real engine.

Booking-flow shape (context keys a completed booking's Engagement.details carries):
  category_id -> item_id -> staff_id -> date -> time, plus an optional
  customer_name_override if the customer edited the WhatsApp-profile-sourced name.
No cart/add_to_cart/capture_pending_item is used anywhere in this flow -- a class/session
booking has exactly one class type, trainer, date and time, captured directly into named
context keys via each menu_select step's `capture_key`, then read back by the final
`confirm_action` step's `create_engagement` action (which reads its EngagementType off the
FlowDefinition itself, not off any step).
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
_DEMO_IMG_BASE = demo_image_base("gym")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_FREE_TRIAL = f"{_DEMO_IMG_BASE}/free_trial.jpg"
_IMG_PERSONAL_TRAINING = f"{_DEMO_IMG_BASE}/personal_training.jpg"
_IMG_GROUP_CLASSES = f"{_DEMO_IMG_BASE}/group_classes.jpg"
_IMG_YOGA = f"{_DEMO_IMG_BASE}/yoga.jpg"


TEMPLATE = {
    "code": "gym",
    "name": "Gym & Fitness Studio",
    "action_type": "appointment",
    "icon": "\U0001f3cb",  # 🏋
    "welcome_message": "\U0001f4aa *Welcome to [Business Name]!*\n\nBook your session in seconds.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:book", "title": "\U0001f4aa Book a Session"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Gym"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Free Trial",
            "icon_image": _IMG_FREE_TRIAL,
            "items": [
                {
                    "name": "Free Trial Session",
                    "description": "One free trial session to experience the gym.",
                    "price": 0,
                    "price_type": "free",
                    "images": [_IMG_FREE_TRIAL],
                    "attributes": {"duration_minutes": 60},
                },
                {
                    "name": "Free Group Class Trial",
                    "description": "One free trial pass to attend any group class of your choice -- Zumba, HIIT or Yoga.",
                    "price": 0,
                    "price_type": "free",
                    "images": [_IMG_FREE_TRIAL],
                    "attributes": {"duration_minutes": 45},
                },
            ],
        },
        {
            "name": "Personal Training",
            "icon_image": _IMG_PERSONAL_TRAINING,
            "items": [
                {
                    "name": "Personal Training",
                    "description": "One-on-one session with a personal trainer.",
                    "price": 800,
                    "price_type": "fixed",
                    "images": [_IMG_PERSONAL_TRAINING],
                    "attributes": {"duration_minutes": 60},
                },
                {
                    "name": "Personal Training Package (5 Sessions)",
                    "description": "Five one-on-one sessions with a personal trainer, including a customized fitness plan.",
                    "price": 3500,
                    "price_type": "fixed",
                    "images": [_IMG_PERSONAL_TRAINING],
                    "attributes": {"duration_minutes": 60},
                },
            ],
        },
        {
            "name": "Group Classes",
            "icon_image": _IMG_GROUP_CLASSES,
            "items": [
                {
                    "name": "Zumba Class",
                    "description": "High-energy dance fitness in a group setting.",
                    "price": 300,
                    "price_type": "fixed",
                    "images": [_IMG_GROUP_CLASSES],
                    "attributes": {"duration_minutes": 45},
                },
                {
                    "name": "HIIT Class",
                    "description": "High-intensity interval training, group format.",
                    "price": 350,
                    "price_type": "fixed",
                    "images": [_IMG_GROUP_CLASSES],
                    "attributes": {"duration_minutes": 45},
                },
            ],
        },
        {
            "name": "Yoga",
            "icon_image": _IMG_YOGA,
            "items": [
                {
                    "name": "Yoga Class",
                    "description": "Balanced yoga session for flexibility and calm.",
                    "price": 300,
                    "price_type": "fixed",
                    "images": [_IMG_YOGA],
                    "attributes": {"duration_minutes": 60},
                },
                {
                    "name": "Power Yoga",
                    "description": "Fast-paced, strength-focused yoga session.",
                    "price": 350,
                    "price_type": "fixed",
                    "images": [_IMG_YOGA],
                    "attributes": {"duration_minutes": 60},
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
            "prompt": "\U0001f4aa *Welcome to {{restaurant_name}}!*\n\nBook your session in seconds.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:book", "title": "\U0001f4aa Book a Session"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:location", "title": "\U0001f4cd Our Location"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Gym"},
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
            "message": "\U0001f9d1 *Connecting you now*\n\nSomeone from our team at {{business_name}} will reply here shortly.",
            "back_target": "welcome",
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f381 *Special Offers*\n\nAsk our team about current offers and membership packages any time you book!",
            "back_target": "welcome",
        },
        {
            "step_id": "location_info",
            "type": "message",
            "prompt": "\U0001f4cd *Our Location*\n\nYou'll find {{restaurant_name}}'s address and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de *Contact Us*\n\nYou can reach {{restaurant_name}}'s front desk right here on WhatsApp, any time.",
            "back_target": "welcome",
        },
        {
            # Spec step 2: "Book a Session" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f4aa *Class Types*\n\nWhich type of class or session would you like to book?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "service_select",
            "show_image": True,
            "section_title": "Class Types",
        },
        {
            # Spec step 3: Category tapped -> Class/session list (name + duration + price,
            # tap = select). [Back -> Category list]
            "step_id": "service_select",
            "type": "menu_select",
            "prompt": "\U0001f3cb️ *{{category_id_label}}*\n\nTap one to select:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "back_target": "category_select",
            "next": "staff_select",
            "show_image": True,
            "section_title": "Classes",
        },
        {
            # Spec step 4: Class/session tapped -> "Choose Trainer" (Any Available / named
            # trainer), only shown when the staff_selection module is on.
            # [Back -> Service list]
            "step_id": "staff_select",
            "type": "menu_select",
            "prompt": "Great choice -- *{{item_id_label}}*\n\n\U0001f4aa Who would you like to train with?",
            "buttons_from": "staff",
            "capture_key": "staff_id",
            "back_target": "service_select",
            "next": "date_select",
            "skip_if_module_off": "staff_selection",
            "show_image": False,
        },
        {
            # Spec step 5: Date buttons -- Today / Tomorrow / Pick a Date.
            # [Back -> trainer selection]
            "step_id": "date_select",
            "type": "menu_select",
            "prompt": "\U0001f4c5 *Pick a Date*\n\nWhen would you like to come in?",
            "buttons_from": "dates",
            "capture_key": "date",
            "back_target": "staff_select",
            "next": "time_select",
            "show_image": False,
        },
        {
            # Spec step 6: Time slot buttons from real trainer/gym availability.
            # [Back -> date buttons]
            "step_id": "time_select",
            "type": "menu_select",
            "prompt": "⏰ *Available Slots -- {{date_label}}*\n\nTap a time to book it:",
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
            "prompt": "\U0001f4cb Please confirm the name for this booking:\n\n*{{customer_name}}*",
            "buttons_from": "static",
            "static_options": [
                {"id": "name:confirm", "title": "✅ Looks Good"},
                {"id": "name:edit", "title": "✏️ Edit Name"},
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
            "prompt": "✏️ Please type the name we should use for this booking:",
            "capture_key": "customer_name_override",
            "allow_skip": False,
            "next": "booking_confirm",
            "back_target": "name_confirm",
        },
        {
            # Spec step 8: Booking confirmation card (class, trainer, date, time) ->
            # "Confirm Booking" button. [Back -> name confirmation]
            "step_id": "booking_confirm",
            "type": "confirm_action",
            "prompt": (
                "\U0001f4cb *Review Your Booking*\n\n"
                "\U0001f3cb *Class:* {{item_id_label}}\n"
                "\U0001f4aa *Trainer:* {{staff_id_label}}\n"
                "\U0001f4c5 *Date:* {{date_label}}\n"
                "⏰ *Time:* {{time_label}}\n\n"
                "Tap below to confirm."
            ),
            "buttons_from": "static",
            "static_options": [{"id": "booking:confirm", "title": "✅ Confirm Booking"}],
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
                "✅ *Session Confirmed!*\n\n"
                "Reference: {{last_reference_number}}\n\n"
                "We'll send you a reminder before your session. See you soon at "
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
            "in_progress": "In Session",
            "completed": "Completed",
            "cancelled": "Cancelled",
        },
        "catalog_label": "Classes",
        "category_label": "Class Type",
        "item_label": "Class",
        "staff_label": "Trainer",
    },
    "default_modules": {
        "staff_selection": True,
    },
}
