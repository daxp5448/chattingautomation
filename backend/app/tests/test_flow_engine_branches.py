from sqlalchemy import select

from app.models.branch import Branch
from app.models.conversation_state import ConversationState
from app.models.enums import BranchStatus, ConversationStep
from app.models.product import Product
from app.tests.test_flow_engine import (  # noqa: F401 -- reuse fixtures/helpers
    _button_reply,
    _list_reply,
    _message_value,
    _post_webhook,
    _text,
    _use_in_memory_sender,
    demo_tenant,
)


def _last_body(fake_sender) -> str:
    payload = fake_sender.sent[-1].payload
    if payload["type"] == "text":
        return payload["text"]["body"]
    if payload["type"] == "interactive":
        return payload["interactive"]["body"]["text"]
    return ""


def _last_rows(fake_sender) -> list[dict]:
    payload = fake_sender.sent[-1].payload
    return payload["interactive"]["action"]["sections"][0]["rows"]


async def test_single_branch_entry_skips_branch_selection(client, db_session, demo_tenant, _use_in_memory_sender):
    await _post_webhook(client, _message_value(_text("hi")))

    # Single-branch restaurant: straight to the welcome menu, no branch prompt at all.
    assert "Select a branch" not in _last_body(_use_in_memory_sender)
    rows = _last_rows(_use_in_memory_sender)
    assert {r["id"] for r in rows} == {
        "button:order_food",
        "button:view_menu",
        "button:today_special",
        "button:our_location",
        "button:contact_restaurant",
    }

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.context.get("branch_id") == str(demo_tenant["branch"].id)


async def test_multi_branch_entry_asks_for_branch_first(client, db_session, demo_tenant, _use_in_memory_sender):
    restaurant = demo_tenant["restaurant"]
    branch2 = Branch(restaurant_id=restaurant.id, name="Downtown", status=BranchStatus.OPEN)
    db_session.add(branch2)
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))
    assert "Select a branch" in _last_body(_use_in_memory_sender)

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.SELECT_BRANCH
    assert "branch_id" not in state.context

    await _post_webhook(client, _message_value(_list_reply(f"branch:{branch2.id}")))
    rows = _last_rows(_use_in_memory_sender)
    assert "button:order_food" in {r["id"] for r in rows}

    await db_session.refresh(state)
    assert state.context["branch_id"] == str(branch2.id)
    assert state.current_step == ConversationStep.WELCOME


async def test_view_menu_button_skips_branch_reselection(client, db_session, demo_tenant, _use_in_memory_sender):
    category = demo_tenant["category"]
    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:view_menu")))

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.SELECT_CATEGORY
    rows = _last_rows(_use_in_memory_sender)
    assert {r["id"] for r in rows} == {f"category:{category.id}"}


async def test_today_special_lists_featured_products_then_can_be_ordered(client, db_session, demo_tenant, _use_in_memory_sender):
    restaurant = demo_tenant["restaurant"]
    special = Product(
        restaurant_id=restaurant.id,
        category_id=demo_tenant["category"].id,
        name="Chef's Pizza",
        price=350,
        is_featured=True,
    )
    db_session.add(special)
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:today_special")))

    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.SELECT_PRODUCT
    rows = _last_rows(_use_in_memory_sender)
    assert len(rows) == 1
    assert rows[0]["id"] == f"product:{special.id}"
    assert rows[0]["title"] == "Chef's Pizza"
    assert "350" in rows[0]["description"]

    # Selecting the featured product flows into the normal quantity/cart path.
    await _post_webhook(client, _message_value(_list_reply(f"product:{special.id}")))
    await db_session.refresh(state)
    assert state.current_step == ConversationStep.SELECT_QUANTITY


async def test_today_special_empty_sends_fallback_message(client, db_session, demo_tenant, _use_in_memory_sender):
    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:today_special")))

    assert "special" in _last_body(_use_in_memory_sender).lower()
    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.WELCOME


async def test_our_location_sends_branch_address(client, db_session, demo_tenant, _use_in_memory_sender):
    branch = demo_tenant["branch"]
    branch.address = "123 Main Street"
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:our_location")))

    assert "123 Main Street" in _last_body(_use_in_memory_sender)


async def test_contact_restaurant_prefers_branch_phone(client, db_session, demo_tenant, _use_in_memory_sender):
    restaurant = demo_tenant["restaurant"]
    restaurant.support_number = "000-000-0000"
    branch = demo_tenant["branch"]
    branch.phone = "999-888-7777"
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:contact_restaurant")))

    assert "999-888-7777" in _last_body(_use_in_memory_sender)
    assert "000-000-0000" not in _last_body(_use_in_memory_sender)


async def test_change_branch_noop_with_single_branch(client, db_session, demo_tenant, _use_in_memory_sender):
    await _post_webhook(client, _message_value(_text("hi")))
    await _post_webhook(client, _message_value(_button_reply("button:change_branch")))

    assert "only one branch" in _last_body(_use_in_memory_sender).lower()
    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.WELCOME


async def test_change_branch_reprompts_with_multiple_branches(client, db_session, demo_tenant, _use_in_memory_sender):
    restaurant = demo_tenant["restaurant"]
    branch2 = Branch(restaurant_id=restaurant.id, name="Downtown", status=BranchStatus.OPEN)
    db_session.add(branch2)
    await db_session.commit()

    await _post_webhook(client, _message_value(_text("hi")))  # multi-branch -> asks up front
    await _post_webhook(client, _message_value(_list_reply(f"branch:{demo_tenant['branch'].id}")))
    await _post_webhook(client, _message_value(_button_reply("button:change_branch")))

    assert "Select a branch" in _last_body(_use_in_memory_sender)
    state = (await db_session.execute(select(ConversationState))).scalar_one()
    assert state.current_step == ConversationStep.SELECT_BRANCH
    assert "branch_id" not in state.context
