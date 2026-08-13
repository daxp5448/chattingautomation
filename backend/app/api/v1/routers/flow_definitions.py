"""API surface for a business's own FlowDefinition: the entry step's home-screen buttons
(title/icon/order/visible/destination, unchanged since Phase 1), and -- as of Phase 2
Item 3, the Drag & Drop Flow Builder -- full step-graph replacement via PUT /steps.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.flow_definition_repository import FlowDefinitionRepository
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.schemas.flow_definition import (
    FlowDefinitionRead,
    FlowStepsUpdate,
    HomeButtonInput,
    HomeButtonsRead,
    HomeButtonsUpdate,
)
from app.schemas.message_catalog import MessageEntry, MessageTextUpdate
from app.services import message_catalog
from app.services.flow_shape_validation import FlowShapeError, validate_entry_step, validate_flow_graph, validate_home_buttons

router = APIRouter(prefix="/restaurants/{restaurant_id}/flow", tags=["flow-definitions"])

# Editing a business's own flow is configuration territory, same bar as menu.py/
# bot_config.py -- cashier/kitchen accounts don't touch it.
_MANAGE_FLOW = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _extract_home_buttons(entry_step: dict) -> list[dict]:
    routes = entry_step.get("routes") or {}
    next_fallback = entry_step.get("next")
    buttons = []
    for option in entry_step.get("static_options") or []:
        option_id = option["id"]
        buttons.append({
            "id": option_id,
            "title": option.get("title", ""),
            "icon": option.get("icon"),
            "visible": option.get("visible", True),
            # Exact-match route first, else the step's plain `next` fallback -- mirrors
            # _resolve_next's own priority (generic_flow_engine.py) minus its wildcard-
            # suffix case, which validate_home_buttons forbids new button ids from
            # opting into anyway, so it's not reachable through this endpoint going
            # forward (an old, pre-existing wildcard route, if one ever exists, simply
            # won't round-trip perfectly through this reader -- not a concern this pass).
            "destination_step_id": routes.get(option_id, next_fallback),
        })
    return buttons


def _apply_home_buttons(entry_step: dict, buttons: list[HomeButtonInput]) -> dict:
    """Returns a NEW entry-step dict with the button-related keys replaced -- never
    mutates `entry_step` in place. `FlowDefinition.steps` is a plain (non-Mutable-wrapped)
    JSON column; the caller must assign a genuinely new list/dict back to `flow.steps` for
    SQLAlchemy's dirty-tracking to see the change at all (the identical class of bug found
    and fixed for GenericConversationState.context earlier in this project -- see that
    model's docstring).
    """
    old_option_ids = {opt["id"] for opt in (entry_step.get("static_options") or [])}
    routes = {k: v for k, v in (entry_step.get("routes") or {}).items() if k not in old_option_ids}
    for button in buttons:
        routes[button.id] = button.destination_step_id

    new_step = {**entry_step}
    new_step["static_options"] = [
        {"id": b.id, "title": b.title, "icon": b.icon, "visible": b.visible} for b in buttons
    ]
    new_step["routes"] = routes
    return new_step


@router.get("", response_model=FlowDefinitionRead)
async def get_flow(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    flow = await FlowDefinitionRepository(db).get_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    return flow


@router.get("/home-buttons", response_model=HomeButtonsRead)
async def get_home_buttons(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    flow = await FlowDefinitionRepository(db).get_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    try:
        entry_step = validate_entry_step(flow.steps, flow.entry_step_id)
    except FlowShapeError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"entry_step_id": flow.entry_step_id, "buttons": _extract_home_buttons(entry_step)}


@router.patch("/home-buttons", response_model=HomeButtonsRead)
async def update_home_buttons(
    restaurant_id: uuid.UUID, payload: HomeButtonsUpdate, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FlowDefinitionRepository(db)
    flow = await repo.get_for_update_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")

    try:
        entry_step = validate_entry_step(flow.steps, flow.entry_step_id)
        existing_step_ids = {s["step_id"] for s in flow.steps}
        validate_home_buttons([b.model_dump() for b in payload.buttons], existing_step_ids)
    except FlowShapeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_entry_step = _apply_home_buttons(entry_step, payload.buttons)
    # Scoped strictly to the entry step -- every other step in the flow is carried over by
    # object reference, untouched. A genuinely new list (not the same object mutated in
    # place) is required for the plain JSON column to persist the change -- see
    # _apply_home_buttons's docstring.
    flow.steps = [new_entry_step if s.get("step_id") == flow.entry_step_id else s for s in flow.steps]
    await repo.commit()
    return {"entry_step_id": flow.entry_step_id, "buttons": _extract_home_buttons(new_entry_step)}


@router.get("/steps/{step_id}/buttons", response_model=HomeButtonsRead)
async def get_step_buttons(restaurant_id: uuid.UUID, step_id: str, db: DbSession, user: CurrentUser):
    """The Bot Preview side-by-side editor's per-node button editor -- a generalization
    of GET /home-buttons to any step_id, not just the entry step. `_extract_home_buttons`
    was already step-shape-generic (nothing in it assumes "entry step" specifically); the
    entry-step-only restriction lived entirely in the two endpoints, not the helper."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    flow = await FlowDefinitionRepository(db).get_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    step = next((s for s in flow.steps if s.get("step_id") == step_id), None)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No step '{step_id}' in this flow")
    return {"entry_step_id": step_id, "buttons": _extract_home_buttons(step)}


