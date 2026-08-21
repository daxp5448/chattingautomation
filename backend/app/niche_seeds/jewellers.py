"""Jewellers niche template -- an `action_type="inquiry"` niche (enquiry/appointment
lead capture, no cart, no payment) for the generic conversation engine (see
app/services/generic_flow_engine.py, whose module docstring and step-shape contract this
file's `default_flow_steps` implements exactly).

RESTRUCTURED from a cart/checkout "order" niche to an enquiry-led niche: high-value
jewellery purchases are enquiry/appointment-driven, not one-tap-checkout, so this niche
now shares Real Estate's inquiry flow shape (app/niche_seeds/real_estate.py) instead of
Restaurant's order flow -- "listing" becomes "piece", "budget range" becomes "preferred
visit", everything else about the shape is identical. No cart/quantity/checkout/payment
step exists anywhere in this file any more.

`TEMPLATE` matches app/models/niche_template.py's column shapes 1:1 -- see
app/services/niche_provisioning.py for how it's copied into a brand-new business's own
catalog_categories/catalog_items/flow_definitions rows at creation time, and
app/tests/test_niche_jewellers.py for an end-to-end proof this drives a real
conversation through the real engine.

Inquiry-flow shape (context keys a completed inquiry's Engagement.details carries):
  category_id -> item_id (captured directly via capture_key, PLUS action=
  "capture_pending_item" so pending_item_name/pending_item_price are also available to
  render) -> preferred_visit -> requirements, plus an optional customer_name_override if
  the customer edited the WhatsApp-profile-sourced name. There is no cart/staff/date/time
  anywhere in this flow -- a jewellery enquiry is exactly one piece of interest plus
  free-text notes, captured directly into named context keys, then read back by the
  final `confirm_action` step's `create_engagement` action. Because `cart` is always
  empty here, `create_engagement` sets `requires_payment=False` automatically
  (`bool(cart)`) -- no special-casing needed for "this niche never charges online".

  Between picking a piece and being asked for a visit preference, `piece_details` shows
  EVERY active photo curated for that piece (front/side/worn-on-hand/etc, each with its
  own caption, in Super-Admin-set order) -- not just one representative image. See
  app/services/image_presenter.py and generic_flow_engine.py's item_context_key handling.

"Book Appointment" is the sole entry point into the enquiry flow (category_select) --
there used to be a separate "Explore Collection" button routing to the same place, but it
was removed as a redundant duplicate of the newer "Explore Design" carousel below, which
now owns the "browse visually" role. "Book Appointment" still leads into the same
category_select this always used, so the underlying enquiry flow is unchanged.
"""

from app.niche_seeds._media import demo_image_base


_DEMO_IMG_BASE = demo_image_base("jewellers")
_IMG_WELCOME = f"{_DEMO_IMG_BASE}/welcome.jpg"
_IMG_GOLD = f"{_DEMO_IMG_BASE}/gold.jpg"
_IMG_DIAMOND = f"{_DEMO_IMG_BASE}/diamond.jpg"
_IMG_SILVER = f"{_DEMO_IMG_BASE}/silver.jpg"
_IMG_BRIDAL = f"{_DEMO_IMG_BASE}/bridal.jpg"

_WELCOME_TEXT = "\U0001f48d Welcome to {{business_name}}! Discover exquisite jewellery, made to be seen in person."


