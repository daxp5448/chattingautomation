export interface Restaurant {
  id: string;
  name: string;
  slug: string;
  support_number: string | null;
  email: string | null;
  logo_url: string | null;
  cover_image_url: string | null;
  currency: string;
  timezone: string;
  delivery_charge: number;
  status: "active" | "suspended" | "onboarding" | "cancelled";
  trial_ends_at: string | null;
  // Which conversation engine this business runs on -- see /home-builder, which reads
  // this to decide whether to call the legacy BotButton CRUD or the generic engine's
  // home-buttons endpoint.
  uses_generic_engine: boolean;
  niche_type: string | null;
  // True for the sentinel Demo Bot restaurant and every per-niche demo restaurant it
  // fans out to (see backend app/services/demo_bot_service.py) -- not a real business.
  is_demo: boolean;
  // Admin-set safety cap for the Broadcast Module -- not a live query against Meta's
  // real messaging tier. See /broadcasts.
  broadcast_daily_cap: number;
  // Feature Package entitlements (see /feature-packages). null means unrestricted --
  // every gated feature is available. Only a restaurant explicitly assigned a package
  // (at creation or via reassignment) ever has a real (possibly empty) list here. See
  // lib/restaurant.tsx's hasFeature() helper, the single place this should be read from.
  feature_package_id: string | null;
  enabled_features: string[] | null;
  whatsapp_phone_number_id: string | null;
  whatsapp_business_account_id: string | null;
  payment_methods: string[];
  default_payment_method: string;
  razorpay_key_id: string | null;
  loyalty_settings: {
    points_per_currency_unit?: number;
    redemption_value_per_point?: number;
  };
  // Only populated by GET /restaurants (the super-admin list) -- see
  // backend RestaurantListItem. Absent on a single-restaurant fetch.
  total_orders?: number;
  last_order_at?: string | null;
}

export interface RestaurantCreateResult extends Restaurant {
  owner_email: string;
  setup_url: string;
}

// Universal Image Processing Pipeline (see backend app/models/image.py). One uploaded
// original + every generated derivative; `urls` is populated by the API (presigned
// storage URLs), never stored directly.
export interface ImageVariant {
  key: string;
  format: string;
  width: number;
  height: number;
  size_bytes: number;
}

export interface ImageRecord {
  id: string;
  restaurant_id: string;
  image_type: string;
  catalog_item_id: string | null;
  original_width: number;
  original_height: number;
  original_size_bytes: number;
  status: "processing" | "ready" | "failed";
  failure_reason: string | null;
  crop_box: { x: number; y: number; width: number; height: number } | null;
  resolution_warning: boolean;
  low_quality_reason: string | null;
  replaced_by_image_id: string | null;
  variants: Record<string, ImageVariant>;
  created_at: string;
  updated_at: string;
  urls: Record<string, string>;
}

// GET/POST/PATCH /image-type-profiles -- the Super-Admin-editable "add a new image type
// or change a size profile without a deploy" registry.
export interface ImageVariantSpec {
  variant_name: string;
  target_context: "whatsapp" | "thumbnail" | "banner" | "gallery" | "website";
  width: number;
  height: number;
  crop_mode: "cover" | "contain";
  format: string;
}

export interface ImageTypeProfile {
  id: string;
  code: string;
  label: string;
  variant_specs: ImageVariantSpec[];
  max_upload_size_bytes: number;
  is_customized: boolean;
  created_at: string;
  updated_at: string;
}

// GET /niche-templates -- populates the "Add Business" niche picker. Selecting one and
// creating a restaurant with `niche_code` set auto-provisions that niche's default
// catalog + conversation flow on the new generic multi-niche engine (see backend
// app/services/niche_provisioning.py); leaving it unset creates a business on the
// original restaurant-only flow, unchanged.
export interface NicheTemplateSummary {
  id: string;
  code: string;
  name: string;
  action_type: "order" | "inquiry" | "appointment" | "booking";
  icon: string;
}

// GET/POST/PATCH /niche-templates/{id} -- full detail, Super-Admin CRUD. `welcome_buttons`
// is deliberately NOT included here -- confirmed dead at runtime (only
// default_flow_steps[entry_step_id].static_options actually drives a provisioned
// business's buttons); see /home-builder for editing a business's own live buttons.
export interface NicheTemplateFull {
  id: string;
  code: string;
  name: string;
  action_type: "order" | "inquiry" | "appointment" | "booking";
  icon: string | null;
  welcome_message: string;
  welcome_banner_image: string | null;
  default_catalog: Record<string, unknown>[];
  default_flow_steps: FlowStep[];
  default_ui_layout: Record<string, { x: number; y: number }>;
  terminology: Record<string, unknown>;
  default_modules: Record<string, unknown>;
  is_customized: boolean;
  created_at: string;
  updated_at: string;
}

