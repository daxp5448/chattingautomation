import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def _send_sync(to_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
    message["To"] = to_email
    message.set_content(body)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USERNAME:
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.send_message(message)


async def send_email(to_email: str, subject: str, body: str) -> None:
    """Best-effort -- every caller treats a failed/unconfigured send as a warning, never
    a reason to fail the request that triggered it (e.g. a restaurant still gets created
    even if SMTP isn't set up yet; the setup_url is also always returned in the API
    response so nothing is lost if the email never arrives).
    """
    if not settings.SMTP_HOST:
        logger.warning("SMTP_HOST is not configured; skipping email to %s (subject: %s)", to_email, subject)
        return
    try:
        # smtplib is synchronous; run it off the event loop so one slow/unreachable SMTP
        # server can't stall the request that triggered the send.
        await asyncio.to_thread(_send_sync, to_email, subject, body)
    except Exception:
        logger.warning("Failed to send email to %s (subject: %s)", to_email, subject, exc_info=True)
