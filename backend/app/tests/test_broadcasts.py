"""Proof for Phase 2, Item 2: Broadcast Module -- segmentation, the marketing_opt_in
guardrail, the stale-state recheck at send time (not just snapshot time), the daily
recipient cap, variable-count validation, scheduling via the beat-task poller (not
apply_async), the consecutive-failure circuit breaker, crash-resume, tenant isolation,
and role gating.
"""

import itertools

from sqlalchemy import select

from app.core.security import encrypt_secret, hash_password
from app.models.broadcast import BroadcastCampaign, BroadcastRecipient
from app.models.customer import Customer
from app.models.enums import BroadcastRecipientStatus, BroadcastStatus, TemplateCategory, TemplateStatus
from app.models.restaurant import Restaurant
from app.models.user import User
from app.models.whatsapp_template import WhatsAppTemplate
from app.services import broadcast_service
from app.services.whatsapp_client import InMemoryWhatsAppSender
from app.tasks import broadcast_dispatch, broadcast_sender
from app.tasks.broadcast_dispatch import _dispatch_due_campaigns
from app.tasks.broadcast_sender import _send_broadcast_campaign

_wamid_counter = itertools.count(1)


async def _register_and_login(client, restaurant_id, role="owner", email="owner@broadcast-test.dev"):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPass123!", "role": role, "restaurant_id": str(restaurant_id)},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass123!"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_restaurant(db_session, slug: str, daily_cap: int = 250) -> Restaurant:
    restaurant = Restaurant(
        name=f"Broadcast Test {slug}", slug=f"broadcast-test-{slug}",
        whatsapp_phone_number_id=f"BROADCAST_TEST_PHONE_{slug}",
        whatsapp_access_token_encrypted=encrypt_secret("fake-access-token"),
        broadcast_daily_cap=daily_cap,
    )
    db_session.add(restaurant)
    await db_session.commit()
    return restaurant


async def _make_template(db_session, restaurant, name="promo", category=TemplateCategory.MARKETING, placeholders=1) -> WhatsAppTemplate:
    body = "Hi " + " ".join(f"{{{{{i + 1}}}}}" for i in range(placeholders)) if placeholders else "Hi there"
    template = WhatsAppTemplate(
        restaurant_id=restaurant.id, name=name, category=category, language="en_US",
        body_text=body, status=TemplateStatus.APPROVED, meta_template_id=f"meta_{name}",
    )
    db_session.add(template)
    await db_session.commit()
    return template


async def _make_customer(db_session, restaurant, phone, tags=None, opted_in=False, blocked=False) -> Customer:
    customer = Customer(
        restaurant_id=restaurant.id, phone=phone, name=f"Customer {phone[-4:]}",
        tags=tags or [], marketing_opt_in=opted_in, is_blocked=blocked,
    )
    db_session.add(customer)
    await db_session.commit()
    return customer


# --- segmentation ----------------------------------------------------------------------


