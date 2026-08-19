"""Flow Acceptance Matrix (Super Admin audit requirement) applied exhaustively across
all 12 niche seed templates -- structural validation of every niche's
`default_flow_steps` graph: no dead-end buttons, no routes/next/condition targets
pointing at a step that doesn't exist, no step unreachable from the entry step, no two
buttons on the same step doing the same thing (duplicate id or duplicate visible title),
every catalog category/item has real image coverage, and no restaurant-specific
terminology leaking into a non-restaurant niche's copy.

Reuses discover_templates() (app/services/niche_template_sync.py) -- the exact same
niche-seed-module registry the real seed script/Demo Bot provisioning use -- rather than
hardcoding a second list of 12 niche codes here.
"""

from app.services.niche_template_sync import discover_templates

_RESTAURANT_ONLY_WORDS = {"menu", "dish", "food", "order food", "view menu"}


def _resolve_next(step: dict, option_id: str) -> str | None:
    """Mirrors generic_flow_engine.py::_Engine._resolve_next's exact matching order
    (exact route match, then a routes key ending '*' as a prefix match, then `next`) --
    a button is only a genuine dead end if none of these three resolve to anything."""
    routes = step.get("routes") or {}
    if option_id in routes:
        return routes[option_id]
    for prefix, target in routes.items():
        if prefix.endswith("*") and option_id.startswith(prefix[:-1]):
            return target
    return step.get("next")


def _all_referenced_targets(step: dict) -> list[tuple[str, str]]:
    """(field_name, target_step_id) for every field on this step that names another
    step_id -- back_target included (validated for existing, not for reachability: see
    test_every_step_reachable_from_entry's exclusion of it from the BFS edge set)."""
    refs = []
    for field in ("next", "then_step", "else_step", "fallback_next", "back_target"):
        target = step.get(field)
        if target:
            refs.append((field, target))
    for reply_key, target in (step.get("routes") or {}).items():
        refs.append((f"routes[{reply_key}]", target))
    return refs


def _forward_edges(step: dict) -> list[str]:
    """Edges used for entry-reachability -- forward-progressing only, excludes
    back_target (backward navigation would trivially make every step "reachable" via a
    round trip through whatever step has a Back button to it, masking a real orphan)."""
    targets = []
    for field in ("next", "then_step", "else_step", "fallback_next"):
        target = step.get(field)
        if target:
            targets.append(target)
    targets.extend((step.get("routes") or {}).values())
    return targets


def _iter_niches():
    templates = discover_templates()
    assert len(templates) == 12, f"Expected all 12 niches discoverable, found {len(templates)}: {sorted(t['code'] for t in templates)}"
    return templates


def test_no_duplicate_step_ids():
    for template in _iter_niches():
        steps = template["default_flow_steps"]
        step_ids = [s["step_id"] for s in steps]
        duplicates = {sid for sid in step_ids if step_ids.count(sid) > 1}
        assert not duplicates, f"{template['code']}: duplicate step_id(s) {duplicates}"


def test_every_referenced_step_target_exists():
    """No routes/next/condition/back_target pointing at a step that isn't in this flow --
    'no buttons pointing to the wrong step'."""
    for template in _iter_niches():
        steps = template["default_flow_steps"]
        step_ids = {s["step_id"] for s in steps}
        for step in steps:
            for field, target in _all_referenced_targets(step):
                assert target in step_ids, (
                    f"{template['code']}/{step['step_id']}: {field} points to unknown step '{target}'"
                )


def test_every_step_reachable_from_entry():
    """No orphaned steps -- everything is reachable by forward navigation from the entry
    step (default_flow_steps[0], matching niche_provisioning.py's own entry_step_id
    derivation)."""
    for template in _iter_niches():
        steps = template["default_flow_steps"]
        steps_by_id = {s["step_id"]: s for s in steps}
        entry = steps[0]["step_id"]

        seen = {entry}
        frontier = [entry]
        while frontier:
            current = frontier.pop()
            for target in _forward_edges(steps_by_id[current]):
                if target not in seen and target in steps_by_id:
                    seen.add(target)
                    frontier.append(target)

        unreachable = set(steps_by_id) - seen
        assert not unreachable, f"{template['code']}: step(s) unreachable from entry '{entry}': {unreachable}"


def test_no_dead_end_buttons():
    """Every button (static_option) on a menu_select/confirm_action/quantity_input step
    resolves to a real next step, via the engine's own routing precedence -- 'no
    dead-end buttons'."""
    for template in _iter_niches():
        for step in template["default_flow_steps"]:
            if step["type"] not in ("menu_select", "confirm_action", "quantity_input"):
                continue
            for option in step.get("static_options") or []:
                resolved = _resolve_next(step, option["id"])
                assert resolved is not None, (
                    f"{template['code']}/{step['step_id']}: button '{option['id']}' ({option.get('title')}) "
                    "has no route and no fallback `next` -- dead end"
                )


def test_no_duplicate_buttons_within_a_step():
    for template in _iter_niches():
        for step in template["default_flow_steps"]:
            options = step.get("static_options") or []
            ids = [o["id"] for o in options]
            titles = [o["title"] for o in options]
            dup_ids = {i for i in ids if ids.count(i) > 1}
            dup_titles = {t for t in titles if titles.count(t) > 1}
            assert not dup_ids, f"{template['code']}/{step['step_id']}: duplicate button id(s) {dup_ids}"
            assert not dup_titles, f"{template['code']}/{step['step_id']}: duplicate button title(s) {dup_titles}"


def test_every_category_and_item_has_image_coverage():
    """'Every niche needs realistic categories and records' + 'no niche left with an
    empty image section' -- every seeded category has an icon and every seeded item has
    at least one image."""
    for template in _iter_niches():
        for category in template["default_catalog"]:
            assert category.get("icon_image"), f"{template['code']}: category '{category['name']}' has no icon_image"
            for item in category.get("items", []):
                assert item.get("images"), (
                    f"{template['code']}/{category['name']}: item '{item['name']}' has no images"
                )


def test_no_restaurant_terminology_leaking_into_other_niches():
    for template in _iter_niches():
        if template["code"] == "restaurant":
            continue
        terminology = template.get("terminology") or {}
        for key in ("catalog_label", "category_label", "item_label"):
            value = (terminology.get(key) or "").strip().lower()
            assert value not in _RESTAURANT_ONLY_WORDS, (
                f"{template['code']}: terminology.{key}='{terminology.get(key)}' looks like leftover restaurant copy"
            )


def test_every_niche_has_a_human_handoff_step():
    """'Test human handoff' -- every niche's flow includes a real escape hatch to a
    person, not just automation with no way out."""
    for template in _iter_niches():
        types = {s["type"] for s in template["default_flow_steps"]}
        assert "human_handoff" in types, f"{template['code']}: no human_handoff step anywhere in the flow"


def test_every_non_welcome_step_has_a_back_target():
    """'Back' must go somewhere real everywhere except the entry step itself (which has
    nothing to go back to) and terminal/human_handoff steps -- matches
    FlowDefinition.steps' own documented contract ('back_target: ... None only for the
    welcome step' + 'terminal: ... no back-navigation is offered after it')."""
    for template in _iter_niches():
        steps = template["default_flow_steps"]
        entry = steps[0]["step_id"]
        for step in steps:
            if step["step_id"] == entry:
                continue
            if step["type"] == "human_handoff" or step.get("terminal"):
                continue  # no back navigation offered after handoff or a flow's final step
            assert step.get("back_target"), f"{template['code']}/{step['step_id']}: no back_target set"
