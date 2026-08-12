"""Celery task for background WhatsApp message delivery.

NOTE: `send_whatsapp_message` below is not currently invoked anywhere in the codebase.
The live outbound-send path is synchronous, with its own retry/backoff logic, in
`app/services/whatsapp_client.py` (`GraphAPIWhatsAppSender.send`) -- the flow engine
calls that directly since the customer is actively waiting on the webhook response.
This task is dormant infrastructure (no Celery worker wiring/caller currently exists
for it) and should not be mistaken for something actively running in production.
"""

from typing import Any

import httpx

from app.core.config import settings
from app.core.security import decrypt_secret
from app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    autoretry_for=(httpx.HTTPError,),
    retry_backoff=True,
    retry_backoff_max=60,
    max_retries=5,
)
def send_whatsapp_message(
    self, phone_number_id: str, access_token_encrypted: str, payload: dict[str, Any]
) -> None:
    """Background delivery for outbound WhatsApp messages that don't need to block the
    webhook response (e.g. staff/order-status notifications). The synchronous flow-engine
    reply path sends inline via GraphAPIWhatsAppSender instead, since the customer is
    actively waiting on that response.
    """
    access_token = decrypt_secret(access_token_encrypted)
    url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {access_token}"}
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
