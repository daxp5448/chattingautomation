"""Shared flow-shape validation, reused by `NicheTemplate.default_flow_steps` validation
(app/api/v1/routers/niche_templates.py), the generic engine's home-buttons endpoint
(app/api/v1/routers/flow_definitions.py), and -- as of Phase 2 Item 3, the Drag & Drop
Flow Builder -- full flow-graph validation (`validate_flow_graph` below), which this
file's own prior docstring named as this feature's job.
"""

from app.models.enums import FlowStepType

MAX_BUTTON_TITLE_LENGTH = 20  # WhatsApp truncates quick-reply button titles here -- see
# generic_flow_engine.py::_send_options's own defensive `o["title"][:20]` and
# app/tests/test_niche_retail.py's title-length test, which exists for this exact reason.

# Mirrors generic_flow_engine.py's _AUTO_ADVANCE_TYPES -- steps that run without waiting
# for customer input. Kept as a separate constant (not imported from the engine module)
# to avoid a schema-validation module depending on the runtime engine; if the engine's
# set ever changes, this one must be updated alongside it.
_AUTO_ADVANCE_TYPES = {
    FlowStepType.CONDITION.value,
    FlowStepType.DELAY.value,
    FlowStepType.API_CALL.value,
    FlowStepType.AI_RESPONSE.value,
}
# A per-step sanity ceiling, not a substitute for generic_flow_engine.py's runtime
# total-chain budget (several small delays can still exceed that budget at runtime) --
# this only catches an obviously-too-large single step early, at save time.
MAX_DELAY_SECONDS_PER_STEP = 5.0


class FlowShapeError(ValueError):
    """A rejected flow/button edit -- routers translate this into a 400, never a 500."""


def validate_entry_step(steps: list[dict], entry_step_id: str) -> dict:
    """Returns the entry step dict if valid, otherwise raises FlowShapeError."""
    step = next((s for s in steps if s.get("step_id") == entry_step_id), None)
    if step is None:
        raise FlowShapeError(f"entry_step_id '{entry_step_id}' does not match any step_id in steps")
    if step.get("type") != FlowStepType.MENU_SELECT.value:
        raise FlowShapeError(
            f"entry step '{entry_step_id}' must be type '{FlowStepType.MENU_SELECT.value}' to carry buttons, got '{step.get('type')}'"
        )
    return step


def validate_home_buttons(buttons: list[dict], existing_step_ids: set[str]) -> None:
    if not buttons:
        raise FlowShapeError("at least one button is required")

    seen_ids = set()
    for button in buttons:
        button_id = button.get("id", "")
        if not button_id:
            raise FlowShapeError("every button needs a non-empty id")
        if button_id in seen_ids:
            raise FlowShapeError(f"duplicate button id '{button_id}'")
        seen_ids.add(button_id)

        if button_id.endswith("*"):
            # _resolve_next's routes matching treats a trailing "*" as a wildcard-prefix
            # route (generic_flow_engine.py's _resolve_next) -- a button id ending in "*"
            # would accidentally opt into that instead of being treated as a literal id.
            raise FlowShapeError(f"button id '{button_id}' must not end with '*' (reserved for wildcard routing)")

        title = button.get("title", "")
        if not title:
            raise FlowShapeError(f"button '{button_id}' needs a non-empty title")
        if len(title) > MAX_BUTTON_TITLE_LENGTH:
            raise FlowShapeError(
                f"button '{button_id}' title is {len(title)} chars, exceeds the {MAX_BUTTON_TITLE_LENGTH}-char "
                "WhatsApp quick-reply limit"
            )

        destination = button.get("destination_step_id")
        if not destination:
            raise FlowShapeError(f"button '{button_id}' needs a destination_step_id")
        if destination not in existing_step_ids:
            raise FlowShapeError(f"button '{button_id}' destination_step_id '{destination}' does not match any step_id in the flow")


