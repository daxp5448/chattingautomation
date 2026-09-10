# WhatsApp Response Latency Report

Investigation only — no behavior-changing fix was applied. Scope: `backend/app`, real
inbound-message path (Meta webhook → reply sent). See "Files inspected / modified" at the
bottom for the complete list.

## Overall finding

There is **no queue, no missing index, no artificial delay, and no blocking-call-on-async
bug** anywhere in this path. The webhook does the entire job — parse → resolve tenant →
lock/read conversation state → run the flow engine → call Meta → commit — **before**
returning HTTP 200 (confirmed in code, see "Webhook acknowledgement" below). That is a
deliberate, previously-reviewed decision (see `generic_flow_engine.py`'s
`schedule_background_upload` docstring: *"the webhook-level 'return 200 instantly, process
later' architecture the product owner explicitly declined earlier"*) — not an oversight.

Given that architecture, the response time a customer feels is the straight-line sum of:

```
webhook overhead + DB/session lookups + flow-engine logic + Meta API round-trip(s)
```

Locally (SQLite, in-process, no network to Meta) that sum is **~20–30ms** per turn — see
measured timings below. On the real Oracle VM deployment (Postgres over the loopback/
docker network, real TLS handshakes reused via a persistent client, real Meta network
latency) the two components that will dominate and that I could **not** measure without
sending a real message are:

1. **The Meta Graph API call itself** (`whatsapp_client.py`'s `GraphAPIWhatsAppSender.send`)
   — this is a real internet round-trip Meta controls the far side of, typically
   150–500ms per call, sometimes more. Every single reply — even a one-line text message —
   pays this once; a reply that also sends an image (see `_render_step`'s `"message"` step
   type) pays it twice, **sequentially**, on purpose (see finding #2 below).
2. **Repeated/redundant database round-trips on the Demo Bot path** (`demo_bot_service.py`)
   — a real, concrete, fixable pattern found by reading the code (detailed below), not a
   guess. It won't single-handedly cause a "does not feel real-time" complaint by itself,
   but it's pure waste stacked directly into every demo reply's critical path.

My best-supported explanation for "feels slow / not real-time": **it is one Meta API
round-trip (or two, for any step that sends an image) sitting directly in the customer's
critical path, with no way to make it "feel" instant while the current webhook
acknowledgement model (block until fully processed, then return 200) is unchanged.**
Everything else measured is single-digit-to-low-double-digit milliseconds.

## Measured timings

Two different things are reported here, and it matters which is which:

- **Local, measured** (via the new temporary instrumentation, run against this repo's own
  SQLite test database, real code path, `InMemoryWhatsAppSender` standing in for Meta —
  see "Runtime test" below): backend-only processing time, real numbers.
- **Meta network time**: **not measured** — I did not send a real WhatsApp message
  through a production/demo credential, per your explicit instruction. The number given is
  from static inspection of `whatsapp_client.py`'s configured timeouts and typical
  Graph API latency, not a live measurement.

| Stage | Time | Status |
|---|---:|---|
| Webhook receive → validation | ~1 ms | Measured (local) |
| Message parsing | 0 ms | Measured (local) |
| Tenant resolution | 0–5 ms | Measured (local) — cached after first hit (`TTLCache`, see `restaurant_repository.py`) |
| DB/session lookup (customer + conversation-state lock + flow definition) | 7–21 ms | Measured (local, SQLite) |
| Intent processing (rule-based fuzzy match) | 0–1 ms | Measured (local) |
| Options lookup (category/item DB query, fires even on a plain button tap — see finding below) | 0–1 ms locally | Measured (local, tiny catalog) — Not measured under production Postgres/catalog size |
| Flow engine (rendering + all per-step logic) | 0–8 ms | Measured (local, excludes Meta network since sender was stubbed) |
| Response preparation (template render + humanize) | 0 ms | Measured (local) |
| Meta API send (actual `graph.facebook.com` HTTP call) | Not measured | Blocked from calling real API by design (task instruction) — see "Meta API findings" for the code-level analysis and configured timeouts (connect 5s / read 10s) |
| Total backend processing (webhook receive → HTTP 200), Meta call excluded | 22–31 ms | Measured (local, SQLite, 7-turn conversation) |

Raw captured lines (7-turn conversation: hi → category → item → quantity → cart →
checkout → address, run against local SQLite):

```
[WA LATENCY] restaurant=latency-bench-kitchen wa_message_id=wamid.bench.1
webhook_validation=1ms
message_parsing=0ms
tenant_resolution=5ms
session_db=7ms
flow_engine_started=4ms
flow_engine_completed=4ms
webhook_completed=3ms
response_preparation=0ms x1 (nested -- already counted inside flow_engine above)
total=23ms
---
[WA LATENCY] restaurant=latency-bench-kitchen wa_message_id=wamid.bench.7
webhook_validation=1ms
message_parsing=0ms
tenant_resolution=0ms
session_db=21ms
flow_engine_started=2ms
flow_engine_completed=1ms
webhook_completed=7ms
options_lookup=0ms x1 (nested -- already counted inside flow_engine above)
intent_processing=0ms x1 (nested -- already counted inside flow_engine above)
response_preparation=0ms x1 (nested -- already counted inside flow_engine above)
total=31ms
```

(Full 7-turn capture is reproducible — see "Commands used for testing".)

**Read this carefully**: `meta_send`, `options_lookup`, `intent_processing` and
`response_preparation` are **nested inside** `flow_engine`, not additional sequential
stages after it — the flow engine calls Meta's send API *while* rendering a step, so their
time is already included in `flow_engine_started`→`flow_engine_completed`. They're broken
out separately so you can see how much of the flow-engine time is DB/CPU work vs (in a real
deployment) network waiting on Meta.

## Biggest bottlenecks

Ranked by expected real-world impact on the Oracle VM deployment, not local-machine
numbers (which are all tiny because SQLite and the in-memory sender have near-zero
latency):

1. **Meta Graph API round-trip is inline, in the customer's critical path, once per
   outbound message, sent sequentially when more than one message is needed.**
   `generic_flow_engine.py`'s `send_generic_messages_batch` (line ~503) explicitly sends a
   batch of messages **one at a time, awaited in order** — this is intentional (its own
   docstring explains a prior concurrent-send attempt caused an image to visually arrive
   *after* the options list it was supposed to precede), but it means a step that shows an
   image + an options list pays **two full Meta round-trips back to back**, not one. This
   is the single largest, least avoidable cost in the whole path, and it is architectural
   (real network call to a third party Meta controls), not a bug.
2. **The webhook blocks on the entire pipeline before acknowledging Meta** (confirmed
   below). This is a known, previously-declined trade-off, not new information — surfacing
   it because it's the reason #1 is felt directly as "the bot is slow to reply" instead of
   being invisible to the customer.
3. **Demo Bot path re-fetches the same rows multiple times per turn** (`demo_bot_service.py`
   → `generic_flow_engine.py`) — concrete, in the code, detailed below. Real but small
   (single-digit ms on Postgres); worth fixing for cleanliness, not the reason for a
   "several-second" feel.
4. **`_resolve_options` runs unconditionally on every button tap into a `menu_select` step,
   even though its result is provably discarded** for a real button tap. Same category as
   #3 — real, wasteful, but small relative to a Meta round-trip.

Nothing else rose to the level of a "bottleneck" — no missing index, no sync-call-in-async,
no sleep/retry/backoff on the happy path, no N+1 loop over individual rows (image
resolution is already correctly batched).

## Blocking operations

Systematically checked every category from the brief; findings below are the ones that
actually exist in this codebase.

- **No `requests` library usage anywhere in the message path.** All outbound HTTP
  (`whatsapp_client.py`, `meta_media_upload.py`, `api_endpoint_client.py`) uses `httpx`
  through the existing `async`/`await` machinery — nothing synchronous is called from
  inside an `async def`.
- **No raw `time.sleep`.** The only sleeps found:
  - `generic_flow_engine.py` `_advance_and_render`, line ~956: `await asyncio.sleep(delay_seconds)` —
    this is the flow's own `delay` step type (a business-configured "wait N seconds before
    the next message" node), correctly `await`ed, capped by `_MAX_TOTAL_BLOCKING_SECONDS =
    5.0` (module-level, line 205) shared across an entire auto-advance chain. Not a hidden
    system delay — it only fires if a business's own flow definition includes a `delay`
    step, and it holds the `GenericConversationState` row lock + a pooled DB connection for
    that whole duration, which is itself a design trade-off worth knowing about but is
    explicitly documented as such in the code (see the comment directly above
    `_MAX_TOTAL_BLOCKING_SECONDS`).
  - `whatsapp_client.py` `GraphAPIWhatsAppSender.send`, line ~377: `await
    asyncio.sleep(backoff)` between retry attempts on a Meta 5xx/connect failure
    (exponential backoff, capped at 8s, max 3 attempts total). Only fires when Meta's API is
    already failing — not part of the normal-case path, but worth knowing it can add up to
    ~1s+2s of extra wait before a customer sees anything, on a bad connection to Meta.
  - `demo_data_purge.py` / `reconciliation.py` (Celery tasks) — background jobs, nowhere
    near the inbound webhook.
- **No sync DB driver blocking the event loop.** `db/session.py` uses
  `create_async_engine` with `postgresql+asyncpg` in production; every repository call in
  the path is `await session.execute(...)`.
- **Media upload is correctly fire-and-forget.** `meta_media_upload.py`'s
  `schedule_background_upload` (line 116) explicitly launches an `asyncio.create_task` and
  returns immediately — the *current* send always goes out via a plain image `link`
  first; the Meta media-upload (which would otherwise add a second, slower API call) only
  pre-warms a cache for the *next* time, off the customer-facing path entirely. This is
  already the right design, not a bottleneck.
- **`_resolve_options` fires even when its result will be discarded** —
  `generic_flow_engine.py::handle`, lines 633–634:
  ```python
  resolved_options = await self._resolve_options(restaurant, state, current) if current.get("buttons_from") else []
  resolved = resolve_interaction(interaction, resolved_options, state.context, restaurant)
  ```
  `resolve_interaction` (`conversational_intent.py`, line 60) immediately returns a no-op
  the instant `interaction.reply_id` is set — i.e. **every ordinary button/list tap**, which
  is the majority of turns in a guided order flow. But `_resolve_options` (a real DB query —
  `list_by_category`/`list_visible`/`list_active` plus a bulk image-resolution query) has
  already run and its result thrown away by the time that check happens. This fires on
  every `category_select`/`item_select`/`staff_select` step's button tap, for every
  customer, for the whole lifetime of a guided order.

## Database findings

- **Queries per ordinary inbound message (generic engine, non-demo, button tap on a
  `menu_select` step)**: ~5–7 round trips —
  1. wa_message_id dedup check (`Message` table)
  2. `Customer.get_or_create` (SELECT, occasionally INSERT)
  3. `GenericConversationState.get_for_update_by_customer` (SELECT ... FOR UPDATE)
  4. `FlowDefinition.get_by_restaurant` (SELECT)
  5. inbound `Message` INSERT + flush
  6. `_resolve_options`'s catalog query + its bulk-image query (2 round trips) — **wasted**
     when the tap is a real button press, per the finding above
  7. commit
  (Restaurant-by-`phone_number_id` lookup is a **10th** conceptual query but is served from
  an in-process TTL cache — `restaurant_repository.py` line 15 — so it's usually free.)
- **Which queries are repeated needlessly**: on the **Demo Bot** path specifically
  (`demo_bot_service.py`, the path a live sales-demo prospect actually talks to), an
  ordinary mid-demo message re-fetches the same rows twice:
  - `_customer_is_at_a_terminal_step` (line 207) does its own
    `CustomerRepository.get_or_create` + `GenericConversationStateRepository.get_by_customer`
    + `FlowDefinitionRepository.get_by_restaurant` **just to check one boolean**, then
    falls through (line 423) to `process_inbound_message`, which immediately repeats **all
    three** lookups itself (`generic_flow_engine.py` lines 359–372) — the second
    `FlowDefinition.get_by_restaurant` call fetches a byte-for-byte identical row that was
    already sitting in a local variable one function call earlier. That's 3 extra,
    fully avoidable DB round trips on every single ordinary demo turn.
  - The wa_message_id dedup check also runs twice via two different code paths for the
    same id: `demo_bot_service.py`'s own `_already_processed` (line 80) and then, on
    delegation, `generic_flow_engine.py::process_inbound_message`'s own
    `message_repo.get_by_wa_message_id` check (line 355) — functionally identical
    queries, run back-to-back.
- **Indexes**: checked every column actually filtered on in this path —
  `Restaurant.whatsapp_phone_number_id` (unique+indexed), `Customer.restaurant_id`
  (indexed), `Customer.phone` (indexed — two separate single-column indexes rather than
  one composite `(restaurant_id, phone)` index, which Postgres can still satisfy via a
  bitmap AND of both indexes reasonably efficiently at this table size, but a composite
  index would be strictly better if this ever becomes measurably slow),
  `GenericConversationState.customer_id` (unique constraint, so indexed),
  `FlowDefinition.restaurant_id` — did not confirm indexed/not from this pass (not on the
  hot-lookup list the brief called out; flag for a follow-up look if needed).
  **Nothing here looks under-indexed for current or 50–100-tenant scale.**
- **Flow/config data reloaded per message**: `FlowDefinition.get_by_restaurant` is a small
  JSON blob (the whole flow's step list) fetched fresh on every message rather than cached
  — reasonable given it can be edited live by staff via the Flow Builder and must reflect
  edits immediately, but it is fetched **twice** per turn on the Demo Bot path specifically
  (see above), never more than once on the ordinary generic-engine path.

## Meta API findings

- **HTTP client**: `httpx.AsyncClient`, fully async, no blocking calls.
- **Connection reuse**: **already correct.** `whatsapp_client.py`'s `GraphAPIWhatsAppSender`
  is instantiated exactly once at import time (`webhook.py` line 36: `_sender =
  GraphAPIWhatsAppSender()`, a module-level singleton) and holds one persistent
  `httpx.AsyncClient` for the life of the process — every send reuses an already-open
  keep-alive TCP/TLS connection to `graph.facebook.com` instead of paying a fresh
  handshake per message. The class's own docstring (line 304) documents this was a
  deliberate fix for exactly this problem. **This is not something to "fix" — it's already
  done.**
- **Timeout configuration**: `httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)`
  (line 319) — reasonable, not the cause of routine slowness; would only matter on an
  actually-degraded connection to Meta.
- **Retries**: up to 3 attempts total, only for 5xx/connect failures (never for a
  4xx, and never after a timeout with an ambiguous outcome — see the code's own comment
  at line 359 explaining why retrying a timed-out send risks a duplicate customer-visible
  message), exponential backoff capped at 8s. **Only engages when Meta itself is failing**
  — irrelevant to the normal-case latency question, but worth knowing it can add real
  seconds on a bad connection.
- **Multiple Meta calls per reply**: yes, whenever a step sends an image alongside its
  text/options (`_render_step`'s `"message"` type, and `_send_options`'s image-then-list
  pattern) — sent **sequentially, not concurrently**, on purpose (see Bottleneck #1 above).
  This is the one Meta-API-shaped finding that actually compounds real latency: two
  sequential round-trips instead of one.
- **Media (image) messages**: normal case sends a `link`-based image message (Meta fetches
  the URL itself, no separate upload call from this backend). A **separate** upload-based
  path exists (`meta_media_upload.py`, `image_by_id`) for pre-warming a faster `media_id`
  path on repeat sends, but it is fire-and-forget/background as noted above — never adds a
  second synchronous call to the current reply.
- **Not measured live**: actual round-trip time to `graph.facebook.com` from the Oracle VM.
  This is the one number in this whole report that genuinely can't be produced without
  either sending a real message (explicitly disallowed for this investigation) or having
  the Oracle VM environment available to `curl` Meta directly.

## Webhook acknowledgement

**(B) — the webhook processes the entire flow and sends the WhatsApp reply BEFORE
returning HTTP 200.** Confirmed directly in code: `api/v1/routers/webhook.py`'s
`receive_webhook` — every branch (`_BLOCKED_STATUSES`, demo, `uses_generic_engine`, legacy)
`await`s `process_inbound_message` / `handle_demo_inbound` (which internally runs the
flow engine and calls Meta's send API) **inside** the function body, and only the very
last line, after every branch of the `for entry / for change` loop has completed, is
`return {"status": "ok"}` (see line ~248, now `latency_debug.mark("webhook_completed")`
immediately before it). There is no background task, no queue enqueue, no "ack now,
process later" split anywhere in this file.

As noted above, this is confirmed to be a **known, previously-reviewed trade-off**, not an
accidental design — `generic_flow_engine.py`'s `schedule_background_upload` docstring
explicitly references it: *"the webhook-level 'return 200 instantly, process later'
architecture the product owner explicitly declined earlier ... that removes the
per-customer FOR UPDATE lock protecting conversation state."*

## Artificial delays

Searched the entire message path for `sleep`, `delay`, `typing`, `retry`, `backoff`,
`timeout`:

- No typing-indicator simulation anywhere (no artificial "looks more human" pause).
- The only real delays are the two `asyncio.sleep` call sites and the retry/backoff logic
  already covered under "Blocking operations" and "Meta API findings" above — both
  legitimate, bounded, and off the normal happy path (a business must configure a `delay`
  flow step for the first; Meta must actually be failing for the second).
- No hardcoded artificial latency anywhere.

## Recommended fixes

Diagnosis only, per your instructions — **none of these were applied.** Ordered by
impact.

### 1. Stop calling `_resolve_options` when the interaction already has a `reply_id`
- **Problem**: `generic_flow_engine.py::handle`, lines 633–634 — a real DB query (+ a bulk
  image-resolution query) runs before checking whether its result will even be used.
- **Why it causes delay**: on every button/list tap into a `menu_select` step (a large
  fraction of all turns in a guided order flow), 1–2 DB round trips execute and are
  immediately discarded.
- **Expected improvement**: removes 1–2 DB round trips (each realistically a few ms on
  Postgres, more under load) from the majority of turns. Not the dominant cost (that's the
  Meta round-trip), but free to fix and adds up under concurrent load.
- **Redis needed?** No.
- **Risk to existing flow**: very low — a one-line reorder (check `interaction.reply_id`
  before calling `_resolve_options`, matching what `resolve_interaction` already checks
  first internally).

### 2. Stop double-fetching Customer/ConversationState/FlowDefinition on the Demo Bot path
- **Problem**: `demo_bot_service.py::_customer_is_at_a_terminal_step` (line 207) fetches
  Customer + GenericConversationState + FlowDefinition, then the very next call
  (`process_inbound_message`) fetches all three again from scratch.
- **Why it causes delay**: 3 fully avoidable DB round trips on every ordinary demo-bot
  turn — the exact path a live sales prospect is talking to.
- **Expected improvement**: a few ms per turn on Postgres; meaningfully reduces DB
  connection-pool pressure under concurrent demo traffic (multiple prospects demoing at
  once, which is the stated real-customer-demo scenario).
- **Redis needed?** No.
- **Risk to existing flow**: low, but non-trivial to do cleanly — `demo_bot_service.py`
  currently treats `_customer_is_at_a_terminal_step` as a read-only, side-effect-free peek
  deliberately kept separate from `process_inbound_message`'s row-locking read (see that
  function's own docstring). Fixing this means threading an already-fetched
  Customer/FlowDefinition through, which touches a function signature shared by several
  call sites in that file — worth a dedicated, reviewed change rather than a quick patch.

### 3. Consider concurrent (not sequential) sends only where message *order* genuinely
   doesn't matter to the customer
- **Problem**: every multi-message reply (image + options, banner + picker text) pays two
  full sequential Meta round-trips.
- **Why it causes delay**: this is the single biggest lever in the whole path — but
  `send_generic_messages_batch`'s own docstring documents that concurrent sending was
  **already tried and reverted** because Meta's image-fetch-and-validate step is slow
  enough that a concurrently-fired text/options message reliably wins the race and arrives
  before its own image, confirmed by live testing.
- **Expected improvement**: recovers one Meta round-trip (commonly 150–500ms) per
  image-bearing reply, if a way is found to preserve arrival order without sequential
  awaiting (e.g. Meta's own message-context/reply-threading feature, if applicable — not
  investigated here since this is diagnosis-only).
- **Redis needed?** No.
- **Risk to existing flow**: **high** if attempted naively — this exact approach already
  caused a real, user-visible ordering bug once. Any change here needs to solve the
  ordering problem first, not just re-introduce `asyncio.gather`.

### 4. If "feels slow" persists after the above, the next real lever is the webhook
   acknowledgement model itself
- **Problem**: HTTP 200 is only returned after the full pipeline (DB + flow engine + Meta
  call) completes, so the customer's own message "read receipt → bot reply" gap is the sum
  of everything in this report.
- **Why it causes delay**: it's not that any one step is slow (locally, total backend time
  excluding Meta is ~20-30ms) — it's that a genuine third-party network call (Meta) sits
  fully synchronously between the customer's tap and the customer's reply, with the whole
  DB transaction held open across it.
- **Expected improvement**: potentially large (the customer stops waiting on Meta's own
  round-trip), but this is exactly the "ack now, process later" architecture change you
  explicitly asked not to do in this pass, and which the product owner already declined
  once before (per the code comment cited above) because it removes the row lock that
  currently prevents two concurrent/redelivered webhook events from double-processing the
  same customer's turn. **Not recommending this now** — flagging it only because it's the
  one structural option left if a genuinely faster feel is required and the above smaller
  fixes aren't enough.
- **Redis needed?** Only if this path is chosen later, and only as a broker for whatever
  background mechanism replaces the current in-request processing (Celery is already in
  the stack for other jobs — `docker-compose.yml` shows `celery-worker`/`celery-beat`
  already running against a `redis` service in this project, currently used for broadcast
  sends, media-status sync, and reconciliation, **never** for inbound webhook processing).
  This is a fact about the existing infrastructure, not a recommendation to use it here.
- **Risk**: high — re-architecting the ack model changes the conversation-state locking
  guarantee the current design deliberately relies on. Explicitly out of scope for this
  pass per your instructions.

---

## Files inspected

`app/api/v1/routers/webhook.py` · `app/services/generic_flow_engine.py` ·
`app/services/flow_engine.py` · `app/services/demo_bot_service.py` ·
`app/services/whatsapp_client.py` · `app/services/conversational_intent.py` ·
`app/services/conversational_style.py` · `app/services/image_presenter.py` ·
`app/services/meta_media_upload.py` · `app/services/template_engine.py` ·
`app/repositories/customer_repository.py` ·
`app/repositories/generic_conversation_repository.py` ·
`app/repositories/flow_definition_repository.py` ·
`app/repositories/restaurant_repository.py` ·
`app/repositories/demo_session_repository.py` ·
`app/models/customer.py` · `app/models/generic_conversation_state.py` ·
`app/models/restaurant.py` · `app/db/session.py` · `app/core/config.py` ·
`docker-compose.yml` · `docker-compose.oracle.yml` ·
`nginx/whatsapp.kelviontech.in.conf` · relevant existing tests under `app/tests/`.

## Files modified (temporary instrumentation only — no behavior change)

- **`app/core/latency_debug.py`** (new file) — the timing/logging helper itself
  (`start`/`mark`/`add_duration`/`time_block`/`finish`), contextvar-based so concurrent
  requests never mix up timings.
- **`app/api/v1/routers/webhook.py`** — added `latency_debug.start()` /
  `.mark("webhook_validation")` / `.mark("message_parsing")` / `.mark("tenant_resolution")`
  / `.tag(...)` / `.finish()` around the existing logic. No control-flow, query, or
  response changed.
- **`app/services/generic_flow_engine.py`** — added `.mark("session_db")` after the
  existing customer/session/flow-definition lookups, `.mark("flow_engine_started"
  /"_completed")` around the existing `engine.handle(...)` call, and
  `time_block("options_lookup"/"intent_processing")` / `time_block("response_preparation")`
  around existing lines inside `handle()` / `_render_step()`. No logic changed.
- **`app/services/flow_engine.py`** (legacy engine, used by any restaurant with
  `uses_generic_engine=False`) — same pattern: `.mark("session_db")` and
  `.mark("flow_engine_started"/"_completed")` around the existing lookups/`engine.handle`
  call.
- **`app/services/whatsapp_client.py`** — wrapped the existing `await
  self._client.post(...)` call in `time_block("meta_send")`. No request/response/retry
  logic changed.

All five diffs were verified to be purely additive (confirmed by re-reading each diff) and
the full relevant test suite (288 tests across webhook/flow-engine/niche/generic-engine
coverage) passes unchanged after these edits.

## Commands used for testing

```bash
# Full existing test suite for every file touched or read during this investigation --
# confirms zero behavior change from the instrumentation.
cd backend
./venv/Scripts/python.exe -m pytest app/tests/ -q -k "flow_engine or niche or webhook or generic"
# -> 288 passed, 393 deselected

./venv/Scripts/python.exe -m pytest app/tests/test_flow_engine.py app/tests/test_webhook_signature.py \
    app/tests/test_demo_bot.py app/tests/test_generic_media_id_cache.py -q
# -> 31 passed
```

A temporary, throwaway benchmark test (`app/tests/test_zz_latency_benchmark.py`, deleted
after use — not part of the permanent suite) drove a 7-turn realistic order conversation
("hi" → pick order flow → pick category → pick item → set quantity → checkout → type a
delivery address) through the **real** `/api/v1/webhook` HTTP route (real signature
verification, real payload shape, real DB), with `webhook._sender` monkeypatched to
`InMemoryWhatsAppSender` so **no code path could reach the real network**, and captured
the resulting `[WA LATENCY]` log lines shown above via:

```bash
./venv/Scripts/python.exe -m pytest app/tests/test_zz_latency_benchmark.py -q -s --log-cli-level=INFO
```

## Whether any external WhatsApp/Meta message was sent

**No.** Every runtime test above ran against the local SQLite test database with either
`InMemoryWhatsAppSender` substituted for the real sender, or (in the standard test suite)
restaurants configured without functioning Meta credentials — `GraphAPIWhatsAppSender.send`
itself no-ops (logs a warning and returns) when `phone_number_id`/`access_token` aren't
both present (`whatsapp_client.py` line ~323), which is an existing safety property of the
code, not something added for this investigation. No HTTP request was made to
`graph.facebook.com` at any point.
