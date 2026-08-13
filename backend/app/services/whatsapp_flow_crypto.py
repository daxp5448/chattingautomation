"""Encryption/decryption for a WhatsApp Flow's data-exchange endpoint -- see Meta's
"Implementing your endpoint" guide (verified directly against the current docs before
writing this, not from memory): the request body carries an AES-128 key wrapped in RSA
(OAEP/SHA-256), plus a 128-bit IV, plus the actual payload encrypted with that AES key
(AES-128-GCM, auth tag appended to the ciphertext). The response is the same JSON payload
re-encrypted with the SAME AES key but an IV with every byte inverted (XOR 0xFF against the
request's IV) -- distinct from the request's own IV so neither direction reuses an
identical (key, IV) pair. Returned as a bare base64 string, not JSON-wrapped.

Used by app/api/v1/routers/webhook.py's Flow data-exchange endpoint and
app/services/whatsapp_flow_order_service.py. Health-check ("ping") and error-acknowledgment
requests are NOT encrypted -- that shape check happens in the webhook router, before this
module is ever called.
"""

import base64
import json
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class FlowDecryptionError(Exception):
    """Raised when a Flow data-exchange request can't be decrypted -- wrong/missing
    private key, malformed body, or a tampered/corrupted payload. The caller (webhook
    router) responds with a plain 421 per Meta's own guidance for this failure mode, not a
    500 -- Meta reacts to 421 by re-fetching the public key.
    """


def generate_keypair() -> tuple[str, str]:
    """Fresh RSA-2048 keypair for one restaurant's Flow endpoint (Meta requires one
    dedicated key pair per WABA -- see the approved plan's Context). Returns
    (private_key_pem, public_key_pem); the private key is encrypted at rest via
    encrypt_secret before storage, same bar as whatsapp_access_token_encrypted.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def decrypt_request(body: dict[str, Any], private_key_pem: str) -> tuple[dict[str, Any], bytes, bytes]:
    """Returns (decrypted_json, aes_key, iv). The caller must hold onto aes_key/iv to
    encrypt the matching response via encrypt_response below -- they're needed again, not
    just discarded after decrypting the request.
    """
    try:
        private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
        encrypted_aes_key = base64.b64decode(body["encrypted_aes_key"])
        iv = base64.b64decode(body["initial_vector"])
        encrypted_flow_data = base64.b64decode(body["encrypted_flow_data"])

        aes_key = private_key.decrypt(
            encrypted_aes_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        # AESGCM.decrypt expects ciphertext with the auth tag already appended -- exactly
        # the shape Meta sends, no manual splitting needed.
        plaintext = AESGCM(aes_key).decrypt(iv, encrypted_flow_data, None)
        return json.loads(plaintext), aes_key, iv
    except Exception as exc:
        raise FlowDecryptionError("Failed to decrypt Flow data-exchange request") from exc


def encrypt_response(data: dict[str, Any], aes_key: bytes, iv: bytes) -> str:
    inverted_iv = bytes(b ^ 0xFF for b in iv)
    ciphertext = AESGCM(aes_key).encrypt(inverted_iv, json.dumps(data).encode(), None)
    return base64.b64encode(ciphertext).decode()
