import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import RestaurantStatus


class RestaurantBase(BaseModel):
    name: str
    logo_url: str | None = None
    cover_image_url: str | None = None
    gst_number: str | None = None
    address: str | None = None
    state: str | None = None
    support_number: str | None = None
    email: EmailStr | None = None
    opening_hours: dict[str, Any] = {}
    currency: str = "INR"
    timezone: str = "Asia/Kolkata"
    delivery_charge: float = 0
    tax_settings: dict[str, Any] = {}
    theme: dict[str, Any] = {}
    invoice_footer: str | None = None
    terms_and_conditions: str | None = None
    privacy_policy: str | None = None
    refund_policy: str | None = None
    payment_methods: list[str] = ["cod"]
    default_payment_method: str = "cod"
    loyalty_settings: dict[str, Any] = {}
    conversation_settings: dict[str, Any] = {}


class RestaurantCreate(RestaurantBase):
    slug: str
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    # Meta/Facebook Commerce Catalog id connected to this business's WABA -- see
    # app/models/restaurant.py::whatsapp_catalog_id. Optional; unset means the jewellery
    # design carousel (and any future catalog-message feature) falls back to its plain
    # sequential-image behavior instead of a native product_list message.
    whatsapp_catalog_id: str | None = None
    whatsapp_access_token: str | None = None
    whatsapp_verify_token: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    # If omitted, an owner login is auto-generated from the slug -- see create_restaurant.
    owner_email: EmailStr | None = None
    # NicheTemplate.code (e.g. "restaurant", "salon") -- if set, the new business is
    # provisioned onto the generic multi-niche engine with that template's default
    # catalog/flow instead of the legacy restaurant-only flow. See
    # app/services/niche_provisioning.py.
    niche_code: str | None = None
    # Marks this restaurant as part of the Demo Bot (see app/services/demo_bot_service.py)
    # rather than a real business -- Super Admin only, set once when creating the one
    # sentinel "Demo Bot" restaurant. Per-niche demo restaurants are auto-provisioned by
    # app/services/demo_restaurant_sync.py, never created through this endpoint directly.
    is_demo: bool = False
    # Which FeaturePackage to assign at creation -- if omitted, whichever package has
    # is_default=True is used (if any); if neither is set, enabled_features stays None
    # (unrestricted). See create_restaurant and app/models/feature_package.py.
    feature_package_id: uuid.UUID | None = None


class RestaurantUpdate(BaseModel):
    name: str | None = None
    logo_url: str | None = None
    cover_image_url: str | None = None
    gst_number: str | None = None
    address: str | None = None
    state: str | None = None
    support_number: str | None = None
    email: EmailStr | None = None
    opening_hours: dict[str, Any] | None = None
    currency: str | None = None
    timezone: str | None = None
    delivery_charge: float | None = None
    tax_settings: dict[str, Any] | None = None
    theme: dict[str, Any] | None = None
    invoice_footer: str | None = None
    terms_and_conditions: str | None = None
    privacy_policy: str | None = None
    refund_policy: str | None = None
    payment_methods: list[str] | None = None
    default_payment_method: str | None = None
    loyalty_settings: dict[str, Any] | None = None
    conversation_settings: dict[str, Any] | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    whatsapp_catalog_id: str | None = None
    whatsapp_quick_customize_flow_id: str | None = None
    whatsapp_quick_customize_flow_draft_mode: bool | None = None
    whatsapp_access_token: str | None = None
    whatsapp_verify_token: str | None = None
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None
    status: RestaurantStatus | None = None
    trial_ends_at: datetime | None = None
    broadcast_daily_cap: int | None = None
    # Super-admin-only (see subscription_fields in update_restaurant) -- reassigning
    # re-snapshots enabled_features server-side. enabled_features itself is deliberately
    # NEVER a directly PATCHable field anywhere in this schema -- only the server-side
    # assignment logic sets it, closing a privilege-escalation path an Owner could
    # otherwise use to grant themselves any feature by PATCHing their own restaurant.
    feature_package_id: uuid.UUID | None = None


