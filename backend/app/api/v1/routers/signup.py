"""Public self-serve business signup: a stranger picks an industry, creates their own
account and business with no admin involved, verifies their email via a typed 6-digit OTP,
and lands auto-logged-in in a fully working dashboard immediately.

Kept deliberately separate from auth.py (narrow, bootstrap-or-admin-only) and
restaurants.py (POST /restaurants is SUPER_ADMIN-gated by design) so this genuinely
different trust boundary -- reachable by literally anyone -- is legible in its own file
rather than a stray public route hiding among admin-only ones.

The restaurant created here starts in RestaurantStatus.PENDING_REVIEW: the owner's
dashboard is fully usable right away (branches, menu, coupons, WhatsApp credentials, all of
it), but webhook.py's _BLOCKED_STATUSES keeps the WhatsApp bot itself silent until a Super
Admin approves (PATCH /restaurants/{id} with status=active -- no dedicated approve endpoint
needed, that one already audit-logs the transition and sends a status-change email).
"""

import hmac
import re
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.deps import DbSession
from app.core.rate_limit import limiter
from app.core.security import generate_otp, hash_otp, hash_password
from app.models.enums import RestaurantStatus, UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.repositories.restaurant_repository import RestaurantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import (
    ResendOtpRequest,
    ResendOtpResult,
    SignupRequest,
    SignupResult,
    TokenResponse,
    VerifyOtpRequest,
)
from app.schemas.niche_template import NichePublicSummary
from app.services.auth_service import issue_tokens, set_auth_cookies
from app.services.email_service import send_email
from app.services.niche_provisioning import provision_from_template

router = APIRouter(prefix="/signup", tags=["signup"])

_OTP_TTL = timedelta(minutes=10)
_OTP_MAX_ATTEMPTS = 5
_OTP_MAX_RESENDS = 5


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")
    return slug or "business"


async def _unique_slug(repo: RestaurantRepository, base: str) -> str:
    slug = base
    suffix = 1
    while await repo.get_by_slug(slug):
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


def _debug_otp(raw_code: str) -> str | None:
    # Mirrors the existing RestaurantCreateResult.setup_url convention (see
    # app/api/v1/routers/restaurants.py::create_restaurant) of returning an out-of-band
    # secret directly in the response outside production, so local/test flows work without
    # SMTP configured -- never populated once ENVIRONMENT == "production".
    return raw_code if settings.ENVIRONMENT != "production" else None


@router.get("/niches", response_model=list[NichePublicSummary])
@limiter.limit("30/minute")
async def list_public_niches(request: Request, db: DbSession):
    templates = await NicheTemplateRepository(db).list_all()
    return templates


@router.post("", response_model=SignupResult, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def signup(request: Request, payload: SignupRequest, db: DbSession):
    niche_repo = NicheTemplateRepository(db)
    template = await niche_repo.get_by_code(payload.niche_code)
    if template is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown niche_code '{payload.niche_code}'")

    user_repo = UserRepository(db)
    existing = await user_repo.get_by_email(payload.owner_email)
    if existing is not None:
        if existing.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
        # Unverified from a previous, abandoned signup attempt -- treat this as a resend
        # on the SAME restaurant/user rather than 409ing, so mistyping an OTP once doesn't
        # permanently strand someone who wants to retry with the same email.
        raw_otp, otp_hash = generate_otp()
        existing.otp_hash = otp_hash
        existing.otp_expires_at = datetime.utcnow() + _OTP_TTL
        existing.otp_attempts = 0
        existing.otp_resend_count += 1
        await db.commit()
        await send_email(payload.owner_email, "Verify your email", f"Your verification code is {raw_otp}. It expires in 10 minutes.")
        return SignupResult(
            restaurant_id=existing.restaurant_id, owner_email=payload.owner_email, debug_otp_code=_debug_otp(raw_otp)
        )

    restaurant_repo = RestaurantRepository(db)
    slug = await _unique_slug(restaurant_repo, _slugify(payload.business_name))

    restaurant = Restaurant(
        name=payload.business_name,
        slug=slug,
        status=RestaurantStatus.PENDING_REVIEW,
        # DEMO ONLY -- starts the "7 days free, then pay" demo clock automatically at
        # signup. See app/api/v1/routers/billing.py's module docstring. Timezone-aware
        # (unlike this file's naive otp_expires_at) to match Restaurant.trial_ends_at's
        # DateTime(timezone=True) column and the existing admin-panel write path
        # (frontend sends `new Date(...).toISOString()`).
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    restaurant = await restaurant_repo.create(restaurant)
    await db.flush()

    await provision_from_template(db, restaurant, template)

    raw_otp, otp_hash = generate_otp()
    owner = User(
        email=payload.owner_email,
        hashed_password=hash_password(payload.password),
        role=UserRole.OWNER,
        restaurant_id=restaurant.id,
        is_active=False,
        otp_hash=otp_hash,
        otp_expires_at=datetime.utcnow() + _OTP_TTL,
        otp_attempts=0,
        otp_resend_count=0,
    )
    await user_repo.create(owner)

    await AuditLogRepository(db).record(
        actor_id=None,
        restaurant_id=restaurant.id,
        action="signup_created",
        entity="restaurant",
        entity_id=str(restaurant.id),
        diff={"niche_code": payload.niche_code, "business_name": payload.business_name},
    )
    await restaurant_repo.commit()

    await send_email(payload.owner_email, "Verify your email", f"Your verification code is {raw_otp}. It expires in 10 minutes.")

    return SignupResult(restaurant_id=restaurant.id, owner_email=payload.owner_email, debug_otp_code=_debug_otp(raw_otp))


async def _get_pending_owner(db: DbSession, restaurant_id: uuid.UUID) -> User:
    owners = await UserRepository(db).list(restaurant_id=restaurant_id, role=UserRole.OWNER)
    if not owners:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending signup found for this business")
    return owners[0]


@router.post("/verify-otp", response_model=TokenResponse)
@limiter.limit("10/minute")
async def verify_otp(request: Request, response: Response, payload: VerifyOtpRequest, db: DbSession):
    user = await _get_pending_owner(db, payload.restaurant_id)

    if user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already verified -- please log in")
    if not user.otp_expires_at or user.otp_expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code expired -- request a new one")
    if user.otp_attempts >= _OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many incorrect attempts -- request a new code")

    if not user.otp_hash or not hmac.compare_digest(hash_otp(payload.code), user.otp_hash):
        user.otp_attempts += 1
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Incorrect code")

    user.is_active = True
    user.otp_hash = None
    user.otp_expires_at = None
    user.otp_attempts = 0
    user.otp_resend_count = 0
    await db.commit()

    tokens = issue_tokens(user)
    set_auth_cookies(response, tokens)
    return tokens


@router.post("/resend-otp", response_model=ResendOtpResult)
@limiter.limit("3/minute")
async def resend_otp(request: Request, payload: ResendOtpRequest, db: DbSession):
    user = await _get_pending_owner(db, payload.restaurant_id)

    if user.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Already verified -- please log in")
    if user.otp_resend_count >= _OTP_MAX_RESENDS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many resend requests -- please contact support")

    raw_otp, otp_hash = generate_otp()
    user.otp_hash = otp_hash
    user.otp_expires_at = datetime.utcnow() + _OTP_TTL
    user.otp_attempts = 0
    user.otp_resend_count += 1
    await db.commit()

    await send_email(user.email, "Your new verification code", f"Your verification code is {raw_otp}. It expires in 10 minutes.")

    return ResendOtpResult(sent=True, debug_otp_code=_debug_otp(raw_otp))
