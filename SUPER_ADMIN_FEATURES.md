# Super Admin Feature Catalog & Package System

Source: analysis of `kelviontech-whatsapp-features.html` (the 72-toggle mockup) cross-checked
against the actual codebase (`backend/app`, `frontend/app`) as of 2026-08-11, plus additions
proposed below. This file has two parts:

- **Part A** — the Feature Package system: a proposed (not yet built) mechanism for Super
  Admin to bundle features into packages and allocate a package to a business at creation
  time, so "which features does this business get" becomes admin-panel-driven instead of a
  flat on/off switch per feature per business.
- **Part B** — the full feature catalog: every feature from the HTML mockup, deduplicated,
  plus new features proposed below, each tagged with real implementation status.

**Status tags used throughout:**
| Tag | Meaning |
|---|---|
| ✅ LIVE | Built, tested, working today for every generic-engine niche |
| 🟡 PARTIAL | Some of the described behavior exists; specifics below |
| ❌ PLANNED | Not built. Some are on the confirmed Phase 2/3 roadmap; others are just catalog entries |
| 🆕 PROPOSED | Not in the original HTML — suggested here as an addition |

---

## Part A: The Feature Package System (proposed design — not yet built)

### The problem today

Every feature below either (a) just exists for every business unconditionally (e.g. Coupons,
FAQ), or (b) is a per-business on/off toggle buried inside that business's own config (e.g.
`Restaurant.loyalty_settings["modules"]`, checked by `skip_if_module_off` in
`generic_flow_engine.py`). There is **no Super-Admin-level concept of "which features does
this customer's plan include"** — no packages, no tiers, nothing gating which admin
pages/APIs a business can reach. A business on the cheapest plan and a business on the most
expensive plan currently see the exact same dashboard.

### Proposed model

```
FeaturePackage (Super-Admin-curated, mirrors NicheTemplate/ApiEndpoint's
                "curate once, businesses consume" pattern)
  id, name, description
  feature_codes: list[str]         # subset of the fixed FEATURE_REGISTRY below
  is_default: bool                 # what a new business gets if no package is picked
  created_at, updated_at

Restaurant.feature_package_id: UUID | null    (FK -> FeaturePackage)
Restaurant.feature_overrides: dict[str, bool] # optional per-business exceptions on top of
                                               # the package (e.g. "give this one client
                                               # early access to X without a new package")
```

**Why a fixed `FEATURE_REGISTRY` in code, not a DB table of arbitrary strings:** every entry
in the catalog below corresponds to real functionality that had to be built — a feature
can't be "activated" by typing a new string into a form the way a niche or a menu item can.
The registry is a backend constant (`app/core/feature_registry.py`, one dict per feature:
code, label, category, description, default-on-for-new-package). This matches this
project's own "never hardcode anything" rule correctly: **niches, menus, flows, languages,
gateways, templates, and widgets are data** (Super Admin authors them with no code change) —
**but the catalog of features the codebase actually implements is not data**, it's an
inventory of what exists. What *is* data, fully admin-panel-driven with no code change, is
the packages themselves (which features go in "Starter" vs "Growth" vs "Enterprise") and
which package each business is on.

### How gating would work

