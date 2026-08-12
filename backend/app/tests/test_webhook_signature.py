import hashlib
import hmac

from app.api.v1.routers.webhook import _verify_signature
from app.core.config import settings


def test_valid_signature_accepted():
    body = b'{"hello": "world"}'
    signature = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, f"sha256={signature}") is True


def test_invalid_signature_rejected():
    body = b'{"hello": "world"}'
    assert _verify_signature(body, "sha256=deadbeef") is False


def test_missing_signature_rejected():
    body = b'{"hello": "world"}'
    assert _verify_signature(body, None) is False


def test_missing_app_secret_allows_through(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_SECRET", "")
    assert _verify_signature(b"anything", None) is True
