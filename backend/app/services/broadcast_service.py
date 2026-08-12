"""Shared helpers for the Broadcast Module -- segment resolution, per-recipient
personalization-token resolution, and template-placeholder-count validation. Split out
from the router/task so both can call the same logic without duplicating it (the router
validates once at `start`; the task resolves per-recipient at send time).
"""

import re
import uuid

from app.models.customer import Customer
from app.models.whatsapp_template import WhatsAppTemplate

_PLACEHOLDER_PATTERN = re.compile(r"\{\{(\d+)\}\}")

# The only recognized per-recipient personalization token for this pass -- not a general
# templating language, matching "don't over-build past what's needed." Falls back to the
# customer's phone number if they have no name on file, same idiom notification_service.py
# already uses elsewhere (`customer.name or customer.phone`).
_CUSTOMER_NAME_TOKEN = "{{customer_name}}"


def count_template_placeholders(body_text: str) -> int:
    """The number of distinct {{N}} positional placeholders a template body expects --
    Meta requires this many variable values on every send. Uses the highest N found
    (not just the count of matches) so a body referencing {{1}} and {{3}} but not {{2}}
    is still measured correctly, though niche seed authors are expected to number
    sequentially with no gaps."""
    matches = _PLACEHOLDER_PATTERN.findall(body_text)
    if not matches:
        return 0
    return max(int(m) for m in matches)


def validate_variable_count(template: WhatsAppTemplate, variable_template: list[str]) -> None:
    expected = count_template_placeholders(template.body_text)
    if len(variable_template) != expected:
        raise ValueError(
            f"Template '{template.name}' expects {expected} variable value(s), got {len(variable_template)}"
        )


def resolve_variable_values(variable_template: list[str], customer: Customer) -> list[str]:
    return [customer.name or customer.phone if v == _CUSTOMER_NAME_TOKEN else v for v in variable_template]


async def enqueue_broadcast_send(campaign_id: uuid.UUID) -> None:
    """Dispatches the Celery send task for a campaign that just started (or just came
    due via the beat-task dispatcher) -- a thin, monkeypatchable seam, same shape as
    app/services/image_pipeline.py::enqueue_processing. Declared `async def` so tests can
    monkeypatch it to `await _send_broadcast_campaign(str(campaign_id))` directly instead,
    since no real Celery broker/worker runs in the test environment -- keeps everything on
    the caller's existing event loop rather than nesting a second one via asyncio.run().
    """
    from app.tasks.broadcast_sender import send_broadcast_campaign  # local import: avoids
    # a celery_app import at module load time for callers that never need Celery at all.

    send_broadcast_campaign.delay(str(campaign_id))
