"""Coverage for the funnel-analytics event foundation (see app/models/analytics_event.py
and app/services/analytics.py) -- proves each event type fires from the real engine at
the point it's supposed to, not a bare unit call against record_event in isolation.
"""

from sqlalchemy import select

from app.models.analytics_event import AnalyticsEvent
from app.tests.test_niche_restaurant import (
    CUSTOMER_PHONE,
    CUSTOMER_PROFILE_NAME,
    _get_category_id,
    _get_item,
    _get_customer,
    _send_text,
    _tap,
    restaurant_tenant,
    sender,
)


async def _event_types(db_session, restaurant_id) -> list[str]:
    rows = (
        await db_session.execute(
            select(AnalyticsEvent.event_type).where(AnalyticsEvent.restaurant_id == restaurant_id).order_by(AnalyticsEvent.created_at)
        )
    ).scalars().all()
    return list(rows)


async def test_full_order_flow_emits_the_expected_funnel_events(db_session, restaurant_tenant, sender):
    restaurant = restaurant_tenant
    starters_category_id = await _get_category_id(db_session, restaurant.id, "Starters")
    paneer_item = await _get_item(db_session, restaurant.id, "Paneer Tikka")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:order")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{starters_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{paneer_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "__skip__")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "order:confirm")

    events = await _event_types(db_session, restaurant.id)

    assert "FLOW_STARTED" in events
    assert events.count("NODE_VIEWED") >= 7  # one per step actually rendered along the way
    assert "BUTTON_CLICKED" in events
    assert "PRODUCT_VIEWED" in events
    assert "PRODUCT_ADDED" in events
    assert "CART_STARTED" in events
    assert "CHECKOUT_STARTED" in events
    assert "FLOW_COMPLETED" in events  # order_confirmed is the terminal step

    # Ordering is meaningful: the funnel started before it viewed a product, which is
    # before it added one, which is before checkout started, which is before it completed.
    assert events.index("FLOW_STARTED") < events.index("PRODUCT_VIEWED") < events.index("PRODUCT_ADDED")
    assert events.index("PRODUCT_ADDED") < events.index("CHECKOUT_STARTED") < events.index("FLOW_COMPLETED")

    # Every row is correctly attributed to this restaurant/niche -- tenant isolation for
    # analytics data matters just as much as for any other tenant-scoped table.
    rows = (await db_session.execute(select(AnalyticsEvent).where(AnalyticsEvent.restaurant_id == restaurant.id))).scalars().all()
    assert all(r.niche_code == "restaurant" for r in rows)
    customer = await _get_customer(db_session, restaurant.id)
    assert all(r.customer_id == customer.id for r in rows if r.customer_id is not None)


async def test_second_cart_addition_does_not_re_fire_cart_started(db_session, restaurant_tenant, sender):
    """CART_STARTED marks the cart's 0 -> 1 transition only -- a second item added to an
    already-non-empty cart must not fire it again."""
    restaurant = restaurant_tenant
    starters_category_id = await _get_category_id(db_session, restaurant.id, "Starters")
    mains_category_id = await _get_category_id(db_session, restaurant.id, "Main Course")
    paneer_item = await _get_item(db_session, restaurant.id, "Paneer Tikka")
    butter_chicken = await _get_item(db_session, restaurant.id, "Butter Chicken")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:order")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{starters_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{paneer_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:add_more")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{mains_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{butter_chicken.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")

    events = await _event_types(db_session, restaurant.id)
    assert events.count("CART_STARTED") == 1
    assert events.count("PRODUCT_ADDED") == 2


async def test_human_handoff_emits_handoff_event(db_session, restaurant_tenant, sender):
    restaurant = restaurant_tenant
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:human")

    events = await _event_types(db_session, restaurant.id)
    assert "HUMAN_HANDOFF" in events
    # A human handoff is not itself a "flow completed" state -- the confirmed/terminal
    # step was never reached.
    assert "FLOW_COMPLETED" not in events
