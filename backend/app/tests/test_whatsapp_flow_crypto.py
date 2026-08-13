"""Round-trip proof for whatsapp_flow_crypto.py -- the highest-risk new code in the
WhatsApp Flows work (real crypto, not just app logic). The "client" helpers below
independently reimplement Meta's documented encryption scheme rather than just calling our
own decrypt in reverse, so this actually proves interop with a correctly-behaving external
party, not merely self-consistency.
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.whatsapp_flow_crypto import (
    FlowDecryptionError,
    decrypt_request,
    encrypt_response,
    generate_keypair,
)


def _client_encrypt_request(public_key_pem: str, payload: dict) -> tuple[dict, bytes, bytes]:
    public_key = serialization.load_pem_public_key(public_key_pem.encode())
    aes_key = AESGCM.generate_key(bit_length=128)
    iv = b"\x11" * 16  # fixed for test determinism -- Meta uses a fresh random IV per real request
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


def _client_decrypt_response(response_b64: str, aes_key: bytes, iv: bytes) -> dict:
    inverted_iv = bytes(b ^ 0xFF for b in iv)
    ciphertext = base64.b64decode(response_b64)
    plaintext = AESGCM(aes_key).decrypt(inverted_iv, ciphertext, None)
    return json.loads(plaintext)


def test_generate_keypair_returns_valid_pem_pair():
    private_pem, public_pem = generate_keypair()
    assert "BEGIN PRIVATE KEY" in private_pem
    assert "BEGIN PUBLIC KEY" in public_pem


def test_full_round_trip_request_and_response():
    private_pem, public_pem = generate_keypair()
    request_payload = {"version": "3.0", "action": "data_exchange", "screen": "CATEGORY", "data": {"restaurant_id": "abc123"}}

    body, client_aes_key, client_iv = _client_encrypt_request(public_pem, request_payload)

    decrypted, server_aes_key, server_iv = decrypt_request(body, private_pem)
    assert decrypted == request_payload
    assert server_aes_key == client_aes_key
    assert server_iv == client_iv

    response_payload = {"screen": "ITEM", "data": {"items": ["Gold Necklace", "Gold Bangles"]}}
    encrypted_response = encrypt_response(response_payload, server_aes_key, server_iv)

    decrypted_response = _client_decrypt_response(encrypted_response, client_aes_key, client_iv)
    assert decrypted_response == response_payload


def test_decrypt_request_wrong_private_key_raises():
    _, public_pem = generate_keypair()
    wrong_private_pem, _ = generate_keypair()  # a different, unrelated keypair
    body, _, _ = _client_encrypt_request(public_pem, {"action": "ping"})

    with pytest.raises(FlowDecryptionError):
        decrypt_request(body, wrong_private_pem)


def test_decrypt_request_malformed_body_raises():
    private_pem, _ = generate_keypair()
    with pytest.raises(FlowDecryptionError):
        decrypt_request({"encrypted_flow_data": "not-base64!!", "encrypted_aes_key": "x", "initial_vector": "y"}, private_pem)


def test_decrypt_request_tampered_ciphertext_raises():
    """AES-GCM's auth tag must catch bit-flipped ciphertext, not silently decrypt garbage
    -- this is what actually makes GCM authenticated, not just confidential."""
    private_pem, public_pem = generate_keypair()
    body, _, _ = _client_encrypt_request(public_pem, {"action": "ping"})

    tampered = bytearray(base64.b64decode(body["encrypted_flow_data"]))
    tampered[0] ^= 0xFF
    body["encrypted_flow_data"] = base64.b64encode(bytes(tampered)).decode()

    with pytest.raises(FlowDecryptionError):
        decrypt_request(body, private_pem)
