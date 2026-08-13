import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, OptionalCurrentUser
from app.core.rate_limit import limiter
from app.core.security import create_access_token, decode_token, hash_password, hash_setup_token
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SetupCompleteRequest,
    TokenResponse,
    UserCreate,
    UserRead,
)
from app.services.auth_service import authenticate, issue_tokens

router = APIRouter(prefix="/auth", tags=["auth"])

# Owners may only create staff accounts under their own restaurant -- not other owners
# or super admins, and not for a restaurant they don't belong to (enforced below).
_OWNER_CREATABLE_ROLES = {UserRole.MANAGER, UserRole.CASHIER, UserRole.KITCHEN}

# The admin panel (browser) authenticates via httpOnly cookies instead of storing tokens
# in localStorage/JS-readable state (localStorage is trivially readable by any injected
# script -- an httpOnly cookie is not). Non-browser API clients (pytest, smoke_test.py,
# scripts) keep using the Authorization: Bearer header, which every response here still
# also returns in the JSON body -- see app/core/deps.py::_resolve_token for the fallback
# that accepts either. `secure` is only enforced in production because local dev runs
# over plain http, where a Secure cookie would silently never be sent by the browser.
_COOKIE_SECURE = settings.ENVIRONMENT == "production"


def _set_auth_cookies(response: Response, tokens: TokenResponse) -> None:
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


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(request: Request, payload: UserCreate, db: DbSession, current_user: OptionalCurrentUser):
    repo = UserRepository(db)

    if await repo.exists_any():
        # Not the very first account on this deployment -- creating one now requires
        # being authenticated as a super_admin (any role/restaurant) or an owner (limited
        # to manager/cashier/kitchen accounts under their own restaurant). Without this,
        # anyone who can reach this endpoint could self-register as super_admin. This
        # authorization gate must run BEFORE the email-uniqueness check below: otherwise
        # an unauthenticated caller could probe arbitrary emails and learn which are
        # already registered purely from the 409-vs-not response, without ever passing
        # authorization.
        if current_user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
        if current_user.role == UserRole.SUPER_ADMIN:
            pass
        elif current_user.role == UserRole.OWNER:
            if payload.role not in _OWNER_CREATABLE_ROLES:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Owners can only create manager/cashier/kitchen accounts",
                )
            if payload.restaurant_id != current_user.restaurant_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create users for another business"
                )
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to create users")
    # else: this is the first account on a brand-new deployment -- allow it unauthenticated
    # so there's a bootstrap path (the CLI equivalent is app/seed.py).

    if await repo.get_by_email(payload.email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        restaurant_id=payload.restaurant_id,
        branch_id=payload.branch_id,
    )
    user = await repo.create(user)
    await repo.commit()
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, response: Response, payload: LoginRequest, db: DbSession):
    repo = UserRepository(db)
    user = await authenticate(repo, payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    tokens = issue_tokens(user)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("10/minute")
async def refresh(request: Request, response: Response, db: DbSession, payload: RefreshRequest = RefreshRequest()):
    raw_refresh_token = payload.refresh_token or request.cookies.get("refresh_token")
    if not raw_refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    try:
        claims = decode_token(raw_refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    repo = UserRepository(db)
    try:
        user_uuid = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc
    user = await repo.get(user_uuid)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    tokens = issue_tokens(user)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    # No server-side session/token-revocation store exists yet (see GOING_LIVE.md) -- this
    # clears the browser's copy of both cookies, which is sufficient for the normal
    # "sign out on this device" case. A stolen/leaked token from before logout remains
    # valid until it naturally expires, same as the pre-cookie bearer-token model.
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


@router.get("/me", response_model=UserRead)
async def me(current_user: CurrentUser) -> User:
    # The browser can't decode an httpOnly cookie's JWT payload client-side (that's the
    # point of httpOnly) -- it calls this instead, right after login and on every fresh
    # page load, to learn who's signed in.
    return current_user


@router.get("/ws-ticket")
async def ws_ticket(current_user: CurrentUser) -> dict[str, str]:
    """A WebSocket handshake can't carry an httpOnly cookie's value as a query param (the
    browser never exposes it to JS to put there), and browsers can't set custom headers
    on a WS upgrade request either -- so the live-updates socket (app/api/v1/routers/ws.py)
    still authenticates via `?token=`, same as before cookies existed. Rather than putting
    the real access token in a URL (query strings end up in proxy/access logs), this mints
    a purpose-built ticket: a normal access-type JWT but valid for 2 minutes instead of the
    usual session length, cookie-authenticated to request, used once to open one socket.
    """
    ticket = create_access_token(
        str(current_user.id),
        {
            "role": current_user.role.value,
            "restaurant_id": str(current_user.restaurant_id) if current_user.restaurant_id else None,
            "email": current_user.email,
        },
        expires_delta=timedelta(minutes=2),
    )
    return {"ticket": ticket}


@router.post("/setup", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("10/minute")
async def complete_setup(request: Request, payload: SetupCompleteRequest, db: DbSession):
    """Completes the one-time setup-token flow started by POST /restaurants (see
    app/core/security.py:generate_setup_token). The account created there has an
    hashed_password that can never match a real login, so this is the only way to make
    it usable -- the caller lands on /login next, this endpoint never issues tokens.
    """
    repo = UserRepository(db)
    token_hash = hash_setup_token(payload.token)
    user = await repo.get_by_setup_token_hash(token_hash)
    if (
        not user
        or not user.setup_token_expires_at
        or user.setup_token_expires_at < datetime.now(timezone.utc).replace(tzinfo=None)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired setup token")

    user.hashed_password = hash_password(payload.password)
    user.setup_token_hash = None
    user.setup_token_expires_at = None
    user.is_active = True
    await repo.commit()
