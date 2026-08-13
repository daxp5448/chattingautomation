"""End-to-end HTTP-level proof for POST /webhook/flow/{restaurant_id} -- the encrypted
data-exchange endpoint a real Flow session calls as the customer moves between screens.
Reuses the same independent client-side encrypt/decrypt helpers as
test_whatsapp_flow_crypto.py (not our own encrypt/decrypt in reverse) so this proves real
interop through the full HTTP+DB stack, not just unit-level self-consistency.
"""

import base64
import json
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.security import encrypt_secret
from app.services.whatsapp_flow_crypto import generate_keypair
from app.tests.test_niche_jewellers import CUSTOMER_PHONE, _get_category_id, jewellers_tenant


def _client_encrypt_request(public_key_pem: str, payload: dict) -> dict:
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    aes_key = AESGCM.generate_key(bit_length=128)
    iv = b"\x22" * 16
    ciphertext = AESGCM(aes_key).encrypt(iv, json.dumps(payload).encode(), None)
    encrypted_aes_key = public_key.encrypt(
        aes_key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    body = {
        "encrypted_flow_data": base64.b64encode(ciphertext).decode(),
        "encrypted_aes_key": base64.b64encode(encrypted_aes_key).decode(),
        "initial_vector": base64.b64encode(iv).decode(),
    }
    return body, aes_key, iv


def _client_decrypt_response(response_text: str, aes_key: bytes, iv: bytes) -> dict:
    inverted_iv = bytes(b ^ 0xFF for b in iv)
    ciphertext = base64.b64decode(response_text)
    plaintext = AESGCM(aes_key).decrypt(inverted_iv, ciphertext, None)
    return json.loads(plaintext)


async def test_ping_health_check_returns_plain_json_unencrypted(client):
    resp = await client.post(f"/api/v1/webhook/flow/{uuid.uuid4()}", json={"version": "3.0", "action": "ping"})
    assert resp.status_code == 200
    assert resp.json() == {"data": {"status": "active"}}


async def test_unconfigured_restaurant_returns_404(client, db_session, jewellers_tenant):
    body, _, _ = _client_encrypt_request(generate_keypair()[1], {"action": "data_exchange", "data": {}})
    resp = await client.post(f"/api/v1/webhook/flow/{jewellers_tenant.id}", json=body)
    assert resp.status_code == 404


async def test_wrong_public_key_used_returns_421(client, db_session, jewellers_tenant):
    private_pem, _public_pem = generate_keypair()
    jewellers_tenant.whatsapp_flow_private_key_encrypted = encrypt_secret(private_pem)
    await db_session.commit()

    _wrong_private_pem, unrelated_public_pem = generate_keypair()
    body, _, _ = _client_encrypt_request(unrelated_public_pem, {"action": "data_exchange", "data": {}})

    resp = await client.post(f"/api/v1/webhook/flow/{jewellers_tenant.id}", json=body)
    assert resp.status_code == 421


async def test_full_encrypted_round_trip_select_category(client, db_session, jewellers_tenant):
    private_pem, public_pem = generate_keypair()
    jewellers_tenant.whatsapp_flow_private_key_encrypted = encrypt_secret(private_pem)
    await db_session.commit()
    gold_category_id = await _get_category_id(db_session, jewellers_tenant.id, "Gold Jewellery")

    request_payload = {
        "version": "3.0", "action": "data_exchange", "screen": "CATEGORY_SCREEN",
        "data": {"action": "select_category", "category_id": gold_category_id},
        "flow_token": CUSTOMER_PHONE,
    }
    body, aes_key, iv = _client_encrypt_request(public_pem, request_payload)

    resp = await client.post(f"/api/v1/webhook/flow/{jewellers_tenant.id}", json=body)
    assert resp.status_code == 200, resp.text

    decrypted = _client_decrypt_response(resp.text, aes_key, iv)
    assert decrypted["screen"] == "ITEM_SCREEN"
    assert any(i["title"] == "Gold Necklace" for i in decrypted["data"]["items"])
