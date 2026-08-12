import hashlib
import hmac

from app.services.payment.razorpay import verify_webhook_signature


def test_valid_signature_accepted():
    secret = "whsec_test"
    body = b'{"event": "payment_link.paid"}'
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, signature, secret) is True


def test_invalid_signature_rejected():
    assert verify_webhook_signature(b"{}", "deadbeef", "whsec_test") is False


def test_missing_signature_rejected():
    assert verify_webhook_signature(b"{}", None, "whsec_test") is False


def test_missing_secret_rejected():
    assert verify_webhook_signature(b"{}", "some-signature", "") is False
