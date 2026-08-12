"""Live HTTP smoke test against a real running uvicorn process (not the pytest ASGI
transport). Exercises: auth, restaurant/branch/menu CRUD, the WhatsApp webhook signature
verification + full conversation flow (including Phase 2's coupon step, Razorpay
fallback, invoice attach, FAQ/NLU matching, human handover + staff reply), order
creation, loyalty points, dashboard stats, and Phase 3's multi-branch bot entry ("hi"
must ask which branch before anything else once a restaurant has more than one) --
against an actual server process.
"""

import hashlib
import hmac
import json
import sys
import uuid

import httpx

# Response bodies can contain emoji (bot copy uses them freely, e.g. cart/menu messages).
# Windows consoles default to a codepage (cp1252) that can't encode them -- reconfigure
# stdout so a printable check() call never crashes the whole run over a print statement.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8001/api/v1"
APP_SECRET = "smoke-test-secret"
PHONE_NUMBER_ID = f"SMOKE_{uuid.uuid4().hex[:8]}"
CUSTOMER_PHONE = "919876500000"
CUSTOMER_PHONE_2 = "919876500001"

failures: list[str] = []


def check(label: str, condition: bool, detail: str = ""):
    status = "OK" if condition else "FAIL"
    print(f"[{status}] {label} {detail}")
    if not condition:
        failures.append(label)


def sign(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_webhook(client: httpx.Client, value: dict):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [{"id": "1", "changes": [{"value": value, "field": "messages"}]}],
    }
    body = json.dumps(payload).encode()
    resp = client.post(
        f"{BASE}/webhook",
        content=body,
        headers={"X-Hub-Signature-256": sign(body), "Content-Type": "application/json"},
    )
    check(f"webhook POST ({value['messages'][0].get('type')}: {_body_preview(value)})", resp.status_code == 200, str(resp.status_code))


def _body_preview(value: dict) -> str:
    msg = value["messages"][0]
    if msg.get("type") == "text":
        return msg["text"]["body"][:30]
    if msg.get("type") == "interactive":
        interactive = msg["interactive"]
        reply = interactive.get("list_reply") or interactive.get("button_reply") or {}
        return reply.get("id", "")[:30]
    return ""


def message_value(message: dict, from_phone: str = CUSTOMER_PHONE) -> dict:
    return {
        "messaging_product": "whatsapp",
        "metadata": {"phone_number_id": PHONE_NUMBER_ID},
        "contacts": [{"wa_id": from_phone}],
        "messages": [{"from": from_phone, "id": f"wamid.{uuid.uuid4().hex}", **message}],
    }


def text_msg(body: str, from_phone: str = CUSTOMER_PHONE) -> dict:
    return message_value({"type": "text", "text": {"body": body}}, from_phone)