def _auto_advance_targets(step: dict) -> list[str]:
    step_type = step.get("type")
    if step_type == FlowStepType.CONDITION.value:
        return [t for t in (step.get("then_step"), step.get("else_step")) if t]
    if step_type in (FlowStepType.DELAY.value, FlowStepType.API_CALL.value, FlowStepType.AI_RESPONSE.value):
        next_id = step.get("next")
        return [next_id] if next_id else []
    return []


def _check_no_auto_advance_cycle(start_step_id: str, steps_by_id: dict[str, dict]) -> None:
    """DFS from an auto-advancing step, following only auto-advancing edges (a
    CONDITION's then_step/else_step, or the next of a DELAY/API_CALL/AI_RESPONSE).
    Raises if any path revisits a step before reaching an interactive/terminal step or a
    dead end -- such a flow could loop forever at runtime with the customer never
    getting a reply, which generic_flow_engine.py's own hop-cap would otherwise only
    catch live, mid-conversation, for a real customer. Both branches of a condition are
    checked independently so a cycle hidden behind only one branch is still caught.
    """

    def dfs(step_id: str, path: set[str]) -> None:
        step = steps_by_id.get(step_id)
        if step is None or step.get("type") not in _AUTO_ADVANCE_TYPES:
            return
        if step_id in path:
            raise FlowShapeError(
                f"auto-advance chain starting at '{start_step_id}' cycles back through '{step_id}' "
                "without ever reaching an interactive or terminal step"
            )
        next_path = path | {step_id}
        for target_id in _auto_advance_targets(step):
            dfs(target_id, next_path)

    dfs(start_step_id, set())


def validate_flow_graph(steps: list[dict]) -> None:
    """Full flow-graph validation for the Drag & Drop Flow Builder (app/api/v1/routers/
    flow_definitions.py, app/api/v1/routers/niche_templates.py): every routing field
    resolves to a real step_id, and no auto-advancing chain can loop forever. Does NOT
    validate that an API_CALL step's endpoint_id refers to a real, active ApiEndpoint --
    that needs a DB lookup, done by the router at save time, not this pure function.
    """
    step_ids = {s.get("step_id") for s in steps}
    steps_by_id = {s.get("step_id"): s for s in steps}

    for step in steps:
        step_id = step.get("step_id", "<missing step_id>")
        step_type = step.get("type")

        for field in ("next", "back_target"):
            target = step.get(field)
            if target and target not in step_ids:
                raise FlowShapeError(f"step '{step_id}': {field} '{target}' does not match any step_id in the flow")

        for target in (step.get("routes") or {}).values():
            if target not in step_ids:
                raise FlowShapeError(f"step '{step_id}': routes target '{target}' does not match any step_id in the flow")

        if step_type == FlowStepType.CONDITION.value:
            then_step, else_step = step.get("then_step"), step.get("else_step")
            if not then_step or not else_step:
                raise FlowShapeError(f"step '{step_id}': a condition step needs both then_step and else_step")
            if then_step not in step_ids:
                raise FlowShapeError(f"step '{step_id}': then_step '{then_step}' does not match any step_id in the flow")
            if else_step not in step_ids:
                raise FlowShapeError(f"step '{step_id}': else_step '{else_step}' does not match any step_id in the flow")

        if step_type == FlowStepType.DELAY.value:
            delay_seconds = step.get("delay_seconds", 0)
            if not isinstance(delay_seconds, (int, float)) or isinstance(delay_seconds, bool) or delay_seconds < 0:
                raise FlowShapeError(f"step '{step_id}': delay_seconds must be a non-negative number")
            if delay_seconds > MAX_DELAY_SECONDS_PER_STEP:
                raise FlowShapeError(
                    f"step '{step_id}': delay_seconds ({delay_seconds}) exceeds the {MAX_DELAY_SECONDS_PER_STEP}s cap"
                )

        if step_type == FlowStepType.API_CALL.value and not step.get("endpoint_id"):
            raise FlowShapeError(f"step '{step_id}': an api_call step needs an endpoint_id")

    for step in steps:
        if step.get("type") in _AUTO_ADVANCE_TYPES:
            _check_no_auto_advance_cycle(step.get("step_id"), steps_by_id)