async def test_segment_preview_matches_by_tag(client, db_session):
    restaurant = await _make_restaurant(db_session, "segtag")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    await _make_customer(db_session, restaurant, "919000000001", tags=["vip"])
    await _make_customer(db_session, restaurant, "919000000002", tags=["regular"])
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "VIP blast", "template_id": str(template.id), "segment_tags": ["vip"], "variable_template": []},
    )
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    preview = await client.get(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/segment-preview", headers=headers)
    assert preview.status_code == 200
    assert preview.json()["matching_customers"] == 1


async def test_empty_segment_tags_means_all_non_blocked(client, db_session):
    restaurant = await _make_restaurant(db_session, "segall")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    await _make_customer(db_session, restaurant, "919000000011")
    await _make_customer(db_session, restaurant, "919000000012")
    await _make_customer(db_session, restaurant, "919000000013", blocked=True)
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Everyone", "template_id": str(template.id), "segment_tags": [], "variable_template": []},
    )
    campaign_id = created.json()["id"]
    preview = await client.get(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/segment-preview", headers=headers)
    assert preview.json()["matching_customers"] == 2  # blocked customer excluded


# --- marketing_opt_in guardrail ----------------------------------------------------------


async def test_marketing_campaign_excludes_non_opted_in(client, db_session):
    restaurant = await _make_restaurant(db_session, "optin")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.MARKETING, placeholders=0)
    await _make_customer(db_session, restaurant, "919000000021", opted_in=True)
    await _make_customer(db_session, restaurant, "919000000022", opted_in=False)
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Marketing", "template_id": str(template.id), "segment_tags": [], "variable_template": []},
    )
    campaign_id = created.json()["id"]
    started = await client.post(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["total_recipients"] == 1  # only the opted-in customer


async def test_utility_campaign_does_not_filter_on_opt_in(client, db_session):
    restaurant = await _make_restaurant(db_session, "utilityoptin")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    await _make_customer(db_session, restaurant, "919000000031", opted_in=False)
    await _make_customer(db_session, restaurant, "919000000032", opted_in=False)
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Utility", "template_id": str(template.id), "segment_tags": [], "variable_template": []},
    )
    campaign_id = created.json()["id"]
    started = await client.post(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["total_recipients"] == 2  # opt-in not required for utility


# --- start-time validation ---------------------------------------------------------------


async def test_start_rejects_variable_count_mismatch(client, db_session):
    restaurant = await _make_restaurant(db_session, "varmismatch")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=2)
    await _make_customer(db_session, restaurant, "919000000041")
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Bad vars", "template_id": str(template.id), "segment_tags": [], "variable_template": ["only one"]},
    )
    campaign_id = created.json()["id"]
    started = await client.post(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/start", headers=headers)
    assert started.status_code == 400
    assert "variable" in started.json()["detail"].lower()


async def test_start_rejects_over_daily_cap(client, db_session):
    restaurant = await _make_restaurant(db_session, "overcap", daily_cap=1)
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    await _make_customer(db_session, restaurant, "919000000051")
    await _make_customer(db_session, restaurant, "919000000052")
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Too big", "template_id": str(template.id), "segment_tags": [], "variable_template": []},
    )
    campaign_id = created.json()["id"]
    started = await client.post(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/start", headers=headers)
    assert started.status_code == 400
    assert "broadcast_daily_cap" in started.json()["detail"]


async def test_start_rejects_non_approved_template(client, db_session):
    restaurant = await _make_restaurant(db_session, "notapproved")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    template.status = TemplateStatus.PENDING
    await db_session.commit()
    await _make_customer(db_session, restaurant, "919000000061")
    headers = await _register_and_login(client, restaurant.id)

    created = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Not ready", "template_id": str(template.id), "segment_tags": [], "variable_template": []},
    )
    campaign_id = created.json()["id"]
    started = await client.post(f"/api/v1/restaurants/{restaurant.id}/broadcasts/{campaign_id}/start", headers=headers)
    assert started.status_code == 400
    assert "approved" in started.json()["detail"].lower()


# --- send task: success/failure/skip, stale-state recheck --------------------------------


async def test_send_task_marks_sent_and_failed_recipients(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "sendok")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    good = await _make_customer(db_session, restaurant, "919000000071")
    bad = await _make_customer(db_session, restaurant, "919000000072")

    campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Send test",
        segment_tags=[], variable_template=[], status=BroadcastStatus.SENDING, total_recipients=2,
    )
    db_session.add(campaign)
    await db_session.flush()
    db_session.add_all([
        BroadcastRecipient(campaign_id=campaign.id, customer_id=good.id, status=BroadcastRecipientStatus.PENDING),
        BroadcastRecipient(campaign_id=campaign.id, customer_id=bad.id, status=BroadcastRecipientStatus.PENDING),
    ])
    await db_session.commit()
    campaign_id, good_id, bad_id, bad_phone = campaign.id, good.id, bad.id, bad.phone  # captured before expire_all() below

    sender = InMemoryWhatsAppSender()

    async def flaky_send(phone_number_id, access_token, message):
        if message.to == bad_phone:
            raise RuntimeError("whatsapp 500")
        await InMemoryWhatsAppSender.send(sender, phone_number_id, access_token, message)

    monkeypatch.setattr(broadcast_sender, "_sender", sender)
    monkeypatch.setattr(sender, "send", flaky_send)
    monkeypatch.setattr(broadcast_sender, "SEND_PACING_SECONDS", 0)

    result = await _send_broadcast_campaign(str(campaign_id))
    assert result == {"sent": 1, "failed": 1, "skipped": 0}

    db_session.expire_all()
    refreshed = (await db_session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id))).scalar_one()
    assert refreshed.status == BroadcastStatus.COMPLETED
    assert refreshed.sent_count == 1
    assert refreshed.failed_count == 1

    recipients = (await db_session.execute(select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == campaign_id))).scalars().all()
    by_customer = {r.customer_id: r.status for r in recipients}
    assert by_customer[good_id] == BroadcastRecipientStatus.SENT
    assert by_customer[bad_id] == BroadcastRecipientStatus.FAILED


