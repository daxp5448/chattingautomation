from fastapi import Response

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse

# `secure` is only enforced in production because local dev runs over plain http, where a
# Secure cookie would silently never be sent by the browser.
_COOKIE_SECURE = settings.ENVIRONMENT == "production"

# Computed once at import time so the "user not found" / "inactive user" path pays the
# same bcrypt cost as a real password check below. Without this, an attacker can tell
# whether an email is registered purely from response timing (no-hash path is orders of
# magnitude faster than a bcrypt verify).
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-auth-checks")


async def authenticate(user_repo: UserRepository, email: str, password: str) -> User | None:
    user = await user_repo.get_by_email(email)
    if not user or not user.is_active:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def issue_tokens(user: User) -> TokenResponse:
    claims = {
        "role": user.role.value,
        "restaurant_id": str(user.restaurant_id) if user.restaurant_id else None,
        "email": user.email,
    }
    return TokenResponse(
        access_token=create_access_token(str(user.id), claims),
        refresh_token=create_refresh_token(str(user.id)),
    )


def set_auth_cookies(response: Response, tokens: TokenResponse) -> None:
    # The admin panel (browser) authenticates via httpOnly cookies instead of storing
    # tokens in localStorage/JS-readable state (localStorage is trivially readable by any
    # injected script -- an httpOnly cookie is not). Non-browser API clients (pytest,
    # smoke_test.py, scripts) keep using the Authorization: Bearer header, which every
    # response still also returns in the JSON body -- see app/core/deps.py::_resolve_token
    # for the fallback that accepts either. Shared by /auth/login, /auth/refresh, and
    # /signup/verify-otp (the only three places that ever establish a new session).
    response.set_cookie(
        "access_token",
        tokens.access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "refresh_token",
        tokens.refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
