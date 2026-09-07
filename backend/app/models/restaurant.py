from datetime import datetime
from typing import Any

import uuid

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import GUID
from app.models.enums import RestaurantStatus


class Restaurant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "restaurants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    cover_image_url: Mapped[str | None] = mapped_column(String(500))
    gst_number: Mapped[str | None] = mapped_column(String(50))
    address: Mapped[str | None] = mapped_column(String(500))
    # Groundwork only -- not consumed by any tax logic yet. Captured now so a future
    # IGST-vs-CGST/SGST split (inter-state vs intra-state supply) has something to key
    # off; see the comment in app/services/invoice_service.py::generate_invoice_pdf.
    state: Mapped[str | None] = mapped_column(String(100))
    support_number: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))

    opening_hours: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata")
    delivery_charge: Mapped[float] = mapped_column(default=0)
    tax_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    theme: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    invoice_footer: Mapped[str | None] = mapped_column(String(1000))
    terms_and_conditions: Mapped[str | None] = mapped_column(String(5000))
    privacy_policy: Mapped[str | None] = mapped_column(String(5000))
    refund_policy: Mapped[str | None] = mapped_column(String(5000))

    whatsapp_phone_number_id: Mapped[str | None] = mapped_column(
        String(50), unique=True, index=True
    )
    whatsapp_business_account_id: Mapped[str | None] = mapped_column(String(50))
    whatsapp_access_token_encrypted: Mapped[str | None] = mapped_column(String(2000))
    whatsapp_verify_token: Mapped[str | None] = mapped_column(String(200))
    # Meta/Facebook Commerce Catalog id connected to this business's WABA, needed for the
    # real native WhatsApp "Multi-Product Message" (swipeable product_list carousel --
    # see OutboundMessage.product_list in app/services/whatsapp_client.py). NULL for
    # every restaurant today (nobody has a Commerce Catalog connected yet) -- purely
    # additive groundwork, same non-breaking-by-default bias as whatsapp_flow_order_id
    # above: until an Owner/Super Admin explicitly sets this, nothing changes.
    # app/services/generic_flow_engine.py::_render_jewellery_gallery only takes the
    # native product_list branch when this is set AND at least one design on the current
    # page has a JewelleryDesign.meta_retailer_id -- otherwise it falls through to the
    # existing sequential-image carousel completely unchanged.
    whatsapp_catalog_id: Mapped[str | None] = mapped_column(String(50))

    # Native WhatsApp Flow ordering (see the approved "WhatsApp Flows for Ordering" plan) --
    # both NULL means off, same bias as enabled_features/uses_generic_engine: every
    # pre-existing restaurant is completely unaffected until an Owner explicitly opts in via
    # POST .../whatsapp-flow/enable. The private key is per-WABA (Meta's own requirement,
    # "use a dedicated ... encryption key pair for each WABA"), encrypted at rest the same
    # way whatsapp_access_token_encrypted already is.
    whatsapp_flow_order_id: Mapped[str | None] = mapped_column(String(50))
    whatsapp_flow_private_key_encrypted: Mapped[str | None] = mapped_column(String(4000))

    # A SECOND, independent WhatsApp Flow slot -- deliberately separate from
    # whatsapp_flow_order_id above, not a rename/reuse of it. That one is this platform's
    # own auto-provisioned, multi-screen, catalog-browsing Flow (dynamic data-exchange,
    # created fresh per-restaurant by POST .../whatsapp-flow/enable -- see
    # whatsapp_flow_order_service.py's ORDER_FLOW_JSON). This one holds the id of a Flow
    # an admin built manually in Meta's own Flow Builder UI and wants to use as-is --
    # single static screen (item/quantity/notes), no endpoint, so its submission arrives
    # as a plain `nfm_reply` webhook message (see webhook.py's nfm_reply handling), not
    # through the encrypted data-exchange path the auto-provisioned Flow uses. No private
    # key needed here for exactly that reason -- a static Flow's final submission isn't
    # Meta-encrypted the way a dynamic Flow's screen-to-screen data-exchange calls are.
    # NULL means off, same bias as every other opt-in Flow field on this model.
    whatsapp_quick_customize_flow_id: Mapped[str | None] = mapped_column(String(50))
    # Meta only delivers a DRAFT-status Flow to phone numbers registered as test numbers
    # for the WhatsApp app that owns it -- true here is an explicit acknowledgment of that
    # real constraint (adds "mode": "draft" to the outbound Flow message), not a general
    # "developer mode" switch. An Owner must flip this to false once the Flow is
    # published in Meta's Flow Builder, or real customers (not on the test-number list)
    # simply won't receive it.
    whatsapp_quick_customize_flow_draft_mode: Mapped[bool] = mapped_column(Boolean, default=False)

    # Payment: which methods this restaurant accepts, and gateway credentials.
    # Generic per-gateway columns (rather than a dedicated Razorpay table) so the next
    # gateway (Stripe/PhonePe/UPI) slots in the same way without schema churn.
    payment_methods: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["cod"])
    default_payment_method: Mapped[str] = mapped_column(String(20), default="cod")
    razorpay_key_id: Mapped[str | None] = mapped_column(String(200))
    razorpay_key_secret_encrypted: Mapped[str | None] = mapped_column(String(2000))
    razorpay_webhook_secret_encrypted: Mapped[str | None] = mapped_column(String(2000))

    loyalty_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Conversational tone for the WhatsApp bot -- read generically by
    # generic_flow_engine.py's conversational_style.humanize(), never branched on by
    # niche_type. Keys: "tone" (free label, e.g. "friendly_casual"/"premium_elegant"),
    # "language" ("en"/"hinglish"/"auto"), "emoji_level" ("none"/"low"/"high"),
    # "response_length" ("short"/"normal"), "business_personality" (free label, display
    # only). Empty dict (the default) means humanize() no-ops entirely -- zero behavior
    # change for a tenant that hasn't configured this. Populated at provisioning time
    # from NicheTemplate.default_personality (see niche_provisioning.py), then freely
    # editable per-business afterward like any other tenant setting. Plain JSON, not
    # MutableDict -- always assign a whole new dict, never mutate in place (see
    # niche_provisioning.py's loyalty_settings comment for why).
    conversation_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[RestaurantStatus] = mapped_column(
        default=RestaurantStatus.ONBOARDING, nullable=False
    )
    # Informational only -- nothing automatically suspends a restaurant when this date
    # passes (subscription billing here is a manual super_admin action, see
    # app/api/v1/routers/restaurants.py::update_restaurant). This is just so "who's
    # coming due" is visible instead of tracked in someone's head or a spreadsheet. Set
    # automatically to signup time + 7 days for self-serve businesses (see
    # app/api/v1/routers/signup.py), still manually adjustable by a super_admin afterward.
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # DEMO ONLY -- no real payment gateway is involved (see
    # app/api/v1/routers/billing.py's docstring). True once the owner clicks "Pay Now" on
    # the demo paywall after their trial ends. Not read by webhook gating, dashboard
    # blocking, or anything else in the platform -- exists purely so the frontend banner
    # can show "paid" instead of re-prompting after a demo payment.
    is_demo_billing_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Generic multi-niche platform ------------------------------------------------
    # The single switch app/api/v1/routers/webhook.py checks to decide which engine
    # handles this business's inbound messages. Defaults False so every row that exists
    # before this column was added (including the live Prince Corner restaurant) is
    # completely unaffected -- it keeps running on the original flow_engine.py exactly as
    # before. Only businesses created through POST /restaurants/generic (see
    # app/services/niche_provisioning.py) ever get this set True.
    uses_generic_engine: Mapped[bool] = mapped_column(default=False, nullable=False)
    # Which NicheTemplate.code this business was provisioned from -- kept even though the
    # template itself may change later, purely for admin-panel display ("Salon" instead
    # of a raw code) and support/analytics ("how many businesses are on each niche").
    niche_type: Mapped[str | None] = mapped_column(String(50))
    # WhatsApp number (with country code, no "+") the generic engine's notify_business()
    # sends a message to on every completed order/inquiry/appointment/booking. Separate
    # from support_number (that's customer-facing; this is staff-facing) and from the
    # legacy flow's live-chat handover, which notifies via the admin dashboard instead.
    staff_notification_number: Mapped[str | None] = mapped_column(String(30))

    # --- Demo Bot (Phase 1 Item 4) -----------------------------------------------------
    # True for the one sentinel "Demo Bot" restaurant (owns the real demo WhatsApp
    # number) and every auto-provisioned per-niche demo restaurant it fans out to -- see
    # app/services/demo_bot_service.py. Used to: route inbound messages to the demo
    # dispatcher instead of the normal engine (app/api/v1/routers/webhook.py), exclude
    # demo restaurants from Super-Admin business/analytics listings, and enforce that a
    # demo restaurant's completed engagements never trigger a real payment link or staff
    # notification (app/services/generic_flow_engine.py::_Engine._create_engagement) --
    # that enforcement is explicit and unconditional, not merely a side effect of demo
    # restaurants never having Razorpay/staff-notification fields configured.
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set only on a per-niche demo restaurant, pointing at the sentinel -- the demo
    # restaurant owns no real WhatsApp number of its own (whatsapp_phone_number_id stays
    # NULL), so app/services/generic_flow_engine.py::send_generic_message resolves the
    # actual send credentials from this restaurant instead when it's set. NULL for the
    # sentinel itself and for every real (non-demo) restaurant, which keeps sending via
    # its own credentials exactly as before this column existed.
    demo_sends_via_restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("restaurants.id", ondelete="SET NULL"), nullable=True
    )

    # --- Demo Mode on a REAL business's own WhatsApp number ---------------------------
    # Distinct from is_demo above (which marks a restaurant as never having real
    # customers at all). This lets a Super Admin temporarily repoint an already-live
    # restaurant's own connected WhatsApp number at the Demo Bot's industry-picker
    # dispatcher (app/services/demo_bot_service.py) instead of that restaurant's normal
    # order flow -- see app/api/v1/routers/webhook.py's routing check. Defaults False so
    # every existing restaurant (Prince Corner included) is completely unaffected until a
    # Super Admin explicitly flips it on for a live sales demo; flipping it back off
    # restores normal order-taking instantly, since this is purely a routing flag -- no
    # data is moved or deleted either direction.
    demo_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Which NicheTemplate.code values appear in the picker while demo_mode_enabled is on.
    # NULL means "show every niche that has a demo restaurant provisioned" (the same
    # behavior the sentinel Demo Bot restaurant has always had) -- only a non-null list
    # narrows it, so this is additive/opt-in, never a behavior change for the existing
    # sentinel restaurant.
    demo_enabled_niche_codes: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)

    # --- Broadcast Module (app/api/v1/routers/broadcasts.py) --------------------------
    # An admin-set safety cap, not a live query against Meta's real messaging tier (that
    # would need its own Graph API integration, out of scope for this pass) -- defaults
    # to 250, Meta's lowest tier, so a business that hasn't confirmed its real tier can't
    # accidentally blow through it and risk Meta's anti-spam/quality-rating enforcement.
    broadcast_daily_cap: Mapped[int] = mapped_column(default=250, nullable=False)

    # --- Feature Packages (Super Admin entitlements) -----------------------------------
    # Which FeaturePackage this business was last assigned -- informational (what to show
    # as selected in the admin dropdown), NOT the source of truth for gating, since
    # assignment SNAPSHOT-COPIES feature_codes into enabled_features below rather than
    # keeping a live reference (see FeaturePackage's own docstring for why: editing a
    # package later must never retroactively change a business already on it).
    feature_package_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("feature_packages.id", ondelete="SET NULL"), nullable=True
    )
    # The actual, authoritative set of gated feature codes this business has, snapshotted
    # from a FeaturePackage.feature_codes at assignment time -- see
    # app/core/deps.py::require_feature for enforcement. NULL (not an empty list) means
    # "never assigned a package" and is treated as UNRESTRICTED (every gate passes), the
    # same non-breaking-by-default bias uses_generic_engine's own comment documents above:
    # every restaurant that exists before this column was added (including Prince Corner,
    # and every demo restaurant app/services/demo_restaurant_sync.py creates) stays NULL
    # and is completely unaffected by this feature. Only a restaurant explicitly assigned
    # a package (via POST/PATCH /restaurants, see restaurants.py) ever gets a real --
    # possibly empty -- list here.
    enabled_features: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)

    branches = relationship("Branch", back_populates="restaurant", cascade="all, delete-orphan")
    categories = relationship("Category", back_populates="restaurant", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="restaurant", cascade="all, delete-orphan")
    customers = relationship("Customer", back_populates="restaurant", cascade="all, delete-orphan")
    orders = relationship("Order", back_populates="restaurant", cascade="all, delete-orphan")
    bot_messages = relationship("BotMessage", back_populates="restaurant", cascade="all, delete-orphan")
    bot_buttons = relationship("BotButton", back_populates="restaurant", cascade="all, delete-orphan")
    users = relationship("User", back_populates="restaurant", cascade="all, delete-orphan")
    coupons = relationship("Coupon", back_populates="restaurant", cascade="all, delete-orphan")
    faq_entries = relationship("FaqEntry", back_populates="restaurant", cascade="all, delete-orphan")