async def test_send_task_skips_customer_blocked_after_snapshot(db_session, monkeypatch):
    """The bug the design review caught: a customer can block themselves (or be
    anonymized) after the campaign snapshot but before their turn in the send loop --
    proves the recheck happens at send time, not only at snapshot time."""
    restaurant = await _make_restaurant(db_session, "staleblock")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    customer = await _make_customer(db_session, restaurant, "919000000081")

    campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Stale block test",
        segment_tags=[], variable_template=[], status=BroadcastStatus.SENDING, total_recipients=1,
    )
    db_session.add(campaign)
    await db_session.flush()
    db_session.add(BroadcastRecipient(campaign_id=campaign.id, customer_id=customer.id, status=BroadcastRecipientStatus.PENDING))
    await db_session.commit()
    campaign_id, customer_id = campaign.id, customer.id

    # Simulate the customer blocking themselves AFTER the snapshot but BEFORE the task runs.
    customer.is_blocked = True
    await db_session.commit()

    sender = InMemoryWhatsAppSender()
    monkeypatch.setattr(broadcast_sender, "_sender", sender)
    monkeypatch.setattr(broadcast_sender, "SEND_PACING_SECONDS", 0)

    result = await _send_broadcast_campaign(str(campaign_id))
    assert result == {"sent": 0, "failed": 0, "skipped": 1}
    assert sender.sent == []  # never actually sent

    db_session.expire_all()
    recipient = (await db_session.execute(select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == campaign_id))).scalar_one()
    assert recipient.status == BroadcastRecipientStatus.SKIPPED


async def test_send_task_circuit_breaker_aborts_after_consecutive_failures(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "circuitbreak")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    customers = [await _make_customer(db_session, restaurant, f"91900000009{i}") for i in range(7)]

    campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Breaker test",
        segment_tags=[], variable_template=[], status=BroadcastStatus.SENDING, total_recipients=7,
    )
    db_session.add(campaign)
    await db_session.flush()
    for c in customers:
        db_session.add(BroadcastRecipient(campaign_id=campaign.id, customer_id=c.id, status=BroadcastRecipientStatus.PENDING))
    await db_session.commit()
    campaign_id = campaign.id

    sender = InMemoryWhatsAppSender()

    async def always_fail(phone_number_id, access_token, message):
        raise RuntimeError("token revoked")

    monkeypatch.setattr(broadcast_sender, "_sender", sender)
    monkeypatch.setattr(sender, "send", always_fail)
    monkeypatch.setattr(broadcast_sender, "SEND_PACING_SECONDS", 0)
    monkeypatch.setattr(broadcast_sender, "CONSECUTIVE_FAILURE_LIMIT", 5)

    result = await _send_broadcast_campaign(str(campaign_id))
    assert result["failed"] == 5  # aborted after the 5th consecutive failure

    db_session.expire_all()
    refreshed = (await db_session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id))).scalar_one()
    assert refreshed.status == BroadcastStatus.FAILED
    assert "consecutive" in refreshed.failure_reason.lower()

    recipients = (await db_session.execute(select(BroadcastRecipient).where(BroadcastRecipient.campaign_id == campaign_id))).scalars().all()
    still_pending = [r for r in recipients if r.status == BroadcastRecipientStatus.PENDING]
    assert len(still_pending) == 2  # the last 2 of 7 never attempted


async def test_send_task_resumes_only_pending_recipients_after_crash(db_session, monkeypatch):
    """Simulates a task crash/restart: one recipient already SENT (from a prior partial
    run), one still PENDING -- proves resume only touches the still-pending row."""
    restaurant = await _make_restaurant(db_session, "resume")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    already_sent = await _make_customer(db_session, restaurant, "919000000101")
    still_pending = await _make_customer(db_session, restaurant, "919000000102")

    campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Resume test",
        segment_tags=[], variable_template=[], status=BroadcastStatus.SENDING,
        total_recipients=2, sent_count=1,
    )
    db_session.add(campaign)
    await db_session.flush()
    db_session.add_all([
        BroadcastRecipient(campaign_id=campaign.id, customer_id=already_sent.id, status=BroadcastRecipientStatus.SENT),
        BroadcastRecipient(campaign_id=campaign.id, customer_id=still_pending.id, status=BroadcastRecipientStatus.PENDING),
    ])
    await db_session.commit()
    campaign_id = campaign.id

    sender = InMemoryWhatsAppSender()
    monkeypatch.setattr(broadcast_sender, "_sender", sender)
    monkeypatch.setattr(broadcast_sender, "SEND_PACING_SECONDS", 0)

    result = await _send_broadcast_campaign(str(campaign_id))
    assert result == {"sent": 1, "failed": 0, "skipped": 0}
    assert len(sender.sent) == 1
    assert sender.sent[0].to == still_pending.phone  # never re-sent to already_sent