1. A shared `has_feature(restaurant, code) -> bool` helper: `code in restaurant's resolved
   feature set` (package's `feature_codes`, with `feature_overrides` applied on top).
2. **Backend**: routers for a gated feature call `require_feature(code)` (same shape as the
   existing `require_roles(...)` dependency) — a business without the feature gets a 403 with
   a clear "not included in your plan" message, not a 404 or a silent no-op.
3. **Frontend**: nav items and page bodies check the current restaurant's resolved feature
   set (returned on `GET /restaurants/{id}` or a dedicated `GET /restaurants/{id}/features`)
   and hide/soft-disable ungated UI, same pattern `uses_generic_engine` already uses to branch
   `/home-builder` and `/live-chat`.
4. **At restaurant creation**: the existing `/restaurants` "Add Restaurant" form gets a
   "Package" dropdown (defaults to the package flagged `is_default`). Changing a business's
   package later is a normal PATCH from a new `/restaurants/{id}` package selector — same
   surface Super Admin already uses for `status`/`niche_type`.
5. New `/feature-packages` Super-Admin page (same CRUD shape as `/api-endpoints`): create a
   package, check which features it includes from the registry (grouped by category, same
   layout as the original HTML mockup you sent), save.

### Open decisions before this gets built

These are genuinely your call, not something to guess at:

1. **Snapshot vs. live reference** — if Super Admin edits a package after businesses are
   already on it, do those businesses' available features change immediately, or only for
   newly-created businesses (existing ones keep whatever the package looked like at
   assignment time, like `NicheTemplate` → `FlowDefinition` provisioning already does)?
2. **What happens to a business's data when a feature is removed from its package** — e.g. a
   business had Broadcasts enabled, gets downgraded, loses the feature. Do existing broadcast
   campaigns/coupons/etc. stay untouched but new-creation is blocked (soft gate), or does
   existing functionality actually stop working (hard gate)? Soft gate is safer and is what
   `is_customized`-style patterns elsewhere in this codebase favor.
3. **Granularity** — gate at the level of the ~57 catalog entries below (fine-grained), or a
   smaller set of ~15 "modules" (Ordering, Broadcasts, Loyalty, Flow Builder, Live Chat, AI,
   etc.) that map many catalog rows to one gate? Fine-grained gives more pricing flexibility;
   coarse is far less code (one `require_feature` per router file, not per endpoint) and
   maps better to how the packages will actually be sold.

**Recommendation**: snapshot-copy (matches existing provisioning pattern), soft gate
(matches existing safety bias in this codebase), coarse-grained modules for v1 (ordering
speed over completeness — fine-grained entries can be added later without a schema change,
since `feature_codes` is just a list). Say the word and this gets the same
research → design → review → build cycle as every other item this project has gone through.

---

## Part B: Full Feature Catalog

### Platform / Super Admin Infrastructure
*(not in the original HTML — the underlying admin surface everything else depends on)*

| Feature | Status | Notes |
|---|---|---|
| Multi-niche template management (`/niches`) | ✅ LIVE | 12 niches seeded: hotel, real_estate, restaurant, salon, automobile, clinic, education, electronics, grocery, gym, jewellers, retail |
| Visual Flow Builder (drag & drop) | ✅ LIVE | Just shipped — React Flow editor, condition/delay/API-call/human-handoff/AI-placeholder steps |
| Image Type Profile management | ✅ LIVE | Admin-configurable image variant specs, no deploy needed |
| API Endpoint allowlist (for Flow Builder API-call steps) | ✅ LIVE | SSRF-protected at connect layer |
| Multi-branch support | ✅ LIVE | |
| POS / Kitchen Display Devices | ✅ LIVE | |
| Role-based access (Owner/Manager/Cashier/Kitchen/Super Admin) | ✅ LIVE | |
| Audit log | ✅ LIVE | |
| Demo Bot (one number, all niches) | 🟡 PARTIAL | Fully built and tested in code; **not live on a real number yet** — see Implementation Status doc |
| Restaurant status management (active/suspended/onboarding/cancelled) | ✅ LIVE | |
| Feature Package system | ❌ PLANNED | See Part A above |
| Billing / subscription management | ❌ PLANNED | Confirmed on the Phase 3 roadmap (Razorpay, platform-level credentials) |
| White-label branding per tenant | ❌ PLANNED | Confirmed on the Phase 3 roadmap |
| Marketplace (cross-niche discovery) | ❌ PLANNED | Confirmed on the Phase 3 roadmap |
| AI Knowledge Base | ❌ PLANNED | Confirmed on the Phase 3 roadmap — `AI_RESPONSE` flow step already exists as a placeholder waiting for this |
| 🆕 Feature usage analytics (which businesses use which features) | 🆕 PROPOSED | Natural pairing with the Package system — Super Admin sees adoption, not just toggle state |
| 🆕 WhatsApp connection health monitor | 🆕 PROPOSED | Per-business token-expiry / webhook-failure alerts on the Super Admin dashboard — today a dead token just silently fails sends |

### Customer Ordering Flow

| Feature | Status | Notes |
|---|---|---|
| Interactive Menu (List & Button Messages) | ✅ LIVE | `menu_select` step, categories/items sourcing |
| Cart Management in Chat | ✅ LIVE | Core add/remove/quantity/confirm; 24h cart expiry specifically not implemented |
| Address Collection | 🟡 PARTIAL | Location/free-text capture works; distance-based delivery zones, radius validation, "out of zone → nearest branch" not built (`delivery_charge` is a flat per-restaurant value today) |
| In-Chat Payment (Razorpay Link) | ✅ LIVE | |
| "Reorder My Usual" One-Tap | ❌ PLANNED | |
| Voice Order Support (AI Transcription) | ❌ PLANNED | Depends on AI Knowledge Base |
| QR Code Table Ordering | ❌ PLANNED | |
| Group Ordering — Shared Cart | ❌ PLANNED | |
| Pre-Order / Scheduled Delivery | ❌ PLANNED | |
| AI Chatbot Order Taking | 🟡 PARTIAL | Rule-based flow engine handles full ordering today; true NLU/LLM understanding is the AI Knowledge Base item |

### Marketing & Broadcasts

| Feature | Status | Notes |
|---|---|---|
| Customer List Management | ✅ LIVE | Tags, segments |
| Bulk Broadcast to Customer List | ✅ LIVE | |
| Rich Media Broadcasts | 🟡 PARTIAL | Text/template broadcasts work; carousel/list-message broadcast types not built |
| Scheduled Broadcasts | 🟡 PARTIAL | One-time `scheduled_at` works; recurring/festival-auto-broadcast not built |
| Broadcast Analytics Dashboard | 🟡 PARTIAL | Sent/failed counts exist; CTR/conversion/revenue attribution not built |
| Smart Segment Targeting | 🟡 PARTIAL | Tag-based segments work; behavioral segments ("ordered X in last 30 days") not built |
| Opt-Out & Compliance Management | 🟡 PARTIAL | `marketing_opt_in` is respected when *sending*; **inbound "STOP" is not auto-detected anywhere in the webhook** — this is a real, worth-fixing gap, not just an unbuilt nice-to-have |
| Drip Campaigns / Auto-Sequences | ❌ PLANNED | |
| QR Code Generator | ❌ PLANNED | |
| Click-to-WhatsApp Ads Manager | ❌ PLANNED | |
| Subscription Meal Plans (Tiffin/Dabba) | ❌ PLANNED | |
| 🆕 Abandoned-cart WhatsApp reminder | 🆕 PROPOSED | Cart started, no order N minutes later → one automated nudge |

### Order Status & Notifications

| Feature | Status | Notes |
|---|---|---|
| Template Message Auto-Send (status transitions) | ✅ LIVE | |
| Live Delivery Tracking Link | ❌ PLANNED | No rider/live-location system exists |
| Review Request (2h after delivery) | ❌ PLANNED | No scheduled post-delivery job |
| FAQ Auto-Responder | ✅ LIVE | |

### Loyalty, Coupons & Engagement

| Feature | Status | Notes |
|---|---|---|
| Coupon & Discount Engine | ✅ LIVE | Flat/%, usage limits, min order, expiry |
| Loyalty Points | 🟡 PARTIAL | Points accrue and are stored; in-chat "REDEEM" command exists only in the legacy engine, not the generic multi-niche engine |
| Coupon Distribution in Chat | 🟡 PARTIAL | Coupons exist; auto-distributing unique per-customer codes via broadcast not built |
| Birthday & Anniversary Campaigns | ❌ PLANNED | No date-of-birth field to trigger from |
| Family Accounts | ❌ PLANNED | |
| Customer Referral Program | ❌ PLANNED | |

### WhatsApp Templates & Meta Integration

| Feature | Status | Notes |
|---|---|---|
| Template Message Library | ✅ LIVE | |
| Message Customization | ✅ LIVE | |
| Message History | ✅ LIVE | |
| WABA & Phone Number Management | 🟡 PARTIAL | Credentials stored/used; quality-rating and messaging-tier tracking not built |
| Meta Conversation Pricing Tracker | ❌ PLANNED | |
| Message Quality & Compliance Monitor | ❌ PLANNED | |
| Quick Reply Templates (staff shortcuts) | ❌ PLANNED | Live Chat is free-text only today |

### AI Chat Agent & Automation

| Feature | Status | Notes |
|---|---|---|
| Visual Chatbot Flow Builder | ✅ LIVE | Just shipped |
| FAQ Auto-Responder | ✅ LIVE | |
| AI Order-Taking Bot | 🟡 PARTIAL | Rule-based only, see above |
| Smart Upsell Recommendations | ❌ PLANNED | |
| AI Performance Analytics | ❌ PLANNED | |
| Image-Based Menu Discovery | ❌ PLANNED | |
| Auto-Language Detection & Response | ❌ PLANNED | Multi-language is a confirmed Phase 3 roadmap item, not started |

### Advanced Customer Experience

All ❌ PLANNED, none started: Smart Wait Time Estimator, Post-Meal Feedback Loop with
Kitchen, Weather-Based Menu Suggestions, Geo-Fenced Offers, Digital Gift Cards, Corporate
Account & Monthly Billing.

### Delivery & Logistics

| Feature | Status | Notes |
|---|---|---|
| Dynamic Delivery Charge Calculator | 🟡 PARTIAL | Flat fee only; distance/rain/peak-hour rules not built |
| Multi-Stop Route Optimization | ❌ PLANNED | |
| Dark Kitchen / Cloud Kitchen Support | ❌ PLANNED | |
| Third-Party Delivery Integration | ❌ PLANNED | |
| Packaging & Eco-Friendly Options | ❌ PLANNED | |

### 🆕 Additional proposed features (not in the original list)

| Feature | Why it's worth adding |
|---|---|
| WhatsApp Catalog / Meta Commerce sync | Native Product Messages instead of custom list messages — better UX, Meta-native |
| Multi-agent Live Chat (assign conversations to staff, internal notes) | Today's Live Chat has no ownership/routing once more than one staff member is on shift |
| SLA alerting for handed-off conversations | "No staff reply in 10 minutes" alert — directly complements the Human Handoff step just shipped |
| GST invoice as a WhatsApp document message | Exists as a PDF already (per GOING_LIVE.md); not yet sent as a WA document attachment |
| Customer self-service "my orders" / "track order" command | Cheap to build on the existing Order model, high perceived value |
| WhatsApp Business Profile sync (hours/address/about) | Push Restaurant settings to Meta instead of managing them twice |
| Data export & right-to-erasure self-service | `customers.py` already has an anonymize endpoint — surfacing it as a proper DPDP/GDPR-style workflow is a small lift with real compliance value for an India-market SaaS |
