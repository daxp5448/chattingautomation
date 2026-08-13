"""Coverage for the template variables added alongside the Message Management system
(see app/services/generic_flow_engine.py::_prompt_text and the alias points inside
_process_input/_run_action): {{quantity}}, {{address}}, {{order_id}}/{{booking_id}},
{{service_name}}/{{product_name}}, and the always-on {{date}}/{{time}} pair.

Reuses the Restaurant e2e fixture from test_niche_restaurant.py -- driving the real
conversation engine end-to-end is the natural way to prove these variables land in
`GenericConversationState.context` at the right point, not a bare unit call.
"""

from app.tests.test_niche_restaurant import (
    CUSTOMER_PHONE,
    CUSTOMER_PROFILE_NAME,
    _get_category_id,
    _get_item,
    _get_state,
    _get_customer,
    _send_text,
    _tap,
    restaurant_tenant,
    sender,
)


async def test_quantity_service_and_product_name_land_in_context(db_session, restaurant_tenant, sender):
    restaurant = restaurant_tenant
    starters_category_id = await _get_category_id(db_session, restaurant.id, "Starters")
    paneer_item = await _get_item(db_session, restaurant.id, "Paneer Tikka")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:order")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{starters_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{paneer_item.id}")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    # capture_pending_item's aliasing (generic_flow_engine.py::_run_action).
    assert state.context["service_name"] == "Paneer Tikka"
    assert state.context["product_name"] == "Paneer Tikka"

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:3")
    state = await _get_state(db_session, customer.id)
    # quantity_input's aliasing (generic_flow_engine.py::_process_input).
    assert state.context["quantity"] == "3"


async def test_address_order_id_and_booking_id_land_in_context(db_session, restaurant_tenant, sender):
    restaurant = restaurant_tenant
    starters_category_id = await _get_category_id(db_session, restaurant.id, "Starters")
    paneer_item = await _get_item(db_session, restaurant.id, "Paneer Tikka")

    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "hi", profile_name=CUSTOMER_PROFILE_NAME)
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "welcome:order")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"category:{starters_category_id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, f"item:{paneer_item.id}")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "qty:1")
    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "cart:checkout")
    await _send_text(db_session, sender, restaurant, CUSTOMER_PHONE, "221B Baker Street, Bandra West")

    customer = await _get_customer(db_session, restaurant.id)
    state = await _get_state(db_session, customer.id)
    # free_text_input's delivery_address -> {{address}} aliasing.
    assert state.context["address"] == "221B Baker Street, Bandra West"

    await _tap(db_session, sender, restaurant, CUSTOMER_PHONE, "order:confirm")
    state = await _get_state(db_session, customer.id)
    # create_engagement's order_id/booking_id aliasing of last_reference_number.
    assert state.context["order_id"] == state.context["last_reference_number"]
    assert state.context["booking_id"] == state.context["last_reference_number"]
    assert state.context["order_id"]


async def test_date_and_time_are_always_injected_by_prompt_text(db_session, restaurant_tenant, sender):
    """{{date}}/{{time}} are always-available convenience variables (today's server
    date/time) that generic_flow_engine.py::_Engine._prompt_text injects into EVERY
    render's context, whether or not the flow's own captured context has anything
    named that -- proven directly against the real engine method, not a hand-rolled
    substitution, so this can't silently drift from what customers actually see."""
    from app.models.customer import Customer
    from app.services.generic_flow_engine import _Engine

    restaurant = restaurant_tenant
    customer = Customer(restaurant_id=restaurant.id, phone="919876500093", name="Preview Tester")
    db_session.add(customer)
    await db_session.flush()

    engine = _Engine(db_session, sender)
    rendered = await engine._prompt_text(
        restaurant, customer, {"prompt": "Today is {{date}} at {{time}}, {{business_name}}!"}, {}
    )
    assert rendered.startswith("Today is ")
    assert rendered.endswith(f"{restaurant.name}!")
    assert "{{" not in rendered  # both variables actually substituted, not left literal
