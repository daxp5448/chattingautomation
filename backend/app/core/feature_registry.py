"""The fixed catalog of feature codes a FeaturePackage (app/models/feature_package.py) can
bundle. Deliberately a code constant, not a database table, admin-editable list, or anything
else data-driven -- unlike a niche/menu/flow/template (which Super Admin can author from
nothing because the underlying engine is generic), each entry here corresponds to real,
specific functionality that had to be built; the catalog can't grow by someone typing a new
string into a form. What IS fully Super-Admin-driven, with no code change, is which of these
codes go into which package and which package a business is on -- see
app/api/v1/routers/feature_packages.py and app/core/deps.py::require_feature.

Deliberately narrow (5 codes, not the full ~57-row catalog in SUPER_ADMIN_FEATURES.md):
gating only covers genuinely optional add-ons a business can fully operate without. Core
transactional capability (ordering, payment, the running conversation flow, catalog photos,
multi-branch, POS/KDS, dashboard) is never gated -- see the approved plan's "deliberately
excluded, not forgotten" section for why each of those was cut from v1.
"""

FEATURE_REGISTRY: dict[str, str] = {
    "coupons": "Coupons & Discounts",
    "faq_autoresponder": "FAQ Auto-Responder",
    "whatsapp_template_manager": "WhatsApp Template Manager",
    "broadcasts": "Broadcast Campaigns",
    "live_chat_handoff": "Human Handoff / Live Chat",
}