async def test_send_task_personalizes_customer_name_token(db_session, monkeypatch):
    restaurant = await _make_restaurant(db_session, "personalize")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=1)
    customer = await _make_customer(db_session, restaurant, "919000000111")

    campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Personalized",
        segment_tags=[], variable_template=["{{customer_name}}"], status=BroadcastStatus.SENDING, total_recipients=1,
    )
    db_session.add(campaign)
    await db_session.flush()
    db_session.add(BroadcastRecipient(campaign_id=campaign.id, customer_id=customer.id, status=BroadcastRecipientStatus.PENDING))
    await db_session.commit()
    campaign_id = campaign.id

    sender = InMemoryWhatsAppSender()
    monkeypatch.setattr(broadcast_sender, "_sender", sender)
    monkeypatch.setattr(broadcast_sender, "SEND_PACING_SECONDS", 0)

    await _send_broadcast_campaign(str(campaign_id))
    assert len(sender.sent) == 1
    assert sender.sent[0].payload["template"]["components"][0]["parameters"][0]["text"] == customer.name


# --- variable count helper -----------------------------------------------------------------


def test_count_template_placeholders():
    assert broadcast_service.count_template_placeholders("Hi there") == 0
    assert broadcast_service.count_template_placeholders("Hi {{1}}, order {{2}} is ready") == 2


# --- scheduling via beat dispatch, not apply_async ------------------------------------------


async def test_scheduled_campaign_not_started_until_due(db_session, monkeypatch):
    from datetime import timedelta

    from app.db.base import utcnow

    restaurant = await _make_restaurant(db_session, "scheddue")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    await _make_customer(db_session, restaurant, "919000000121")

    future_campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Future",
        segment_tags=[], variable_template=[], status=BroadcastStatus.SCHEDULED,
        scheduled_at=utcnow() + timedelta(hours=2), total_recipients=1,
    )
    due_campaign = BroadcastCampaign(
        restaurant_id=restaurant.id, template_id=template.id, name="Due",
        segment_tags=[], variable_template=[], status=BroadcastStatus.SCHEDULED,
        scheduled_at=utcnow() - timedelta(minutes=5), total_recipients=1,
    )
    db_session.add_all([future_campaign, due_campaign])
    await db_session.commit()
    future_id, due_id = future_campaign.id, due_campaign.id

    dispatched_ids = []

    async def fake_enqueue(campaign_id):
        dispatched_ids.append(campaign_id)

    monkeypatch.setattr(broadcast_dispatch.broadcast_service, "enqueue_broadcast_send", fake_enqueue)

    dispatched_count = await _dispatch_due_campaigns()
    assert dispatched_count == 1
    assert dispatched_ids == [due_id]

    db_session.expire_all()
    future_refreshed = (await db_session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == future_id))).scalar_one()
    due_refreshed = (await db_session.execute(select(BroadcastCampaign).where(BroadcastCampaign.id == due_id))).scalar_one()
    assert future_refreshed.status == BroadcastStatus.SCHEDULED  # untouched
    assert due_refreshed.status == BroadcastStatus.SENDING  # flipped, ready for the send task


# --- tenant isolation + role gating ---------------------------------------------------------


async def test_owner_cannot_read_another_tenants_campaigns(client, db_session):
    restaurant_a = await _make_restaurant(db_session, "tenanta")
    restaurant_b = await _make_restaurant(db_session, "tenantb")
    template_b = await _make_template(db_session, restaurant_b, category=TemplateCategory.UTILITY, placeholders=0)
    headers_a = await _register_and_login(client, restaurant_a.id, email="owner-a@broadcast-test.dev")

    user_b = User(
        email="owner-b@broadcast-test.dev", hashed_password=hash_password("TestPass123!"),
        role="owner", restaurant_id=restaurant_b.id, is_active=True,
    )
    db_session.add(user_b)
    await db_session.commit()
    login_b = await client.post("/api/v1/auth/login", json={"email": "owner-b@broadcast-test.dev", "password": "TestPass123!"})
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    created_b = await client.post(
        f"/api/v1/restaurants/{restaurant_b.id}/broadcasts", headers=headers_b,
        json={"name": "B's campaign", "template_id": str(template_b.id), "segment_tags": [], "variable_template": []},
    )
    campaign_id = created_b.json()["id"]

    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/broadcasts/{campaign_id}", headers=headers_a)
    assert resp.status_code == 403
    resp = await client.get(f"/api/v1/restaurants/{restaurant_b.id}/broadcasts", headers=headers_a)
    assert resp.status_code == 403


async def test_cashier_forbidden_from_creating_campaigns(client, db_session):
    restaurant = await _make_restaurant(db_session, "cashier")
    template = await _make_template(db_session, restaurant, category=TemplateCategory.UTILITY, placeholders=0)
    headers = await _register_and_login(client, restaurant.id, role="cashier", email="cashier@broadcast-test.dev")
    resp = await client.post(
        f"/api/v1/restaurants/{restaurant.id}/broadcasts", headers=headers,
        json={"name": "Nope", "template_id": str(template.id), "segment_tags": [], "variable_template": []},
    )
    assert resp.status_code == 403