// GET /restaurants/{id}/flow -- read-only, powers the Home Builder's destination picker.
export interface FlowDefinitionSummary {
  id: string;
  restaurant_id: string;
  niche_code: string;
  action_type: "order" | "inquiry" | "appointment" | "booking";
  entry_step_id: string;
  steps: { step_id: string; type: string; [key: string]: unknown }[];
}

// Every FlowStepType the generic engine understands (backend app/models/enums.py). The 5
// auto-advancing types (condition/delay/api_call/human_handoff/ai_response) were added in
// Phase 2 Item 3 -- see app/services/generic_flow_engine.py's module docstring for how
// "buttons"/"list"/"payment" builder-UI concepts map onto menu_select/confirm_action
// instead of getting their own step types.
export type FlowStepType =
  | "message"
  | "menu_select"
  | "quantity_input"
  | "free_text_input"
  | "confirm_action"
  | "condition"
  | "delay"
  | "api_call"
  | "human_handoff"
  | "ai_response";

export type FlowStep = { step_id: string; type: FlowStepType; [key: string]: unknown };

// GET/PUT /restaurants/{id}/flow/steps -- full step-graph read/replace, the Drag & Drop
// Flow Builder's save action (distinct from /flow/home-buttons, which only ever touches
// the entry step's button list).
export interface FlowDefinitionFull {
  id: string;
  restaurant_id: string;
  niche_code: string;
  action_type: "order" | "inquiry" | "appointment" | "booking";
  entry_step_id: string;
  steps: FlowStep[];
  ui_layout: Record<string, { x: number; y: number }>;
}

