"""Real Estate niche template -- the `action_type="inquiry"` proof niche (lead capture,
no cart, no payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly).

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_real_estate.py for an end-to-end proof this drives a real
conversation through the real engine.

Inquiry-flow shape (context keys a completed inquiry's Engagement.details carries):
  category_id -> item_id (captured directly via capture_key, same as Salon's item
  selection, PLUS action="capture_pending_item" so pending_item_name/pending_item_price
  are also available to render) -> budget_range -> requirements, plus an optional
  customer_name_override if the customer edited the WhatsApp-profile-sourced name. There
  is no cart/staff/date/time anywhere in this flow -- a real-estate lead is exactly one
  property of interest plus free-text notes, captured directly into named context keys,
  then read back by the final `confirm_action` step's `create_engagement` action. Because
  `cart` is always empty here, `create_engagement` sets `requires_payment=False`
  automatically (`bool(cart)`) -- no special-casing needed for "this niche never charges".

Listing attributes (bedrooms/area_sqft/possession) are carried in each item's
`attributes` JSON bag for potential admin/API use, but surfaced to the customer via each
item's plain `description` field rather than a `_price_label` change -- `_price_label`'s
`include_attributes` special-case currently only knows about `duration_minutes` (a
salon-specific concept), and extending it for real-estate attributes was explicitly out
of scope for this niche (see the shared generic_flow_engine.py, which this file must not
edit).
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
_DEMO_IMG_BASE = demo_image_base("real_estate")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_APARTMENTS = f"{_DEMO_IMG_BASE}/apartments.jpg"
_IMG_VILLAS = f"{_DEMO_IMG_BASE}/villas.jpg"
_IMG_PLOTS = f"{_DEMO_IMG_BASE}/plots.jpg"
_IMG_COMMERCIAL = f"{_DEMO_IMG_BASE}/commercial.jpg"


TEMPLATE = {
    "code": "real_estate",
    "name": "Real Estate",
    "action_type": "inquiry",
    "icon": "\U0001f3e0",  # 🏠
    "welcome_message": "\U0001f3e0 *Welcome to [Business Name]!*\nFind your perfect property today.",
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:browse", "title": "\U0001f3e0 Browse Properties"},
        {"id": "welcome:list_property", "title": "\U0001f4cb List My Property"},
        {"id": "welcome:offers", "title": "\U0001f389 Offers"},
        {"id": "welcome:office", "title": "\U0001f4cd Our Office"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Apartments",
            "icon_image": _IMG_APARTMENTS,
            "items": [
                {
                    "name": "Sea View 2BHK",
                    "description": "2 bedrooms · 950 sqft · Ready to move · Sea-facing balcony in Bandra West.",
                    "price": 8500000,
                    "price_type": "starting_from",
                    "images": [_IMG_APARTMENTS],
                    "attributes": {"bedrooms": 2, "area_sqft": 950, "possession": "Ready to move"},
                },
                {
                    "name": "Garden View 3BHK",
                    "description": "3 bedrooms · 1400 sqft · Under construction, possession Dec 2026 · Gated community with garden.",
                    "price": 12500000,
                    "price_type": "starting_from",
                    "images": [_IMG_APARTMENTS],
                    "attributes": {"bedrooms": 3, "area_sqft": 1400, "possession": "Dec 2026"},
                },
            ],
        },
        {
            "name": "Villas",
            "icon_image": _IMG_VILLAS,
            "items": [
                {
                    "name": "4 BHK Luxury Villa",
                    "description": "4 bedrooms · 3200 sqft · Ready to move · Private pool and garden in Whitefield.",
                    "price": 45000000,
                    "price_type": "starting_from",
                    "images": [_IMG_VILLAS],
                    "attributes": {"bedrooms": 4, "area_sqft": 3200, "possession": "Ready to move"},
                },
                {
                    "name": "3 BHK Independent Villa",
                    "description": "3 bedrooms · 2400 sqft · Under construction, possession Mar 2027 · Independent villa with private terrace in Sarjapur Road.",
                    "price": 28000000,
                    "price_type": "starting_from",
                    "images": [_IMG_VILLAS],
                    "attributes": {"bedrooms": 3, "area_sqft": 2400, "possession": "Mar 2027"},
                },
            ],
        },
        {
            "name": "Plots",
            "icon_image": _IMG_PLOTS,
            "items": [
                {
                    "name": "Residential Plot",
                    "description": "1200 sqft · Clear title · Gated layout, ready for construction.",
                    "price": None,
                    "price_type": "on_request",
                    "images": [_IMG_PLOTS],
                    "attributes": {"area_sqft": 1200, "possession": "Immediate"},
                },
                {
                    "name": "Corner Plot",
                    "description": "1600 sqft · East-facing corner plot · Approved layout, close to the main road.",
                    "price": 4200000,
                    "price_type": "starting_from",
                    "images": [_IMG_PLOTS],
                    "attributes": {"area_sqft": 1600, "possession": "Immediate"},
                },
            ],
        },
        {
            "name": "Commercial Spaces",
            "icon_image": _IMG_COMMERCIAL,
            "items": [
                {
                    "name": "Retail Shop",
                    "description": "450 sqft · Ground floor · High footfall retail space near Main Market.",
                    "price": 6000000,
                    "price_type": "starting_from",
                    "images": [_IMG_COMMERCIAL],
                    "attributes": {"area_sqft": 450, "possession": "Ready to move"},
                },
                {
                    "name": "Office Space",
                    "description": "1800 sqft · Furnished · Grade-A office space with dedicated parking.",
                    "price": 12000000,
                    "price_type": "starting_from",
                    "images": [_IMG_COMMERCIAL],
                    "attributes": {"area_sqft": 1800, "possession": "Ready to move"},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map onto the
    # spec (welcome -> category -> listing -> budget -> requirements -> name confirm ->
    # inquiry confirm -> submitted), plus four simple side-branch "message" steps off the
    # welcome menu (List My Property / Offers / Our Office / Contact Us) that don't lead
    # into the lead-capture chain.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": "\U0001f3e0 *Welcome to {{restaurant_name}}!*\nFind your perfect property today.",
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:browse", "title": "\U0001f3e0 Browse Properties"},
                {"id": "welcome:list_property", "title": "\U0001f4cb List My Property"},
                {"id": "welcome:offers", "title": "\U0001f389 Offers"},
                {"id": "welcome:office", "title": "\U0001f4cd Our Office"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
                {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
            ],
            "routes": {
                "welcome:browse": "category_select",
                "welcome:list_property": "list_property_capture",
                "welcome:offers": "offers_info",
                "welcome:office": "location_info",
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
            # Real lead capture (not a dead-end message): free-text property details ->
            # review -> a genuine tracked Engagement lead, reusing the same
            # create_engagement action verb the browse-a-listing enquiry chain uses below.
            "step_id": "list_property_capture",
            "type": "free_text_input",
            "prompt": (
                "\U0001f4cb *List Your Property*\n\n"
                "Want to list with *{{business_name}}*? Tell us a bit about it "
                "(location, type, asking price) -- or tap Skip and our team will call you instead."
            ),
            "capture_key": "property_listing_details",
            "allow_skip": True,
            "back_target": "welcome",
            "next": "list_property_confirm",
        },
        {
            "step_id": "list_property_confirm",
            "type": "confirm_action",
            "prompt": (
                "\U0001f4cb *Review Your Listing*\n\n"
                "{{property_listing_details}}\n\n"
                "Tap below and our team will get in touch to list it for you."
            ),
            "buttons_from": "static",
            "static_options": [{"id": "listing:submit", "title": "Submit"}],
            "action": "create_engagement",
            "back_target": "list_property_capture",
            "next": "list_property_confirmed",
            "show_image": False,
        },
        {
            "step_id": "list_property_confirmed",
            "type": "message",
            "prompt": (
                "✅ *Thanks!* Your listing request has been submitted.\nReference: {{last_reference_number}}\n\n"
                "Our team will reach out shortly to help list your property."
            ),
            "back_target": None,
            "terminal": True,
        },
        {
            "step_id": "offers_info",
            "type": "message",
            "prompt": "\U0001f389 *Current Offers*\n\nAsk our team about current offers and festive deals on select properties any time!",
            "back_target": "welcome",
        },
        {
            "step_id": "location_info",
            "type": "message",
            "prompt": "\U0001f4cd *{{restaurant_name}}*\n\nYou'll find our office details and directions here -- message us if you need help finding us!",
            "back_target": "welcome",
        },
        {
            "step_id": "contact_info",
            "type": "message",
            "prompt": "\U0001f4de *{{restaurant_name}}*\n\nYou can reach our sales team right here on WhatsApp any time.",
            "back_target": "welcome",
        },
        {
            # "Browse Properties" tapped -> Category list. [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f3e0 Which type of property are you looking for?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "item_select",
            "show_image": True,
            "section_title": "Property Types",
        },
        {
            # Category tapped -> Listing list (name + price, tap = select).
            # [Back -> Category list]
            "step_id": "item_select",
            "type": "menu_select",
            "prompt": "Here are our *{{category_id_label}}* listings -- tap one to view details:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "action": "capture_pending_item",
            "back_target": "category_select",
            "next": "budget_capture",
            "show_image": True,
            "section_title": "Listings",
        },
        {
            # Optional budget note. [Back -> Listing list]
            "step_id": "budget_capture",
            "type": "free_text_input",
            "prompt": "\U0001f4b0 What's your budget range for *{{item_id_label}}*? (or tap Skip)",
            "capture_key": "budget_range",
            "allow_skip": True,
            "back_target": "item_select",
            "next": "requirements_capture",
        },
        {
            # Optional free-form requirements. [Back -> budget note]
            "step_id": "requirements_capture",
            "type": "free_text_input",
            "prompt": "\U0001f4dd Any specific requirements we should know (floor preference, parking, move-in date)? (or tap Skip)",
            "capture_key": "requirements",
            "allow_skip": True,
            "back_target": "budget_capture",
            "next": "name_confirm",
        },
        {
            # Name confirmation, auto-pulled from the WhatsApp profile and editable via a
            # button. [Back -> requirements note]
            "step_id": "name_confirm",
            "type": "menu_select",
            "prompt": "\U0001f9d1 Please confirm the name we should use for this inquiry:\n\n*{{customer_name}}*",
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
                "\U0001f3e0 *Review Your Inquiry*\n\n"
                "\U0001f3e0 *Property:* {{item_id_label}}\n"
                "\U0001f4b0 *Budget:* {{budget_range}}\n"
                "\U0001f4dd *Requirements:* {{requirements}}\n\n"
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
                "✅ *Thank you!* Your inquiry has been submitted.\nReference: {{last_reference_number}}\n\n"
                "Our agent will reach out to you shortly regarding *{{item_id_label}}*."
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
            "completed": "Closed",
            "cancelled": "Not Interested",
        },
        "catalog_label": "Listings",
        "category_label": "Property Type",
        "item_label": "Property",
        "staff_label": "Agent",
    },
    "default_modules": {},
}
