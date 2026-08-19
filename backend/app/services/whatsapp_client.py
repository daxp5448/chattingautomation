import asyncio
import logging
from typing import Any, Protocol

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Total attempts (including the first) for a send before giving up. Only retried for
# transient failures -- 5xx, timeouts, and connect errors -- never for 4xx, which are
# permanent (bad payload/recipient/token) and would just fail again identically.
_MAX_SEND_ATTEMPTS = 3
_MAX_BACKOFF_SECONDS = 8.0


class OutboundMessage:
    """A message the flow engine wants sent to a customer, expressed as a Graph API payload."""

    def __init__(self, to: str, payload: dict[str, Any]):
        self.to = to
        self.payload = payload

    @classmethod
    def text(cls, to: str, body: str) -> "OutboundMessage":
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body[:4096]},
            },
        )

    @classmethod
    def interactive_buttons(
        cls, to: str, body: str, buttons: list[dict[str, str]]
    ) -> "OutboundMessage":
        # Meta allows a maximum of 3 quick-reply buttons per interactive message.
        limited = buttons[:3]
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body[:1024]},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b["id"], "title": b["title"][:20]}}
                            for b in limited
                        ]
                    },
                },
            },
        )

    @classmethod
    def interactive_list(
        cls,
        to: str,
        body: str,
        button_text: str,
        rows: list[dict[str, str]],
        section_title: str = "Options",
    ) -> "OutboundMessage":
        # Meta allows a maximum of 10 rows per interactive list message.
        limited = rows[:10]
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body[:1024]},
                    "action": {
                        "button": button_text[:20],
                        "sections": [
                            {
                                "title": section_title[:24],
                                "rows": [
                                    {
                                        "id": r["id"],
                                        "title": r["title"][:24],
                                        "description": r.get("description", "")[:72],
                                    }
                                    for r in limited
                                ],
                            }
                        ],
                    },
                },
            },
        )

    @classmethod
    def flow(
        cls, to: str, body: str, flow_id: str, flow_token: str, cta: str,
        screen: str, data: dict[str, Any] | None = None,
    ) -> "OutboundMessage":
        """Opens a native WhatsApp Flow (see app/services/whatsapp_flow_order_service.py
        and the approved "WhatsApp Flows for Ordering" plan) -- a multi-screen form inside
        WhatsApp, not a chat message. Shape verified directly against Meta's current docs
        (flow_message_version "3" is a fixed literal, not this platform's own API
        version). `flow_action="navigate"` with the first screen's data embedded here
        means the very first screen doesn't need a data_exchange round-trip -- only
        screen 2 onward calls the data-exchange webhook (see webhook.py's
        receive_flow_data_exchange).
        """
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "flow",
                    "body": {"text": body[:1024]},
                    "action": {
                        "name": "flow",
                        "parameters": {
                            "flow_message_version": "3",
                            "flow_token": flow_token,
                            "flow_id": flow_id,
                            "flow_cta": cta[:30],
                            "flow_action": "navigate",
                            "flow_action_payload": {"screen": screen, "data": data or {}},
                        },
                    },
                },
            },
        )

    @classmethod
    def template(cls, to: str, name: str, language: str, variable_values: list[str] | None = None) -> "OutboundMessage":
        """A Meta-approved Message Template send -- the only way to message a customer
        outside the 24-hour customer-service window (see app/services/
        whatsapp_template_client.py / app/models/whatsapp_template.py). `variable_values`
        are positional, filling the template body's {{1}}, {{2}}, ... placeholders in
        order -- omit for a template with no placeholders.
        """
        components = (
            [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variable_values]}]
            if variable_values
            else []
        )
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {"name": name, "language": {"code": language}, "components": components},
            },
        )

    @classmethod
    def document(cls, to: str, link: str, filename: str, caption: str = "") -> "OutboundMessage":
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "document",
                "document": {"link": link, "filename": filename, "caption": caption[:1024]},
            },
        )

    @classmethod
    def location(cls, to: str, latitude: float, longitude: float, name: str = "", address: str = "") -> "OutboundMessage":
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "location",
                "location": {
                    "latitude": latitude,
                    "longitude": longitude,
                    "name": name[:200],
                    "address": address[:200],
                },
            },
        )

    @classmethod
    def image(cls, to: str, link: str, caption: str = "") -> "OutboundMessage":
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "image",
                "image": {"link": link, "caption": caption[:1024]},
            },
        )

    @classmethod
    def product_list(
        cls,
        to: str,
        catalog_id: str,
        header: str,
        body: str,
        retailer_ids: list[str],
        section_title: str = "Designs",
    ) -> "OutboundMessage":
        """A real native WhatsApp "Multi-Product Message" -- the swipeable product-card
        carousel pulled from a connected Meta/Facebook Commerce Catalog, distinct from
        the sequential OutboundMessage.image fallback above (that fallback is what every
        restaurant without a catalog connected uses today; see
        app/services/generic_flow_engine.py::_render_jewellery_gallery). `retailer_ids`
        must already be synced into `catalog_id` (see
        app/services/meta_catalog_sync.py::sync_designs_to_catalog) -- Meta rejects any
        product_retailer_id it doesn't recognize in that catalog, so callers are
        responsible for filtering out designs with no meta_retailer_id first.

        Single-section only for now, capped at Meta's 10-items-per-section limit -- Meta
        also supports pagination across multiple sections up to 30 items total, but that
        isn't needed yet since this matches the existing page_size=10 gallery convention
        (see JewelleryDesignRepository.list_designs / _render_jewellery_gallery).
        """
        limited = retailer_ids[:10]
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "product_list",
                    "header": {"type": "text", "text": header[:60]},
                    "body": {"text": body[:1024]},
                    "action": {
                        "catalog_id": catalog_id,
                        "sections": [
                            {
                                "title": section_title[:24],
                                "product_items": [{"product_retailer_id": rid} for rid in limited],
                            }
                        ],
                    },
                },
            },
        )

    @classmethod
    def location_request(cls, to: str, body: str) -> "OutboundMessage":
        # Prompts a native "Send location" button in WhatsApp -- the customer taps it and
        # shares their live GPS location instead of typing an address by hand.
        return cls(
            to,
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "location_request_message",
                    "body": {"text": body[:1024]},
                    "action": {"name": "send_location"},
                },
            },
        )


