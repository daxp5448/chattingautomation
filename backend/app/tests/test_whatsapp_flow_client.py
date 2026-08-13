"""Request-shape proof for whatsapp_flow_client.py -- unlike whatsapp_template_client.py
(whose call sites are only ever tested by monkeypatching the whole function away), this
module gets direct httpx.MockTransport-level coverage because one of its endpoints
(register_public_key) is phone-number-scoped rather than WABA-scoped, a detail that's easy
to get backwards and was only confirmed by directly checking Meta's current docs while
writing it -- worth locking in as a real assertion, not just trusting the docstring.
"""

import json

import httpx
import pytest

from app.core.security import encrypt_secret
from app.models.restaurant import Restaurant
from app.services import whatsapp_flow_client


def _restaurant() -> Restaurant:
    return Restaurant(
        name="Flow Client Test Biz", slug="flow-client-test-biz",
        whatsapp_phone_number_id="PHONE_123", whatsapp_business_account_id="WABA_456",
        whatsapp_access_token_encrypted=encrypt_secret("test-token"),
    )


def _install_transport(monkeypatch, handler):
    original_client = httpx.AsyncClient

    def _client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(whatsapp_flow_client.httpx, "AsyncClient", _client)


async def test_register_public_key_hits_phone_number_scoped_endpoint(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"success": True})

    _install_transport(monkeypatch, handler)
    result = await whatsapp_flow_client.register_public_key(_restaurant(), "-----BEGIN PUBLIC KEY-----\nfake\n-----END PUBLIC KEY-----")

    assert result == {"success": True}
    assert "/PHONE_123/whatsapp_business_encryption" in captured["url"]
    assert "WABA_456" not in captured["url"]  # must NOT be WABA-scoped
    assert "business_public_key=" in captured["body"]


async def test_create_flow_hits_waba_scoped_endpoint_and_returns_id(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.read())
        return httpx.Response(200, json={"id": "999888777", "success": True, "validation_errors": []})

    _install_transport(monkeypatch, handler)
    flow_id = await whatsapp_flow_client.create_flow(_restaurant(), "kelviontech_order", ["OTHER"], "https://example.com/webhook/flow/abc")

    assert flow_id == "999888777"
    assert "/WABA_456/flows" in captured["url"]
    assert captured["payload"] == {"name": "kelviontech_order", "categories": ["OTHER"], "endpoint_uri": "https://example.com/webhook/flow/abc"}


async def test_upload_flow_json_raises_on_validation_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "validation_errors": [{"error": "MISSING_REQUIRED_PROPERTY"}]})

    _install_transport(monkeypatch, handler)
    with pytest.raises(ValueError, match="validation failed"):
        await whatsapp_flow_client.upload_flow_json(_restaurant(), "999888777", {"version": "5.1", "screens": []})


async def test_upload_flow_json_succeeds_with_no_validation_errors(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "validation_errors": []})

    _install_transport(monkeypatch, handler)
    result = await whatsapp_flow_client.upload_flow_json(_restaurant(), "999888777", {"version": "5.1", "screens": []})
    assert result["success"] is True


async def test_publish_flow_raises_on_4xx(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": "Blocked by Integrity", "code": 139000}})

    _install_transport(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await whatsapp_flow_client.publish_flow(_restaurant(), "999888777")


async def test_missing_credentials_raises_before_any_http_call(monkeypatch):
    called = []
    _install_transport(monkeypatch, lambda request: called.append(1) or httpx.Response(200, json={}))

    incomplete = Restaurant(name="No Creds", slug="no-creds-flow-client")
    with pytest.raises(ValueError, match="not configured"):
        await whatsapp_flow_client.create_flow(incomplete, "x", ["OTHER"], "https://example.com/webhook/flow/abc")
    assert called == []
