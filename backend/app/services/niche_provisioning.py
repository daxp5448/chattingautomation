"""Copies a NicheTemplate's default catalog + flow into a brand-new business's own rows
-- called once, at business-creation time (see
app/api/v1/routers/restaurants.py::create_restaurant). Editing a template afterward never
touches a business that already provisioned from it; editing the business's own copy is
a normal admin-panel edit from that point on, same as any other tenant data.
"""

import uuid

from app.models.catalog import CatalogCategory, CatalogItem
from app.models.flow_definition import FlowDefinition
from app.models.niche_template import NicheTemplate
from app.models.restaurant import Restaurant


async def provision_from_template(session, restaurant: Restaurant, template: NicheTemplate) -> None:
    restaurant.uses_generic_engine = True
    restaurant.niche_type = template.code
    restaurant.cover_image_url = restaurant.cover_image_url or template.welcome_banner_image
    restaurant.logo_url = restaurant.logo_url or template.welcome_banner_image
    # template.default_modules (e.g. {"staff_selection": False} for a niche like
    # Automobile that wants a module off by default) must land on the business's own
    # `modules` dict, not just exist in the template -- generic_flow_engine.py's
    # `_Engine._advance` reads `restaurant.loyalty_settings["modules"][flag]` with a
    # missing-key default of True, so a module a template wants OFF by default would
    # silently render ON for every real business provisioned from it without this.
    # Builds a genuinely new dict (never mutates restaurant.loyalty_settings in place)
    # since it's a plain JSON column, not a MutableDict -- an in-place update here would
    # risk the same silently-dropped-from-the-UPDATE class of bug fixed elsewhere in
    # this platform (see app/models/generic_conversation_state.py's `context` column).
    if template.default_modules:
        # Template defaults are the BASE, not the final word -- a business that already
        # had an explicit modules choice before provisioning (e.g. an admin pre-set it,
        # or a caller passed it at Restaurant-construction time) must win over the
        # template's default, not get silently overwritten by it.
        restaurant.loyalty_settings = {
            **restaurant.loyalty_settings,
            "modules": {**template.default_modules, **restaurant.loyalty_settings.get("modules", {})},
        }

    for cat_order, category_data in enumerate(template.default_catalog):
        category = CatalogCategory(
            restaurant_id=restaurant.id,
            name=category_data["name"],
            display_order=cat_order,
            visible=True,
            image_url=category_data.get("icon_image"),
        )
        session.add(category)
        await session.flush()

        for item_order, item_data in enumerate(category_data.get("items", [])):
            session.add(
                CatalogItem(
                    restaurant_id=restaurant.id,
                    category_id=category.id,
                    name=item_data["name"],
                    description=item_data.get("description"),
                    images=item_data.get("images", []),
                    price=item_data.get("price"),
                    price_type=item_data.get("price_type", "fixed"),
                    display_order=item_order,
                    attributes=item_data.get("attributes", {}),
                )
            )

    flow = FlowDefinition(
        restaurant_id=restaurant.id,
        niche_code=template.code,
        action_type=template.action_type,
        entry_step_id=(template.default_flow_steps[0]["step_id"] if template.default_flow_steps else "welcome"),
        steps=template.default_flow_steps,
        # Copied alongside steps so a newly-provisioned business's flow builder opens to
        # the template author's own node layout, not an unlaid-out graph -- see
        # FlowDefinition.ui_layout's docstring.
        ui_layout=template.default_ui_layout,
    )
    session.add(flow)
    await session.flush()