TEMPLATE = {
    "code": "jewellers",
    "name": "Jewellers",
    "action_type": "inquiry",
    "icon": "\U0001f48d",  # 💍
    "welcome_message": _WELCOME_TEXT,
    "welcome_banner_image": _IMG_WELCOME,
    "welcome_buttons": [
        {"id": "welcome:explore_design", "title": "\U0001f5bc️ Explore Design"},
        {"id": "welcome:appointment", "title": "\U0001f4c5 Book Appointment"},
        {"id": "welcome:offers", "title": "\U0001f381 Offers"},
        {"id": "welcome:store", "title": "\U0001f4cd Visit Our Store"},
        {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
        {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
    ],
    "default_catalog": [
        {
            "name": "Gold Jewellery",
            "icon_image": _IMG_GOLD,
            "items": [
                {
                    "name": "Gold Necklace",
                    "description": "22K gold necklace, handcrafted finish. Price varies by weight and purity.",
                    "price": 85000,
                    "price_type": "starting_from",
                    "images": [_IMG_GOLD],
                    "attributes": {"material": "22K Gold"},
                },
                {
                    "name": "Gold Bangles",
                    "description": "Set of 22K gold bangles with intricate detailing.",
                    "price": 45000,
                    "price_type": "starting_from",
                    "images": [_IMG_GOLD],
                    "attributes": {"material": "22K Gold"},
                },
            ],
        },
        {
            "name": "Diamond Jewellery",
            "icon_image": _IMG_DIAMOND,
            "items": [
                {
                    "name": "Diamond Ring",
                    "description": "Solitaire diamond ring set in 18K white gold.",
                    "price": 65000,
                    "price_type": "starting_from",
                    "images": [_IMG_DIAMOND],
                    "attributes": {"material": "18K Gold + Diamond"},
                },
                {
                    "name": "Diamond Earrings",
                    "description": "Classic diamond stud earrings, everyday elegance.",
                    "price": 38000,
                    "price_type": "starting_from",
                    "images": [_IMG_DIAMOND],
                    "attributes": {"material": "18K Gold + Diamond"},
                },
            ],
        },
        {
            "name": "Silver Jewellery",
            "icon_image": _IMG_SILVER,
            "items": [
                {
                    "name": "Silver Bracelet",
                    "description": "Sterling silver bracelet with oxidised finish.",
                    "price": 3500,
                    "price_type": "fixed",
                    "images": [_IMG_SILVER],
                    "attributes": {"material": "925 Sterling Silver"},
                },
                {
                    "name": "Silver Anklet",
                    "description": "Everyday sterling silver anklet, lightweight.",
                    "price": 2200,
                    "price_type": "fixed",
                    "images": [_IMG_SILVER],
                    "attributes": {"material": "925 Sterling Silver"},
                },
            ],
        },
        {
            "name": "Bridal Collection",
            "icon_image": _IMG_BRIDAL,
            "items": [
                {
                    "name": "Bridal Necklace Set",
                    "description": "Statement bridal necklace set with matching earrings. Price varies by weight.",
                    "price": 250000,
                    "price_type": "starting_from",
                    "images": [_IMG_BRIDAL],
                    "attributes": {"material": "22K Gold"},
                },
            ],
        },
    ],
    # See app/models/flow_definition.py for the exact per-step shape. Steps map onto
    # welcome -> category -> piece -> piece details (photo gallery) -> preferred visit ->
    # requirements -> name confirm -> inquiry confirm -> submitted, plus side-branch
    # "message"/human_handoff steps off welcome that don't lead into the lead-capture chain.
    "default_flow_steps": [
        {
            "step_id": "welcome",
            "type": "menu_select",
            "prompt": _WELCOME_TEXT,
            "buttons_from": "static",
            "static_options": [
                {"id": "welcome:explore_design", "title": "\U0001f5bc️ Explore Design"},
                {"id": "welcome:appointment", "title": "\U0001f4c5 Book Appointment"},
                {"id": "welcome:offers", "title": "\U0001f381 Offers"},
                {"id": "welcome:store", "title": "\U0001f4cd Visit Our Store"},
                {"id": "welcome:contact", "title": "\U0001f4de Contact Us"},
                {"id": "welcome:human", "title": "\U0001f9d1 Talk to a Human"},
            ],
            "routes": {
                "welcome:explore_design": "material_select",
                "welcome:appointment": "category_select",
                "welcome:offers": "offers_info",
                "welcome:store": "location_info",
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
            "prompt": "\U0001f381 *Today's Offers*\n\nAsk our team about special offers and festive discounts any time you enquire!",
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
            "message": "\U0001f9d1 Connecting you with our jewellery expert at {{business_name}} -- someone will reply here shortly.",
            "back_target": "welcome",
        },
        {
            # Isolated jewellery-only visual carousel: Material/Finish -> Category ->
            # paginated Design gallery. A parallel path alongside the enquiry flow above
            # (category_select/item_select/piece_details) -- not a replacement for it;
            # "Explore Collection"/"Book Appointment" still work exactly as before. See
            # generic_flow_engine.py's JewelleryDesignRepository-backed "jewellery_materials"
            # source and _render_jewellery_gallery for the engine side of this.
            # [Back -> Welcome]
            "step_id": "material_select",
            "type": "menu_select",
            "prompt": "Choose your preferred finish:",
            "buttons_from": "jewellery_materials",
            "capture_key": "material",
            "back_target": "welcome",
            "next": "jewellery_category_select",
            "show_image": False,
            "section_title": "Materials",
        },
        {
            # Material tapped -> Category list scoped to that material.
            # [Back -> Material list]
            "step_id": "jewellery_category_select",
            "type": "menu_select",
            "prompt": "Explore {{material_label}} Jewellery -- choose a category:",
            "buttons_from": "jewellery_categories",
            "capture_key": "jewellery_category",
            "back_target": "material_select",
            "next": "design_gallery",
            "show_image": False,
            "section_title": "Categories",
        },
        {
            # Category tapped -> paginated design images (page_size per page, "Load More"
            # for the next batch -- see JEWELLERY_LOAD_MORE_REPLY_ID in
            # generic_flow_engine.py). Never sends the full design set at once, however
            # large the underlying catalogue is. [Back -> Category list]
            "step_id": "design_gallery",
            "type": "jewellery_design_gallery",
            "page_size": 10,
            "back_target": "jewellery_category_select",
        },
        {
            # "Explore Collection"/"Book Appointment" tapped -> Category list.
            # [Back -> Welcome]
            "step_id": "category_select",
            "type": "menu_select",
            "prompt": "\U0001f48d What would you like to explore today?",
            "buttons_from": "categories",
            "capture_key": "category_id",
            "back_target": "welcome",
            "next": "item_select",
            "show_image": True,
            "section_title": "Categories",
        },
        {
            # Category tapped -> Piece list (name + price, tap = select).
            # [Back -> Category list]
            "step_id": "item_select",
            "type": "menu_select",
            "prompt": "Here's our *{{category_id_label}}* collection -- tap a piece to enquire about it:",
            "buttons_from": "items",
            "category_context_key": "category_id",
            "capture_key": "item_id",
            "action": "capture_pending_item",
            "back_target": "category_select",
            "next": "piece_details",
            "show_image": True,
            "section_title": "Pieces",
        },
        {
            # Piece tapped -> its own detail view: every active photo Super Admin has
            # curated for this piece (see app/services/image_presenter.py), each with its
            # own caption, in order -- not just one representative photo. See
            # generic_flow_engine.py::_Engine._send_options's item_context_key branch.
            # [Back -> Piece list]
            "step_id": "piece_details",
            "type": "menu_select",
            "prompt": "*{{item_id_label}}*\n\n\U0001f3f7️ *Price:* {{pending_item_price}}\n\nTake a look at the photos below, then tap when you're ready to enquire.",
            "item_context_key": "item_id",
            "show_image": True,
            "buttons_from": "static",
            "static_options": [{"id": "piece:enquire", "title": "\U0001f48e Enquire Now"}],
            "routes": {"piece:enquire": "visit_capture"},
            "next": "visit_capture",
            "back_target": "item_select",
        },
        {
            # Optional preferred visit note. [Back -> Piece details]
            "step_id": "visit_capture",
            "type": "free_text_input",
            "prompt": "\U0001f4c5 Would you like to visit us to see *{{item_id_label}}* in person?\n\nLet us know your preferred day and time, or tap Skip to enquire online instead.",
            "capture_key": "preferred_visit",
            "allow_skip": True,
            "back_target": "piece_details",
            "next": "requirements_capture",
        },
        {
            # Optional free-form requirements (customization/budget). [Back -> visit note]
            "step_id": "requirements_capture",
            "type": "free_text_input",
            "prompt": "\U0001f4dd Any customization or budget preferences we should know? (or tap Skip)",
            "capture_key": "requirements",
            "allow_skip": True,
            "back_target": "visit_capture",
            "next": "name_confirm",
        },
        {
            # Name confirmation, auto-pulled from the WhatsApp profile and editable via
            # a button. [Back -> requirements note]
            "step_id": "name_confirm",
            "type": "menu_select",
            "prompt": "\U0001f9d1 Please confirm the name we should use for this enquiry:\n\n*{{customer_name}}*",
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
            "prompt": "Please type the name we should use for this enquiry:",
            "capture_key": "customer_name_override",
            "allow_skip": False,
            "next": "inquiry_confirm",
            "back_target": "name_confirm",
        },
        {
            # Enquiry review card -> "Submit Enquiry" button. [Back -> name confirmation]
            "step_id": "inquiry_confirm",
            "type": "confirm_action",
            "prompt": (
                "\U0001f48e *Review Your Enquiry*\n\n"
                "\U0001f48d *Piece:* {{item_id_label}}\n"
                "\U0001f4c5 *Preferred Visit:* {{preferred_visit}}\n"
                "\U0001f4dd *Notes:* {{requirements}}\n\n"
                "Tap below to submit."
            ),
            "buttons_from": "static",
            "static_options": [{"id": "inquiry:submit", "title": "Submit Enquiry"}],
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
                "✅ *Thank you!* Your enquiry has been submitted.\nReference: {{last_reference_number}}\n\n"
                "Our jewellery expert will reach out shortly to discuss *{{item_id_label}}* and arrange a "
                "visit if you'd like."
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
        "catalog_label": "Collection",
        "category_label": "Jewellery Category",
        "item_label": "Piece",
    },
    "default_modules": {},
}