class WhatsAppSender(Protocol):
    async def send(self, phone_number_id: str, access_token: str, message: OutboundMessage) -> None: ...


class GraphAPIWhatsAppSender:
    """Sends messages via the real Meta WhatsApp Cloud API.

    One instance of this class lives for the whole life of the process (every router
    module does `_sender = GraphAPIWhatsAppSender()` once at import time, never per-
    request) -- so self._client below is a genuinely SHARED, persistent httpx.AsyncClient,
    not a per-call one. Reusing it means every send after the first on a given worker
    reuses an already-open (keep-alive) TCP/TLS connection to graph.facebook.com instead
    of paying a fresh TCP handshake + TLS negotiation on every single message -- easily
    several hundred ms saved per send, and the dominant cost when several messages go out
    for the same customer in quick succession (e.g. an image + its options).
    """

    def __init__(self, api_version: str | None = None):
        self.api_version = api_version or settings.WHATSAPP_GRAPH_API_VERSION
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
        self._client = httpx.AsyncClient(timeout=timeout)

    async def send(self, phone_number_id: str, access_token: str, message: OutboundMessage) -> None:
        if not phone_number_id or not access_token:
            # Restaurant hasn't had real Meta credentials configured yet (expected while
            # onboarding, per Phase 1 scope). Skip the network call instead of sending a
            # malformed request -- inbound processing/state transitions still complete.
            logger.warning(
                "Skipping WhatsApp send: restaurant has no phone_number_id/access_token configured"
            )
            return
        url = f"https://graph.facebook.com/{self.api_version}/{phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}

        last_exc: Exception | None = None
        for attempt in range(_MAX_SEND_ATTEMPTS):
            try:
                response = await self._client.post(url, json=message.payload, headers=headers)
                response.raise_for_status()
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    # 4xx is permanent (bad payload/recipient/token) -- retrying won't help.
                    raise
                # 5xx is Meta explicitly telling us the request was NOT accepted -- safe
                # to retry, same as a connect failure below.
                last_exc = exc
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                # The TCP connection never opened (or never got a slot) -- Meta never saw
                # this request, so retrying cannot produce a duplicate send.
                last_exc = exc
            except (httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                # Deliberately NOT retried, unlike the connect-phase failures above: once
                # the request has been written (or is being written), Meta may already
                # have received and processed it -- we just never got the response back.
                # Retrying here is exactly the "duplicate outbound WhatsApp message" risk
                # flagged by the platform audit (a timeout does not mean the send failed).
                # Failing fast on the FIRST such timeout is safer than silently risking a
                # customer-visible duplicate message.
                logger.error(
                    "WhatsApp send timed out with an ambiguous outcome (request may have "
                    "reached Meta) -- not retrying to avoid a duplicate send: "
                    "phone_number_id=%s type=%s",
                    phone_number_id, message.payload.get("type"),
                )
                raise

            if attempt < _MAX_SEND_ATTEMPTS - 1:
                backoff = min(2**attempt, _MAX_BACKOFF_SECONDS)
                await asyncio.sleep(backoff)

        status_code = last_exc.response.status_code if isinstance(last_exc, httpx.HTTPStatusError) else None
        body = ""
        if isinstance(last_exc, httpx.HTTPStatusError):
            body = last_exc.response.text[:500]
        logger.error(
            "WhatsApp send failed after %d attempts: phone_number_id=%s type=%s status=%s body=%s",
            _MAX_SEND_ATTEMPTS,
            phone_number_id,
            message.payload.get("type"),
            status_code,
            body,
            exc_info=last_exc,
        )
        assert last_exc is not None
        raise last_exc


class InMemoryWhatsAppSender:
    """Records messages instead of calling the network. Used in tests and local dev without
    real Meta credentials configured.
    """

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    async def send(self, phone_number_id: str, access_token: str, message: OutboundMessage) -> None:
        self.sent.append(message)
