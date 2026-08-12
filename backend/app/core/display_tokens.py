"""Token generation/hashing for POS display device links.

Not a password: this is a bearer secret embedded in a URL that a kitchen/counter
browser tab reconnects with on every page load and WebSocket reconnect, so it needs a
fast, deterministic hash (SHA-256) rather than a slow KDF like bcrypt. The raw token is
shown to the owner exactly once at creation time; only the hash is ever persisted.
"""

import hashlib
import secrets


def generate_display_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). Only `token_hash` should ever be stored."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_display_token(raw_token)
    return raw_token, token_hash


def hash_display_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()
