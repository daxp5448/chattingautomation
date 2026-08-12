import enum


class UserRole(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    OWNER = "owner"
    MANAGER = "manager"
    CASHIER = "cashier"
    KITCHEN = "kitchen"


class RestaurantStatus(str, enum.Enum):
    ACTIVE = "active"
    # Temporary, reversible: e.g. a late subscription payment. The bot stops responding
    # to customers while suspended (see app/api/v1/routers/webhook.py), but every setting
    # is preserved and reactivating (PATCH status back to "active") brings it straight
    # back with nothing to reconfigure.
    SUSPENDED = "suspended"
    ONBOARDING = "onboarding"
    # Terminal: the restaurant left the platform. Same bot-blocking effect as SUSPENDED,
    # but distinct so "why is this account off" is answerable at a glance, and so a
    # future data-retention/export job has something unambiguous to key off. There is no
    # DELETE /restaurants endpoint -- cancelling never destroys data.
    CANCELLED = "cancelled"


class BranchStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    PREPARING = "preparing"
    READY = "ready"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, enum.Enum):
    COD = "cod"
    RAZORPAY = "razorpay"
    STRIPE = "stripe"
    PHONEPE = "phonepe"
    UPI = "upi"


class ConversationStep(str, enum.Enum):
    WELCOME = "welcome"
    SELECT_BRANCH = "select_branch"
    SELECT_CATEGORY = "select_category"
    SELECT_PRODUCT = "select_product"
    SELECT_QUANTITY = "select_quantity"
    CART = "cart"
    SELECT_FULFILLMENT = "select_fulfillment"
    COLLECT_COUPON = "collect_coupon"
    COLLECT_ADDRESS = "collect_address"
    CONFIRM_ORDER = "confirm_order"
    COMPLETED = "completed"
    HANDED_OVER = "handed_over"


class FulfillmentType(str, enum.Enum):
    DELIVERY = "delivery"
    PICKUP = "pickup"


class CouponType(str, enum.Enum):
    FLAT = "flat"
    PERCENTAGE = "percentage"


class LoyaltyReason(str, enum.Enum):
    EARNED = "earned"
    REDEEMED = "redeemed"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageSender(str, enum.Enum):
    CUSTOMER = "customer"
    BOT = "bot"
    STAFF = "staff"


# --- Generic multi-niche platform (app/services/generic_flow_engine.py) -------------
# Deliberately separate from the restaurant-specific enums above rather than extending
# them -- see GenericConversationState/Engagement docstrings for why this is a fully
# parallel system, not a variant of the legacy one.


class EngagementType(str, enum.Enum):
    """What kind of "thing happened" a completed generic-engine flow produces. Drives
    which fields on Engagement are meaningful and which notify_business() copy is used --
    see app/services/generic_flow_engine.py::ACTION_VERBS["create_engagement"]."""

    ORDER = "order"
    INQUIRY = "inquiry"
    APPOINTMENT = "appointment"
    BOOKING = "booking"


class EngagementStatus(str, enum.Enum):
    """One small generic status set shared by all 4 engagement types, deliberately not
    reusing OrderStatus's PREPARING/READY (kitchen-specific, meaningless for a booking or
    an inquiry). A niche template's `terminology.status_labels` supplies the
    customer/staff-facing label per status per niche (e.g. "confirmed" reads as
    "Preparing" for a restaurant order, "Confirmed" for a salon booking) -- the underlying
    status code here never changes per niche, only its displayed label does."""

    NEW = "new"
    CONFIRMED = "confirmed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class FlowStepType(str, enum.Enum):
    """The fixed, engine-known set of step shapes every niche's flow is built from --
    see app/services/generic_flow_engine.py module docstring.

    The last 5 values are additive (Phase 2 Item 3, Drag & Drop Flow Builder) and are
    all "auto-advancing" except HUMAN_HANDOFF -- they run without waiting for customer
    input, see generic_flow_engine.py's _advance_and_render. "Buttons"/"list"/"payment"
    nodes in the visual builder deliberately do NOT get their own step type here -- they
    already map onto MENU_SELECT and CONFIRM_ACTION respectively (see that module's
    docstring for why), a UI-only distinction, not a new engine concept.
    """

    MESSAGE = "message"
    MENU_SELECT = "menu_select"
    QUANTITY_INPUT = "quantity_input"
    FREE_TEXT_INPUT = "free_text_input"
    CONFIRM_ACTION = "confirm_action"
    CONDITION = "condition"
    DELAY = "delay"
    API_CALL = "api_call"
    HUMAN_HANDOFF = "human_handoff"
    AI_RESPONSE = "ai_response"


# --- WhatsApp Template Manager (app/services/whatsapp_template_client.py) -----------


class TemplateCategory(str, enum.Enum):
    """Meta's own Message Template categories -- drives review requirements on Meta's
    side (e.g. AUTHENTICATION templates have a restricted, largely fixed body)."""

    MARKETING = "marketing"
    UTILITY = "utility"
    AUTHENTICATION = "authentication"


class TemplateStatus(str, enum.Enum):
    """DRAFT is local-only (never submitted to Meta); the rest mirror Meta's own
    Message Template status vocabulary. See app/models/whatsapp_template.py."""

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DISABLED = "disabled"


# --- Broadcast Module (app/tasks/broadcast_sender.py) -------------------------------


class BroadcastStatus(str, enum.Enum):
    """See app/models/broadcast.py::BroadcastCampaign."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BroadcastRecipientStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    # Excluded at send time (not snapshot time) because the customer blocked themselves
    # or was anonymized after the campaign started -- see app/tasks/broadcast_sender.py.
    SKIPPED = "skipped"
