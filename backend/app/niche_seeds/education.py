"""Education & Coaching Institute niche template -- an `action_type="inquiry"` niche (lead
capture, no cart, no payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly). This is a re-skin of the proven Real
Estate pattern (app/niche_seeds/real_estate.py): "listing" becomes "Course", "budget
range" becomes "preferred batch/timing", everything else about the shape is identical.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_education.py for an end-to-end proof this drives a real conversation
through the real engine.

Inquiry-flow shape (context keys a completed inquiry's Engagement.details carries):
  category_id -> item_id (captured directly via capture_key, same as Real Estate's listing
  selection, PLUS action="capture_pending_item" so pending_item_name/pending_item_price
  are also available to render) -> preferred_batch -> requirements, plus an optional
  customer_name_override if the customer edited the WhatsApp-profile-sourced name. There
  is no cart/staff/date/time anywhere in this flow -- an education lead is exactly one
  course of interest plus free-text notes, captured directly into named context keys, then
  read back by the final `confirm_action` step's `create_engagement` action. Because
  `cart` is always empty here, `create_engagement` sets `requires_payment=False`
  automatically (`bool(cart)`) -- no special-casing needed for "this niche never charges".

Course duration is carried in each item's `attributes` JSON bag for potential admin/API
use, but surfaced to the customer via each item's plain `description` field rather than a
`_price_label` change -- `_price_label`'s `include_attributes` special-case currently only
knows about `duration_minutes` (a salon-specific concept), and extending it for education
attributes was explicitly out of scope for this niche (see the shared
generic_flow_engine.py, which this file must not edit).
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
_DEMO_IMG_BASE = demo_image_base("education")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_ACADEMIC = f"{_DEMO_IMG_BASE}/academic.jpg"
_IMG_COMPETITIVE = f"{_DEMO_IMG_BASE}/competitive.jpg"
_IMG_SKILL = f"{_DEMO_IMG_BASE}/skill.jpg"
_IMG_ONLINE = f"{_DEMO_IMG_BASE}/online.jpg"


TEMPLATE = {
    "code": "education",
    "name": "Education & Coaching",
    "action_type": "inquiry",
    "icon": "\U0001f393",  # 🎓
    "welcome_message": "\U0001f393 Welcome to [Business Name]! Find the right course for you today.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:browse", "title": "\U0001f4da Explore Courses"},
        {"id": "welcome:enroll", "title": "\U0001f4dd Enroll Now"},
        {"id": "welcome:offers", "title": "\U0001f389 Offers"},
        {"id": "welcome:center", "title": "\U0001f4cd Our Center"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
    ],
    "default_catalog": [
        {
            "name": "Academic Coaching",
            "icon_image": _IMG_ACADEMIC,
            "items": [
                {
                    "name": "Class 10 Math Batch",
                    "description": "Duration: 6 months · Board-aligned curriculum with weekly tests and doubt sessions.",
                    "price": 8000,
                    "price_type": "starting_from",
                    "images": [_IMG_ACADEMIC],
                    "attributes": {"duration": "6 months"},
                },
                {
                    "name": "Class 12 Science",
                    "description": "Duration: 1 year · Physics, Chemistry and Biology/Math with practical labs.",
                    "price": 12000,
                    "price_type": "starting_from",
                    "images": [_IMG_ACADEMIC],
                    "attributes": {"duration": "1 year"},
                },
            ],
        },
        {
            "name": "Competitive Exams",
            "icon_image": _IMG_COMPETITIVE,
            "items": [
                {
                    "name": "JEE Foundation",
                    "description": "Duration: 1 year · Concept-first prep for JEE Main and Advanced with mock tests.",
                    "price": 25000,
                    "price_type": "starting_from",
                    "images": [_IMG_COMPETITIVE],
                    "attributes": {"duration": "1 year"},
                },
                {
                    "name": "NEET Foundation",
                    "description": "Duration: 1 year · Biology-heavy NEET prep with weekly test series.",
                    "price": 25000,
                    "price_type": "starting_from",
                    "images": [_IMG_COMPETITIVE],
                    "attributes": {"duration": "1 year"},
                },
            ],
        },
        {
            "name": "Skill Courses",
            "icon_image": _IMG_SKILL,
            "items": [
                {
                    "name": "Spoken English",
                    "description": "Duration: 3 months · Conversational fluency, grammar and interview prep.",
                    "price": 4000,
                    "price_type": "starting_from",
                    "images": [_IMG_SKILL],
                    "attributes": {"duration": "3 months"},
                },
                {
                    "name": "Coding for Kids",
                    "description": "Duration: 4 months · Scratch to Python basics with weekly projects, ages 8-14.",
                    "price": 6000,
                    "price_type": "starting_from",
                    "images": [_IMG_SKILL],
                    "attributes": {"duration": "4 months"},
                },
            ],
        },
        {
            "name": "Online Courses",
            "icon_image": _IMG_ONLINE,
            "items": [
                {
                    "name": "Online Math Batch",
                    "description": "Duration: 6 months · Live online classes with recorded sessions for revision.",
                    "price": 5000,
                    "price_type": "starting_from",
                    "images": [_IMG_ONLINE],
                    "attributes": {"duration": "6 months"},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map onto the
    # spec (welcome -> category -> course -> preferred batch -> requirements -> name
    # confirm -> inquiry confirm -> submitted), plus four simple side-branch "message"
    # steps off the welcome menu (Enroll Now routes into the same browse chain; Offers /
    # Our Center / Contact Us don't lead into the lead-capture chain).
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f393 Welcome to {{restaurant_name}}! Find the right course for you today.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:browse", "title": "\U0001f4da Explore Courses"},
                {"id": "welcome:enroll", "title": "\U0001f4dd Enroll Now"},
                {"id": "welcome:offers", "title": "\U0001f389 Offers"},
                {"id": "welcome:center", "title": "\U0001f4cd Our Center"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
            ],
            "routes": {
                "welcome:browse": "category_select",
                "welcome:enroll": "category_select",
                "welcome:offers": "offers_info",
                "welcome:center": "location_info",
                "welcome:contact": "contact_info",
            },
            "next": "category_select",
            "back_target": None,
            "show_image": True,
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f389 Ask our team about current offers and early-bird discounts on select courses any time!",
            "back_target": "welcome",
        },
        {
            "step_id": "location_info",
            "type": "message",
            "prompt": "\U0001f4cd You'll find {{restaurant_name}}'s center details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de You can reach {{restaurant_name}}'s admissions team right here on WhatsApp any time.",
            "back_target": "welcome",
        },
        {
            # "Explore Courses" / "Enroll Now" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "Which category are you interested in?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "item_select",
            "show_image": True,
            "section_title": "Categories",
        },
        {
            # Category tapped -> Course list (name + price, tap = select).
            # [Back -> Category list]
            "step_id": "item_select",
            "type": "menu_select",
            "prompt": "Here are our {{category_id_label}} courses -- tap one to view details:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "action": "capture_pending_item",
            "back_target": "category_select",
            "next": "batch_capture",
            "show_image": True,
            "section_title": "Courses",
        },
        {
            # Optional preferred batch/timing note. [Back -> Course list]
            "step_id": "batch_capture",
            "type": "free_text_input",
            "prompt": "What's your preferred batch or timing for *{{item_id_label}}*? (or tap Skip)",
            "capture_key": "preferred_batch",
            "allow_skip": True,
            "back_target": "item_select",
            "next": "requirements_capture",
        },
        {
            # Optional free-form requirements. [Back -> preferred batch note]
            "step_id": "requirements_capture",
            "type": "free_text_input",
            "prompt": "Any specific requirements we should know (current level, target score, doubts)? (or tap Skip)",
            "capture_key": "requirements",
            "allow_skip": True,
            "back_target": "batch_capture",
            "next": "name_confirm",
        },
        {
            # Name confirmation, auto-pulled from the WhatsApp profile and editable via a
            # button. [Back -> requirements note]
            "step_id": "name_confirm",
            "type": "menu_select",
            "prompt": "Please confirm the name we should use for this inquiry: *{{customer_name}}*",
            "buttons_from": "static",
            "static_options": [
                {"id": "name:confirm", "title": "Looks Good"},
                {"id": "name:edit", "title": "Edit Name"},
            ],
            "routes": {
                "name:confirm": "inquiry_confirm",
                "name:edit": "name_edit",
            },
            "next": "inquiry_confirm",
            "back_target": "requirements_capture",
            "show_image": False,
        },
        {
            "step_id": "name_edit",
            "type": "free_text_input",
            "prompt": "Please type the name we should use for this inquiry:",
            "capture_key": "customer_name_override",
            "allow_skip": False,
            "next": "inquiry_confirm",
            "back_target": "name_confirm",
        },
        {
            # Inquiry review card -> "Submit Inquiry" button. [Back -> name confirmation]
            "step_id": "inquiry_confirm",
            "type": "confirm_action",
            "prompt": (
                "Please review your inquiry:\n\n"
                "\U0001f393 Course: {{item_id_label}}\n"
                "\U0001f5d3️ Preferred Batch: {{preferred_batch}}\n"
                "\U0001f4dd Requirements: {{requirements}}\n\n"
                "Tap below to submit."
            ),
            "buttons_from": "static",
            "static_options": [{"id": "inquiry:submit", "title": "Submit Inquiry"}],
            "action": "create_engagement",
            "back_target": "name_confirm",
            "next": "inquiry_confirmed",
            "show_image": False,
        },
        {
            # Submitted -> confirmation message (no payment, no cart -- a lead, not a
            # purchase); notify_business() (called unconditionally inside
            # create_engagement's create_engagement action, step above) notifies staff.
            # Flow complete -- terminal, no Back.
            "step_id": "inquiry_confirmed",
            "type": "message",
            "prompt": (
                "✅ Thank you! Your inquiry has been submitted. Reference: {{last_reference_number}}.\n\n"
                "Our counselor will reach out to you shortly regarding {{item_id_label}}."
            ),
            "back_target": None,
            "terminal": True,
        },
    ],
    "terminology": {
        "status_labels": {
            "new": "New Lead",
            "confirmed": "Contacted",
            "in_progress": "Follow-up",
            "completed": "Enrolled",
            "cancelled": "Not Interested",
        },
        "catalog_label": "Courses",
        "category_label": "Category",
        "item_label": "Course",
        "staff_label": "Counselor",
    },
    "default_modules": {},
}