def button_msg(reply_id: str, from_phone: str = CUSTOMER_PHONE) -> dict:
    return message_value(
        {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": reply_id, "title": reply_id}}}, from_phone
    )


def list_msg(reply_id: str, from_phone: str = CUSTOMER_PHONE) -> dict:
    return message_value(
        {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": reply_id, "title": reply_id}}}, from_phone
    )


def main() -> int:
    client = httpx.Client(timeout=10.0)

    resp = client.get("http://127.0.0.1:8001/health")
    check("GET /health", resp.status_code == 200, resp.text)

    resp = client.get(
        f"{BASE}/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "smoke-verify-token", "hub.challenge": "abc123"},
    )
    check("GET /webhook verify handshake", resp.status_code == 200 and resp.text == "abc123", resp.text)

    # --- Auth ---------------------------------------------------------------------
    admin_email = f"admin_{uuid.uuid4().hex[:8]}@smoke.kelviontech.dev"
    resp = client.post(f"{BASE}/auth/register", json={"email": admin_email, "password": "SmokeTest123!", "role": "super_admin"})
    check("POST /auth/register (super_admin)", resp.status_code == 201, resp.text)
    resp = client.post(f"{BASE}/auth/login", json={"email": admin_email, "password": "SmokeTest123!"})
    check("POST /auth/login", resp.status_code == 200, resp.text)
    tokens = resp.json()
    admin_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    resp = client.post(f"{BASE}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    check("POST /auth/refresh", resp.status_code == 200, resp.text)

    # --- Restaurant onboarding (Razorpay enabled but no credentials -> must fall back to COD) --
    slug = f"smoke-diner-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        f"{BASE}/restaurants",
        json={
            "name": "Smoke Test Diner",
            "slug": slug,
            "delivery_charge": 25,
            "whatsapp_phone_number_id": PHONE_NUMBER_ID,
            "payment_methods": ["cod", "razorpay"],
            "default_payment_method": "razorpay",
            "loyalty_settings": {"points_per_currency_unit": 0.1, "redemption_value_per_point": 1.0},
        },
        headers=admin_headers,
    )
    check("POST /restaurants", resp.status_code == 201, resp.text)
    restaurant = resp.json()
    restaurant_id = restaurant["id"]
    check("restaurant.whatsapp_phone_number_id persisted", restaurant["whatsapp_phone_number_id"] == PHONE_NUMBER_ID)

    # One-click onboarding: creating a restaurant auto-creates its owner login too, so a
    # super_admin never has to separately call /auth/register for every new restaurant.
    check("restaurant creation returns an owner_email", "owner_email" in restaurant, resp.text)
    check("restaurant creation returns a one-time owner password", bool(restaurant.get("owner_temporary_password")), resp.text)
    owner_email = restaurant["owner_email"]
    owner_password = restaurant["owner_temporary_password"]

    resp = client.get(f"{BASE}/restaurants", headers=admin_headers)
    check("GET /restaurants (super_admin list)", resp.status_code == 200 and len(resp.json()) >= 1, resp.text)

    resp = client.patch(f"{BASE}/restaurants/{restaurant_id}", json={"delivery_charge": 30}, headers=admin_headers)
    check("PATCH /restaurants/{id}", resp.status_code == 200 and resp.json()["delivery_charge"] == 30, resp.text)

    # A second account (not the bootstrap one) can no longer self-register unauthenticated --
    # this is exactly the hole a code review flagged: anyone could've POSTed role=super_admin.
    resp = client.post(
        f"{BASE}/auth/register",
        json={"email": f"attacker_{uuid.uuid4().hex[:8]}@smoke.kelviontech.dev", "password": "SmokeTest123!", "role": "super_admin"},
    )
    check("unauthenticated register blocked once an account exists", resp.status_code == 401, str(resp.status_code))

    resp = client.post(f"{BASE}/auth/login", json={"email": owner_email, "password": owner_password})
    check("auto-created owner can log in with the returned temporary password", resp.status_code == 200, resp.text)
    owner_headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # An owner still can't self-elevate to super_admin or create users on someone else's restaurant.
    resp = client.post(
        f"{BASE}/auth/register",
        json={"email": f"sneaky_{uuid.uuid4().hex[:8]}@smoke.kelviontech.dev", "password": "SmokeTest123!", "role": "super_admin"},
        headers=owner_headers,
    )
    check("owner blocked from creating a super_admin", resp.status_code == 403, str(resp.status_code))

    resp = client.get(f"{BASE}/restaurants/{uuid.uuid4()}", headers=owner_headers)
    check("owner blocked from foreign restaurant", resp.status_code == 403, str(resp.status_code))

    # --- Branch / Category / Product -------------------------------------------------
    resp = client.post(
        f"{BASE}/restaurants/{restaurant_id}/branches",
        json={"name": "Main", "address": "1 Smoke Test Rd", "phone": "111-111-1111"},
        headers=owner_headers,
    )
    check("POST branches", resp.status_code == 201, resp.text)
    branch_id = resp.json()["id"]

    resp = client.post(f"{BASE}/restaurants/{restaurant_id}/categories", json={"name": "Mains", "display_order": 1}, headers=owner_headers)
    check("POST categories", resp.status_code == 201, resp.text)
    category_id = resp.json()["id"]

    resp = client.post(
        f"{BASE}/restaurants/{restaurant_id}/products",
        json={"name": "Smoke Burger", "category_id": category_id, "price": 199, "gst_percent": 5},
        headers=owner_headers,
    )
    check("POST products", resp.status_code == 201, resp.text)
    product_id = resp.json()["id"]

    resp = client.post(
        f"{BASE}/restaurants/{restaurant_id}/products",
        json={"name": "Smoke Special Pizza", "category_id": category_id, "price": 299, "is_featured": True},
        headers=owner_headers,
    )
    check("POST products (featured)", resp.status_code == 201, resp.text)
    special_product_id = resp.json()["id"]

    # --- Coupon + FAQ setup (Phase 2) -------------------------------------------------
    resp = client.post(
        f"{BASE}/restaurants/{restaurant_id}/coupons",
        json={"code": "SMOKE30", "type": "flat", "value": 30},
        headers=owner_headers,
    )
    check("POST coupons", resp.status_code == 201, resp.text)

    resp = client.post(
        f"{BASE}/restaurants/{restaurant_id}/faq",
        json={"trigger_keywords": ["delivery time", "how long"], "answer": "We deliver in 30-45 minutes."},
        headers=owner_headers,
    )
    check("POST faq", resp.status_code == 201, resp.text)

    resp = client.put(
        f"{BASE}/restaurants/{restaurant_id}/bot/messages",
        json={"key": "welcome", "content": "Hi from smoke test {{restaurant_name}}!"},
        headers=owner_headers,
    )
    check("PUT bot/messages (welcome override)", resp.status_code == 200, resp.text)

    # --- FAQ match should NOT trigger a handover -------------------------------------
    post_webhook(client, text_msg("what's your delivery time?"))
    resp = client.get(f"{BASE}/restaurants/{restaurant_id}/conversations", headers=owner_headers)
    check("FAQ match did not create a handover", resp.status_code == 200 and len(resp.json()) == 0, resp.text)

    # --- Full order flow through the live webhook, using the coupon -------------------
    # Single-branch restaurant: "hi" goes straight to the welcome menu, no branch prompt.
    post_webhook(client, text_msg("hi"))
    post_webhook(client, button_msg("button:order_food"))
    post_webhook(client, list_msg(f"category:{category_id}"))
    post_webhook(client, list_msg(f"product:{product_id}"))
    post_webhook(client, text_msg("3"))
    post_webhook(client, button_msg("cart:checkout"))
    post_webhook(client, button_msg("fulfillment:delivery"))
    post_webhook(client, text_msg("SMOKE30"))  # apply the coupon
    post_webhook(client, text_msg("42 Smoke Test Ave"))
    post_webhook(client, button_msg("order:confirm"))

    resp = client.post(
        f"{BASE}/webhook",
        content=b'{"object":"whatsapp_business_account","entry":[]}',
        headers={"X-Hub-Signature-256": "sha256=deadbeef", "Content-Type": "application/json"},
    )
    check("webhook rejects bad signature", resp.status_code == 401, str(resp.status_code))

    # --- Verify order was created correctly, with coupon discount + Razorpay fallback --
    resp = client.get(f"{BASE}/restaurants/{restaurant_id}/orders", headers=owner_headers)
    check("GET orders", resp.status_code == 200, resp.text)
    orders = resp.json()
    check("exactly one order created", len(orders) == 1, str(len(orders)))
    order = orders[0] if orders else None
    if order:
        expected_subtotal = 199 * 3
        expected_tax = round(expected_subtotal * 0.05, 2)
        expected_total = expected_subtotal + expected_tax + 30 - 30  # + delivery - coupon discount
        check("order.subtotal correct", float(order["subtotal"]) == expected_subtotal, str(order["subtotal"]))
        check("order.discount correct (coupon applied)", float(order["discount"]) == 30, str(order["discount"]))
        check("order.total correct", float(order["total"]) == expected_total, f"{order['total']} vs {expected_total}")
        check(
            "order.payment_method fell back to cod (no real Razorpay creds)",
            order["payment_method"] == "cod",
            order["payment_method"],
        )
        check("order.status is pending", order["status"] == "pending", order["status"])
        check("order.fulfillment_type is delivery", order["fulfillment_type"] == "delivery", order["fulfillment_type"])
        check("order.invoice_url present (or gracefully absent if no storage backend)", "invoice_url" in order)

        resp = client.patch(f"{BASE}/restaurants/{restaurant_id}/orders/{order['id']}/status", json={"status": "completed"}, headers=owner_headers)
        check("PATCH order status -> completed", resp.status_code == 200 and resp.json()["status"] == "completed", resp.text)

        resp = client.get(f"{BASE}/restaurants/{restaurant_id}/customers", headers=owner_headers)
        customers = resp.json()
        check("customer exists after order", len(customers) == 1, str(customers))
        if customers:
            check("customer earned loyalty points on completion", customers[0]["loyalty_points"] > 0, str(customers[0]["loyalty_points"]))

    # --- Human handover: unmatched free text --------------------------------------------
    post_webhook(client, text_msg("completely unrelated gibberish nonsense"))
    resp = client.get(f"{BASE}/restaurants/{restaurant_id}/conversations", headers=owner_headers)
    check("GET conversations shows handed-over customer", resp.status_code == 200 and len(resp.json()) == 1, resp.text)
    conversations = resp.json()
    if conversations:
        customer_id = conversations[0]["customer_id"]
        resp = client.get(f"{BASE}/restaurants/{restaurant_id}/conversations/{customer_id}/messages", headers=owner_headers)
        check("GET conversation transcript", resp.status_code == 200 and len(resp.json()) > 0, resp.text)

        resp = client.post(
            f"{BASE}/restaurants/{restaurant_id}/conversations/{customer_id}/messages",
            json={"body": "Hi, how can I help?"},
            headers=owner_headers,
        )
        check("POST staff reply", resp.status_code == 201, resp.text)

        resp = client.post(f"{BASE}/restaurants/{restaurant_id}/conversations/{customer_id}/resolve", headers=owner_headers)
        check("POST resolve conversation", resp.status_code == 204, str(resp.status_code))

        resp = client.get(f"{BASE}/restaurants/{restaurant_id}/conversations", headers=owner_headers)
        check("conversation no longer listed after resolve", resp.status_code == 200 and len(resp.json()) == 0, resp.text)

    # --- Multi-branch entry: a second branch means "hi" must ask which branch first -----
    resp = client.post(
        f"{BASE}/restaurants/{restaurant_id}/branches",
        json={"name": "Downtown", "address": "2 Smoke Test Ave", "phone": "222-222-2222"},
        headers=owner_headers,
    )
    check("POST second branch", resp.status_code == 201, resp.text)
    branch2_id = resp.json()["id"]

    post_webhook(client, text_msg("hi", CUSTOMER_PHONE_2))
    post_webhook(client, list_msg(f"branch:{branch2_id}", CUSTOMER_PHONE_2))
    post_webhook(client, button_msg("button:today_special", CUSTOMER_PHONE_2))
    post_webhook(client, list_msg(f"product:{special_product_id}", CUSTOMER_PHONE_2))
    post_webhook(client, text_msg("1", CUSTOMER_PHONE_2))
    post_webhook(client, button_msg("cart:checkout", CUSTOMER_PHONE_2))
    post_webhook(client, button_msg("fulfillment:pickup", CUSTOMER_PHONE_2))  # pickup skips the address step entirely
    post_webhook(client, text_msg("skip", CUSTOMER_PHONE_2))
    post_webhook(client, button_msg("order:confirm", CUSTOMER_PHONE_2))

    resp = client.get(f"{BASE}/restaurants/{restaurant_id}/orders", headers=owner_headers)
    orders = resp.json()
    check("second order created via multi-branch flow", len(orders) == 2, str(len(orders)))
    branch2_order = next((o for o in orders if o["branch_id"] == branch2_id), None)
    check("order placed against the branch picked at 'hi'", branch2_order is not None, str(orders))
    if branch2_order:
        check(
            "order routed via Today's Special ordered the featured product",
            float(branch2_order["subtotal"]) == 299,
            str(branch2_order["subtotal"]),
        )
        check("pickup order has fulfillment_type=pickup", branch2_order["fulfillment_type"] == "pickup", branch2_order["fulfillment_type"])
        check("pickup order has zero delivery charge", float(branch2_order["delivery_charge"]) == 0, str(branch2_order["delivery_charge"]))

    resp = client.get(f"{BASE}/restaurants/{restaurant_id}/customers", headers=owner_headers)
    check("second customer created for second branch's order", resp.status_code == 200 and len(resp.json()) == 2, resp.text)

    # --- Dashboard stats ------------------------------------------------------------------
    resp = client.get(f"{BASE}/restaurants/{restaurant_id}/dashboard/stats", headers=owner_headers)
    check("GET dashboard/stats", resp.status_code == 200, resp.text)
    if resp.status_code == 200:
        stats = resp.json()
        check("dashboard total_orders == 2", stats["total_orders"] == 2, str(stats))
        check("dashboard total_customers == 2", stats["total_customers"] == 2, str(stats))

    print()
    if failures:
        print(f"{len(failures)} check(s) FAILED: {failures}")
        return 1
    print("All smoke test checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