// GET/POST/PATCH/DELETE /api-endpoints -- Super-Admin-curated allowlist an API_CALL step
// may reference. A flow author picks endpoint_id from this list; they never type a raw URL.
export interface ApiEndpoint {
  id: string;
  name: string;
  url: string;
  method: string;
  allowed_headers: Record<string, string>;
  capturable_context_keys: string[];
  timeout_seconds: number;
  response_size_cap_bytes: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// GET/POST/PATCH/DELETE /feature-packages -- Super-Admin-curated bundles of feature codes
// (see GET /feature-packages/registry for the fixed catalog they're drawn from).
// Assigning one to a restaurant SNAPSHOT-COPIES feature_codes into
// Restaurant.enabled_features -- editing a package afterward never retroactively changes a
// restaurant already assigned to it.
export interface FeaturePackage {
  id: string;
  name: string;
  description: string | null;
  feature_codes: string[];
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

// GET/PATCH /restaurants/{id}/flow/home-buttons -- the generic engine's home-screen
// buttons, in the same title/icon/order/visible/destination shape as the legacy engine's
// BotButton, so /home-builder can present one UI over either.
export interface HomeButton {
  id: string;
  title: string;
  icon: string | null;
  visible: boolean;
  destination_step_id: string;
}

// GET /restaurants/demo-bot-status -- read-only, powers the /niches page's Demo Bot panel.
export interface DemoBotNicheStatus {
  code: string;
  name: string;
  has_demo_restaurant: boolean;
}

export interface DemoBotStatus {
  sentinel_configured: boolean;
  niches: DemoBotNicheStatus[];
}

export interface AuditLogEntry {
  id: string;
  actor_id: string | null;
  action: string;
  entity: string;
  entity_id: string | null;
  diff: Record<string, unknown>;
  created_at: string;
}

export interface Branch {
  id: string;
  restaurant_id: string;
  name: string;
  address: string | null;
  phone: string | null;
  latitude: number | null;
  longitude: number | null;
  status: "open" | "closed" | "temporarily_unavailable";
  estimated_delivery_time_minutes: number | null;
  manager_name: string | null;
}

export interface Category {
  id: string;
  restaurant_id: string;
  name: string;
  display_order: number;
  visible: boolean;
}

export interface Product {
  id: string;
  restaurant_id: string;
  category_id: string;
  name: string;
  description: string | null;
  price: number;
  discount_price: number | null;
  gst_percent: number;
  is_veg: boolean;
  available: boolean;
  is_featured: boolean;
  tags: string[];
}

export interface BotMessage {
  id: string;
  restaurant_id: string;
  key: string;
  content: string;
}

export interface BotButton {
  id: string;
  restaurant_id: string;
  title: string;
  emoji: string | null;
  action: string;
  next_flow: string | null;
  visible: boolean;
  display_order: number;
}

export interface OrderItem {
  id: string;
  product_id: string;
  name_snapshot: string;
  price_snapshot: number;
  quantity: number;
}

export interface OrderDeliveryAddress {
  address?: string;
  latitude?: number;
  longitude?: number;
}

export interface Order {
  id: string;
  restaurant_id: string;
  branch_id: string;
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  coupon_id: string | null;
  order_number: string;
  status: "pending" | "accepted" | "preparing" | "ready" | "completed" | "cancelled" | "refunded";
  payment_status: string;
  payment_method: string;
  fulfillment_type: "delivery" | "pickup";
  delivery_address: OrderDeliveryAddress;
  notes: string | null;
  subtotal: number;
  tax: number;
  delivery_charge: number;
  discount: number;
  total: number;
  invoice_number: string | null;
  invoice_url: string | null;
  items: OrderItem[];
  created_at: string;
}

export interface DashboardStats {
  total_orders: number;
  revenue: number;
  pending_orders: number;
  cancelled_orders: number;
  completed_orders: number;
  average_order_value: number;
  most_ordered_item: string | null;
  total_customers: number;
}

export interface Coupon {
  id: string;
  restaurant_id: string;
  code: string;
  type: "flat" | "percentage";
  value: number;
  min_order_amount: number;
  max_discount_amount: number | null;
  starts_at: string | null;
  expires_at: string | null;
  usage_limit: number | null;
  usage_limit_per_customer: number | null;
  first_order_only: boolean;
  auto_apply: boolean;
  is_active: boolean;
}

// GET/POST/PATCH /restaurants/{id}/whatsapp-templates -- Meta Message Templates, needed
// to message a customer outside the 24-hour customer-service window. `status` mirrors
// Meta's own vocabulary; DRAFT is local-only. Editable only while draft or rejected.
export interface WhatsAppTemplate {
  id: string;
  restaurant_id: string;
  name: string;
  category: "marketing" | "utility" | "authentication";
  language: string;
  body_text: string;
  variable_examples: string[];
  meta_template_id: string | null;
  status: "draft" | "pending" | "approved" | "rejected" | "disabled";
  rejection_reason: string | null;
  submitted_at: string | null;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

// GET/POST/PATCH /restaurants/{id}/broadcasts -- bulk WhatsApp campaigns to a customer
// segment, using an APPROVED WhatsAppTemplate. Recipients only exist once a campaign has
// actually started (see /{id}/start) -- editing segment_tags on a DRAFT never touches them.
export interface BroadcastCampaign {
  id: string;
  restaurant_id: string;
  template_id: string;
  name: string;
  segment_tags: string[];
  variable_template: string[];
  status: "draft" | "scheduled" | "sending" | "completed" | "failed" | "cancelled";
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  total_recipients: number;
  sent_count: number;
  failed_count: number;
  failure_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface BroadcastRecipient {
  id: string;
  campaign_id: string;
  customer_id: string;
  status: "pending" | "sent" | "failed" | "skipped";
  error_reason: string | null;
  sent_at: string | null;
}

export interface SegmentPreview {
  matching_customers: number;
}

export interface FaqEntry {
  id: string;
  restaurant_id: string;
  trigger_keywords: string[];
  answer: string;
  display_order: number;
  is_active: boolean;
}

export interface Customer {
  id: string;
  restaurant_id: string;
  phone: string;
  name: string | null;
  email: string | null;
  tags: string[];
  is_blocked: boolean;
  marketing_opt_in: boolean;
  loyalty_points: number;
}

export interface ConversationSummary {
  customer_id: string;
  customer_name: string | null;
  customer_phone: string;
  last_message_at: string | null;
  last_message_preview: string | null;
}

export interface Message {
  id: string;
  customer_id: string;
  direction: "inbound" | "outbound";
  sent_by: "customer" | "bot" | "staff";
  staff_user_id: string | null;
  body: string;
  created_at: string;
}

export interface DisplayDevice {
  id: string;
  name: string;
  branch_id: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface DisplayDeviceCreateResult {
  id: string;
  name: string;
  token: string;
}

export interface PosOrderItem {
  name_snapshot: string;
  quantity: number;
}

export interface PosOrder {
  id: string;
  order_number: string;
  status: "pending" | "accepted" | "preparing" | "ready" | "completed" | "cancelled" | "refunded";
  fulfillment_type: "delivery" | "pickup";
  items: PosOrderItem[];
  created_at: string;
  total: number;
}
