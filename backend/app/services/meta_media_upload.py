"""Uploads an image already stored locally (see image_storage_service.py) to Meta's
WhatsApp Media API, returning a media_id that can be sent as {"image": {"id": ...}}
(see whatsapp_client.py::OutboundMessage.image_by_id) instead of {"image": {"link": ...}}
-- Meta already has the bytes for an id-based send, so it skips the fetch-and-validate
step that makes a link-based image send measurably slower than a text/interactive one.

This module only ever uploads and returns an id (or None on any failure) -- it never
decides WHEN to upload or where to persist the result; see
generic_flow_engine.py::_render_jewellery_gallery for the caller that checks a cached id's
freshness, calls this on a miss/stale id, and persists the result onto the JewelleryDesign
row. Every caller must already have a `link`-based fallback ready regardless of what this
returns -- a failed upload here is a silent, logged no-op, never an exception a caller
needs to handle.
"""

import asyncio
import logging
import mimetypes

import httpx

from app.core.config import settings
from app.services import image_storage_service

logger = logging.getLogger(__name__)

# Standard asyncio "fire and forget" gotcha guard: a Task with no reference held anywhere
# can be garbage-collected mid-flight (silently, or with a "Task was destroyed but it is
# pending" warning) once the function that created it returns -- which is exactly what
# happens here, since _schedule_upload_and_cache returns immediately without awaiting the
# task it starts. Holding a reference in this module-level set (cleared via the
# done-callback once the task finishes either way) keeps it alive for its own natural
# lifetime without the caller needing to await or track it.
_background_tasks: set[asyncio.Task] = set()

# Meta's own documented guidance: an uploaded media id is not guaranteed to remain valid
# indefinitely. A safety margin under the commonly-observed ~30-day window, so a design
# gets re-uploaded a few days before an id might actually stop working, rather than after
# a send has already failed.
MEDIA_ID_FRESHNESS_DAYS = 25


async def upload_media(
    client: httpx.AsyncClient, phone_number_id: str, access_token: str, image_key_or_url: str,
) -> str | None:
    """Uploads an image to Meta via POST /{phone_number_id}/media and returns the new
    media_id, or None if anything about it fails (bad content, network error, Meta
    rejection) -- logged, never raised, since every caller already has a `link`-based
    fallback.

    `image_key_or_url` is either a relative storage key (e.g.
    "jewellery/gold/rings/gold_rings_001.jpg", read straight from local/S3 storage --
    never re-fetched over HTTP from our own public URL, since we already have the bytes)
    or a full "http(s)://..." URL (e.g. image_presenter.py's ItemImage.url, or a legacy
    CatalogItem.images plain-URL entry that never went through the Universal Image
    Processing Pipeline -- fetched over HTTP since there's no local key to read).
    """
    is_url = image_key_or_url.startswith("http://") or image_key_or_url.startswith("https://")
    try:
        if is_url:
            resp = await client.get(image_key_or_url, timeout=15.0)
            resp.raise_for_status()
            content = resp.content
        else:
            content = image_storage_service.download_bytes(image_key_or_url)
    except Exception:
        logger.warning("meta_media_upload: could not read %s", image_key_or_url, exc_info=True)
        return None

    content_type = mimetypes.guess_type(image_key_or_url)[0] or "image/jpeg"
    filename = image_key_or_url.rsplit("/", 1)[-1].split("?", 1)[0] or "image.jpg"

    url = f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_API_VERSION}/{phone_number_id}/media"
    try:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            data={"messaging_product": "whatsapp", "type": content_type},
            files={"file": (filename, content, content_type)},
            timeout=20.0,
        )
        response.raise_for_status()
    except httpx.HTTPError:
        logger.warning("meta_media_upload: upload failed for %s via phone_number_id=%s", image_key_or_url, phone_number_id, exc_info=True)
        return None

    media_id = response.json().get("id")
    if not media_id:
        logger.warning("meta_media_upload: Meta accepted the upload for %s but returned no id: %s", image_key_or_url, response.text[:500])
        return None
    return media_id


async def _run_background_upload(client: httpx.AsyncClient, phone_number_id: str, access_token: str, url: str, persist) -> None:
    """`client` is the caller's own persistent httpx.AsyncClient (GraphAPIWhatsAppSender's
    `_client` -- a real, process-lifetime client, safe to keep using after the request
    that scheduled this task has already returned) -- reused rather than opening a fresh
    one per background upload, same reasoning as why that client is persistent in the
    first place. `persist` is an async callable(session, media_id) that writes the result
    into whichever cache (JewelleryDesign's own inline columns, or the generic
    MetaMediaCache table) the caller owns -- called with a FRESH session, never the
    request's own (which is closed/gone by the time this runs, since the request already
    returned before this task's first `await` even gets a chance to run).
    """
    media_id = await upload_media(client, phone_number_id, access_token, url)
    if not media_id:
        return

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        await persist(session, media_id)
        await session.commit()


def schedule_background_upload(client: httpx.AsyncClient, phone_number_id: str, access_token: str, url: str, persist) -> None:
    """Fire-and-forget: the CURRENT send always goes out via `link` immediately (see
    _Engine._media_message / _design_image_message in generic_flow_engine.py) -- this
    only pre-warms the cache for NEXT time, entirely off the customer-facing send path.
    Unlike the webhook-level "return 200 instantly, process later" architecture the
    product owner explicitly declined earlier (that removes the per-customer FOR UPDATE
    lock protecting conversation state), this touches no conversation state at all and a
    failure here is silently a no-op -- worst case, the next send is exactly as fast as
    every send is today, never worse.
    """
    task = asyncio.create_task(_run_background_upload(client, phone_number_id, access_token, url, persist))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
