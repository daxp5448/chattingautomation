"""Presents a niche template's or a business's own flow steps as a flat, searchable
"message catalog" (step_id -> customer-visible text) for the Super Admin / Business
Admin Message Management screens -- see app/api/v1/routers/niche_templates.py and
app/api/v1/routers/flow_definitions.py for the endpoints that use this.

Deliberately reuses NicheTemplate.default_flow_steps / FlowDefinition.steps as the ONLY
storage for message text -- there is no separate message-override table. A "message" IS
a flow step's prompt/message field; this module only ever extracts or replaces that one
field, leaving the step's shape (next/routes/back_target/buttons/etc) completely
untouched, so editing a message here can never desync from the flow graph the same steps
power, and a niche template's existing is_customized/seed-sync protection (see
app/services/niche_template_sync.py) covers message edits for free -- no new persistence
layer, no new seed-overwrite risk.
"""

from typing import Any

# Step types with no directly-rendered customer-visible prompt of their own --
# auto-advance-only types (see generic_flow_engine.py's module docstring for what each
# does). Excluded from the message catalog entirely.
_NO_TEXT_STEP_TYPES = {"condition", "delay", "api_call", "ai_response"}

# Which field on the step dict actually holds the rendered text, per type -- everything
# not listed here (and not in _NO_TEXT_STEP_TYPES) uses "prompt".
_TEXT_FIELD_BY_TYPE = {"human_handoff": "message"}


def message_key(niche_code: str, step_id: str) -> str:
    return f"{niche_code}.{step_id}"


def text_field_for(step_type: str | None) -> str:
    return _TEXT_FIELD_BY_TYPE.get(step_type, "prompt")


def extract_messages(niche_code: str, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per text-bearing step, in flow order."""
    entries = []
    for step in steps:
        step_type = step.get("type")
        if step_type in _NO_TEXT_STEP_TYPES:
            continue
        field = text_field_for(step_type)
        entries.append({
            "step_id": step["step_id"],
            "field": field,
            "message_key": message_key(niche_code, step["step_id"]),
            "text": step.get(field) or "",
            "step_type": step_type,
        })
    return entries


def update_message_text(steps: list[dict[str, Any]], step_id: str, text: str) -> list[dict[str, Any]]:
    """Returns a NEW steps list with the one matching step's text field replaced --
    never mutates the input in place. Both FlowDefinition.steps and
    NicheTemplate.default_flow_steps are plain (non-Mutable-wrapped) JSON columns, so the
    caller must assign a genuinely new list back to the model attribute for SQLAlchemy's
    dirty-tracking to persist the change -- the same class of bug already fixed for
    GenericConversationState.context (see that model's docstring).

    Raises KeyError if step_id doesn't match any step in the list.
    """
    if not any(s.get("step_id") == step_id for s in steps):
        raise KeyError(step_id)
    new_steps = []
    for step in steps:
        if step.get("step_id") != step_id:
            new_steps.append(step)
            continue
        field = text_field_for(step.get("type"))
        new_steps.append({**step, field: text})
    return new_steps
