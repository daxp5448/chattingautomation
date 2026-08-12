import re
from typing import Any

_VARIABLE_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def render_template(template: str, context: dict[str, Any]) -> str:
    """Substitutes {{variable}} tokens in a bot_messages template with values from context.

    Unknown variables are replaced with an empty string rather than left as literal
    `{{...}}` text, since that text is sent directly to a customer over WhatsApp.
    """

    def _replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1))
        return "" if value is None else str(value)

    return _VARIABLE_PATTERN.sub(_replace, template)
