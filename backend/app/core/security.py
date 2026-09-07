import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_fernet = Fernet(settings.FIELD_ENCRYPTION_KEY.encode())


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(subject: str, expires_delta: timedelta, extra_claims: dict[str, Any] | None = None) -> str:
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode: dict[str, Any] = {"sub": subject, "exp": expire}
    if extra_claims:
        to_encode.update(extra_claims)
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    subject: str, extra_claims: dict[str, Any] | None = None, expires_delta: timedelta | None = None
) -> str:
    return _create_token(
        subject,
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        {"type": "access", **(extra_claims or {})},
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject,
        timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES),
        {"type": "refresh"},
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _fernet.decrypt(ciphertext.encode()).decode()


def hash_setup_token(raw_token: str) -> str:
    """A setup token isn't a password needing bcrypt's deliberate slowness -- it's a
    single-use, 32-byte random value that already has enormous entropy, so a fast,
    deterministic hash (for equality lookup by hash) is fine here."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_setup_token() -> tuple[str, str]:
    """Returns (raw_token, token_hash). The raw token is handed to the caller once (as
    part of a setup URL) and never stored; only its hash is persisted, so a database
    read can't be used to complete someone else's account setup."""
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_setup_token(raw_token)


def hash_otp(code: str) -> str:
    """Same reasoning as hash_setup_token: a 6-digit OTP has far less entropy than a
    32-byte token, but it's still short-lived and rate/attempt-capped (see
    POST /signup/verify-otp), so a fast deterministic hash is fine -- brute-force
    resistance is the attempt cap's job, not the hash's."""
    return hashlib.sha256(code.encode()).hexdigest()


def generate_otp() -> tuple[str, str]:
    """Returns (raw_code, code_hash) -- a 6-digit, zero-padded, CSPRNG numeric code (not
    random.random, which isn't safe for anything security-adjacent). The raw code is
    handed to the caller once (to email) and never stored; only its hash is persisted."""
    raw_code = f"{secrets.randbelow(1_000_000):06d}"
    return raw_code, hash_otp(raw_code)
