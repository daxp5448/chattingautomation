"""Loads every `app/niche_seeds/*.py` module's `TEMPLATE` dict into the `niche_templates`
table -- the step between "a niche's content exists in code" and "it shows up in Super
Admin's Add Business niche picker" (GET /niche-templates,
app/api/v1/routers/niche_templates.py) and is selectable via `RestaurantCreate.niche_code`
(app/api/v1/routers/restaurants.py::create_restaurant).

Auto-discovers niche modules by walking the app.niche_seeds package rather than hardcoding
an import list, so adding a new niche module there never requires touching this file too.

Upserts by `code`: a never-customized row is updated in place (a template is meant to
track its source file -- see app/models/flow_definition.py's docstring: a *business*'s own
FlowDefinition is an independent copy made at provisioning time, so re-syncing a template
afterward never touches any business that already provisioned from it). A row a Super
Admin has PATCHed (`NicheTemplate.is_customized=True`, set by
app/api/v1/routers/niche_templates.py) is skipped entirely on re-sync instead -- without
this, running the seed script again (a normal, repeatable deploy step, not a one-time
bootstrap) would silently revert any admin edit back to the code-defined defaults. Not run
automatically at app startup (deliberately -- app/tests/conftest.py's autouse
`_fresh_schema` fixture drops/recreates the DB per test, and several test files construct
their own NicheTemplate rows directly with the same `code`s used here; auto-syncing on
every app boot risks colliding with that if the test transport ever starts triggering
FastAPI lifespan events). Run explicitly instead, same operational shape as `alembic
upgrade head`: `python -m app.scripts.seed_niche_templates`.
"""

import importlib
import pkgutil

from sqlalchemy import select

from app.models.enums import EngagementType
from app.models.niche_template import NicheTemplate
from app.niche_seeds import __name__ as _niche_seeds_package_name
from app.niche_seeds import __path__ as _niche_seeds_package_path

_TEMPLATE_COLUMNS = (
    "name", "action_type", "icon", "welcome_message", "welcome_banner_image",
    "welcome_buttons", "default_catalog", "default_flow_steps", "terminology", "default_modules",
    "default_personality",
)


def discover_templates() -> list[dict]:
    templates = []
    for module_info in pkgutil.iter_modules(_niche_seeds_package_path):
        module = importlib.import_module(f"{_niche_seeds_package_name}.{module_info.name}")
        template = getattr(module, "TEMPLATE", None)
        if template is not None:
            templates.append(template)
    return templates


async def sync_niche_templates(session) -> list[str]:
    """Returns the list of niche codes that were created or updated (a customized row is
    left untouched and NOT included in this list, since nothing about it changed)."""
    synced = []
    for template in discover_templates():
        result = await session.execute(select(NicheTemplate).where(NicheTemplate.code == template["code"]))
        row = result.scalar_one_or_none()
        if row is not None and row.is_customized:
            continue
        if row is None:
            row = NicheTemplate(code=template["code"])
            session.add(row)
        for column in _TEMPLATE_COLUMNS:
            value = template[column]
            if column == "action_type":
                value = EngagementType(value)
            setattr(row, column, value)
        synced.append(template["code"])
    await session.commit()
    return synced