@router.patch("/steps/{step_id}/buttons", response_model=HomeButtonsRead)
async def update_step_buttons(
    restaurant_id: uuid.UUID, step_id: str, payload: HomeButtonsUpdate, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FlowDefinitionRepository(db)
    flow = await repo.get_for_update_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    step = next((s for s in flow.steps if s.get("step_id") == step_id), None)
    if step is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No step '{step_id}' in this flow")

    try:
        existing_step_ids = {s["step_id"] for s in flow.steps}
        validate_home_buttons([b.model_dump() for b in payload.buttons], existing_step_ids)
    except FlowShapeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    new_step = _apply_home_buttons(step, payload.buttons)
    flow.steps = [new_step if s.get("step_id") == step_id else s for s in flow.steps]
    await repo.commit()
    return {"entry_step_id": step_id, "buttons": _extract_home_buttons(new_step)}


async def _niche_default_messages(db: DbSession, niche_code: str) -> dict[str, str]:
    """step_id -> the owning NicheTemplate's CURRENT text for that step, used to flag
    which of a business's own messages are customized vs. still using the niche
    default, and as the restore target below. Empty dict if the niche template was
    deleted or never existed (a business's flow always keeps working independently --
    see app/services/niche_provisioning.py's docstring)."""
    template = await NicheTemplateRepository(db).get_by_code(niche_code)
    if template is None:
        return {}
    return {e["step_id"]: e["text"] for e in message_catalog.extract_messages(niche_code, template.default_flow_steps)}


@router.get("/messages", response_model=list[MessageEntry])
async def list_flow_messages(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    """The Message Management screen's data source for one business's own live flow:
    every text-bearing step, flattened to a searchable {message_key, text} catalog, each
    flagged against the owning niche template's current default so Business/Super Admin
    can see at a glance what's been customized (mirrors bot-builder/page.tsx's existing
    "Customized" vs "Using default" pattern for the legacy engine)."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    flow = await FlowDefinitionRepository(db).get_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    defaults = await _niche_default_messages(db, flow.niche_code)
    entries = message_catalog.extract_messages(flow.niche_code, flow.steps)
    for entry in entries:
        default_text = defaults.get(entry["step_id"])
        entry["default_text"] = default_text
        entry["is_customized"] = default_text is not None and entry["text"] != default_text
    return entries


@router.patch("/messages/{step_id}", response_model=MessageEntry)
async def update_flow_message(
    restaurant_id: uuid.UUID, step_id: str, payload: MessageTextUpdate, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FlowDefinitionRepository(db)
    flow = await repo.get_for_update_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    try:
        flow.steps = message_catalog.update_message_text(flow.steps, step_id, payload.text)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No message step '{step_id}' in this flow") from exc
    await repo.commit()
    defaults = await _niche_default_messages(db, flow.niche_code)
    entries = message_catalog.extract_messages(flow.niche_code, flow.steps)
    entry = next(e for e in entries if e["step_id"] == step_id)
    default_text = defaults.get(step_id)
    entry["default_text"] = default_text
    entry["is_customized"] = default_text is not None and entry["text"] != default_text
    return entry


@router.post("/messages/{step_id}/restore-default", response_model=MessageEntry)
async def restore_flow_message_default(
    restaurant_id: uuid.UUID, step_id: str, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    """Restores this business's own message text to the owning niche template's CURRENT
    default -- not the original seed-file value (that's the niche-template-level
    restore, see niche_templates.py), since a business is meant to track its niche's
    evolving defaults unless it deliberately opts out by customizing."""
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FlowDefinitionRepository(db)
    flow = await repo.get_for_update_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")
    defaults = await _niche_default_messages(db, flow.niche_code)
    if step_id not in defaults:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No niche default available for '{step_id}'")
    try:
        flow.steps = message_catalog.update_message_text(flow.steps, step_id, defaults[step_id])
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No message step '{step_id}' in this flow") from exc
    await repo.commit()
    entries = message_catalog.extract_messages(flow.niche_code, flow.steps)
    entry = next(e for e in entries if e["step_id"] == step_id)
    entry["default_text"] = defaults[step_id]
    entry["is_customized"] = False
    return entry


@router.put("/steps", response_model=FlowDefinitionRead)
async def update_flow_steps(
    restaurant_id: uuid.UUID, payload: FlowStepsUpdate, db: DbSession, user: User = Depends(_MANAGE_FLOW)
):
    """Full step-graph replacement -- the Drag & Drop Flow Builder's save action. Unlike
    /home-buttons (scoped strictly to the entry step), this replaces the whole `steps`
    list, so it's the builder UI's job to have already round-tripped every step the
    business didn't intend to change; this endpoint only validates shape, it doesn't
    diff against what was there before.
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = FlowDefinitionRepository(db)
    flow = await repo.get_for_update_by_restaurant(tenant_id)
    if flow is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This business has no flow configured yet")

    try:
        validate_flow_graph(payload.steps)
        validate_entry_step(payload.steps, payload.entry_step_id)
    except FlowShapeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    flow.steps = payload.steps
    flow.entry_step_id = payload.entry_step_id
    flow.ui_layout = payload.ui_layout
    await repo.commit()
    return flow