class RestaurantRead(RestaurantBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    whatsapp_phone_number_id: str | None
    whatsapp_business_account_id: str | None
    whatsapp_catalog_id: str | None = None
    # Presence (not the id's value itself) is what the frontend needs -- whether native
    # WhatsApp Flow ordering is enabled. The private key is never exposed here or anywhere
    # else via the API; only POST .../whatsapp-flow/enable|disable ever touches it.
    whatsapp_flow_order_id: str | None
    # Unlike whatsapp_flow_order_id above (internal-only, set exclusively by the
    # enable/disable endpoints), this one IS directly admin-settable -- see
    # Restaurant.whatsapp_quick_customize_flow_id's model docstring for why: it's a
    # manually-built Flow, so there's no "create it for me" endpoint to call, only an
    # existing id to paste in.
    whatsapp_quick_customize_flow_id: str | None = None
    whatsapp_quick_customize_flow_draft_mode: bool = False
    razorpay_key_id: str | None
    status: RestaurantStatus
    trial_ends_at: datetime | None
    # Which conversation engine this business runs on -- the frontend's /home-builder
    # page reads this to decide whether to call the legacy BotButton CRUD or the generic
    # engine's home-buttons endpoint. See app/models/restaurant.py::uses_generic_engine.
    uses_generic_engine: bool
    niche_type: str | None
    # See app/services/demo_bot_service.py -- true for the sentinel Demo Bot restaurant
    # and every per-niche demo restaurant it fans out to. The frontend uses this to
    # exclude demo restaurants from normal business lists/counts.
    is_demo: bool
    # See app/models/restaurant.py::demo_sends_via_restaurant_id -- set on a per-niche demo
    # showcase restaurant that has no WhatsApp credentials of its own and sends through the
    # sentinel Flagship restaurant instead. The frontend uses this to show "Connected (via
    # Flagship)" rather than a misleading "Not configured" for these businesses.
    demo_sends_via_restaurant_id: uuid.UUID | None = None
    # See app/models/restaurant.py::demo_mode_enabled -- true while this business's own
    # WhatsApp number is temporarily repointed at the Demo Bot's industry picker instead
    # of its normal order flow. Distinct from is_demo (which marks a restaurant as never
    # having real customers at all).
    demo_mode_enabled: bool
    demo_enabled_niche_codes: list[str] | None
    # Admin-set safety cap for the Broadcast Module (app/api/v1/routers/broadcasts.py) --
    # not a live query against Meta's real messaging tier. See app/models/restaurant.py.
    broadcast_daily_cap: int
    # See app/models/restaurant.py::enabled_features -- None means unrestricted (every
    # Feature Package gate passes). The frontend's hasFeature() helper treats None the
    # same way app/core/deps.py::require_feature does.
    feature_package_id: uuid.UUID | None
    enabled_features: list[str] | None
    created_at: datetime
    updated_at: datetime


class RestaurantListItem(RestaurantRead):
    """The super-admin restaurants list gets a couple of extra at-a-glance fields that
    nowhere else needs (and that would cost an extra query on every single-restaurant
    read if they were on RestaurantRead itself) -- see GET /restaurants."""

    total_orders: int = 0
    last_order_at: datetime | None = None


class RestaurantCreateResult(RestaurantRead):
    """Returned only from POST /restaurants. Instead of a plaintext temporary password,
    the owner account is created unusable-for-login until they complete a one-time setup
    flow at `setup_url` (see app/core/security.py:generate_setup_token and
    POST /auth/setup); the raw setup token is embedded in that URL and never stored or
    returned again after this one response."""

    owner_email: str
    setup_url: str


class DemoBotNicheStatus(BaseModel):
    """One row of the /niches page's read-only 'Demo Bot' status panel -- see
    app/services/demo_bot_service.py / app/services/demo_restaurant_sync.py."""

    code: str
    name: str
    has_demo_restaurant: bool


class DemoBotStatus(BaseModel):
    sentinel_configured: bool
    niches: list[DemoBotNicheStatus]


class DemoModeUpdate(BaseModel):
    """Body for PATCH /restaurants/{id}/demo-mode -- Super Admin only, deliberately its
    own tiny endpoint/schema rather than folded into RestaurantUpdate, since flipping this
    on pauses a live business's real order-taking and shouldn't be reachable through the
    same general-purpose PATCH an Owner can call on their own restaurant."""

    enabled: bool
    # Omitted (unset) field leaves the current selection untouched (router uses
    # exclude_unset). Explicit null means "show every niche that has a demo restaurant" --
    # the same default the sentinel Demo Bot restaurant has always had. Explicit []
    # means "show nothing until niches are selected" (demo_bot_service.py's existing
    # fallback copy for that case). Only validated against real NicheTemplate codes at the
    # router, not here -- this schema stays a pure shape check.
    niche_codes: list[str] | None = None
