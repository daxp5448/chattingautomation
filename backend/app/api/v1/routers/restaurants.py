import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, require_roles, resolve_tenant_id
from app.core.rate_limit import limiter
from app.core.security import encrypt_secret, generate_setup_token, hash_password
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.branch_repository import BranchRepository
from app.repositories.coupon_repository import CouponRepository
from app.repositories.customer_repository import CustomerRepository
from app.repositories.feature_package_repository import FeaturePackageRepository
from app.repositories.menu_repository import CategoryRepository, ProductRepository
from app.repositories.niche_template_repository import NicheTemplateRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.restaurant_repository import RestaurantRepository, invalidate_restaurant_cache
from app.repositories.user_repository import UserRepository
from app.services.niche_provisioning import provision_from_template
from app.schemas.audit_log import AuditLogRead
from app.schemas.branch import BranchRead
from app.schemas.coupon import CouponRead
from app.schemas.customer import CustomerRead
from app.schemas.menu import CategoryRead, ProductRead
from app.schemas.order import OrderRead
from app.schemas.restaurant import (
    DemoBotNicheStatus,
    DemoBotStatus,
    RestaurantCreate,
    RestaurantCreateResult,
    RestaurantListItem,
    RestaurantRead,
    RestaurantUpdate,
)
from app.services.email_service import send_email

router = APIRouter(prefix="/restaurants", tags=["restaurants"])


async def _unique_owner_email(user_repo: UserRepository, slug: str) -> str:
    base = f"owner-{slug}@kelviontech.dev"
    if not await user_repo.get_by_email(base):
        return base
    # Slug is unique per restaurant, so a collision here only happens if that exact
    # derived address was already registered through some other path -- fall back to a
    # short random suffix rather than failing the whole restaurant creation over it.
    return f"owner-{slug}-{secrets.token_hex(3)}@kelviontech.dev"


def build_owner_setup_user(email: str, restaurant_id: uuid.UUID) -> tuple[User, str]:
    """Reusable helper for provisioning a fresh owner login without ever generating or
    returning a plaintext password. Returns (unsaved User, setup_url) -- caller is
    responsible for persisting the User.

    The account's hashed_password is set to a hash of a random UUID it never learns and
    can never enter, so it simply can't authenticate via POST /auth/login until the
    owner completes POST /auth/setup with the token embedded in setup_url (valid for 48
    hours, single use).
    """
    raw_token, token_hash = generate_setup_token()
    owner = User(
        email=email,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.OWNER,
        restaurant_id=restaurant_id,
        is_active=False,
        setup_token_hash=token_hash,
        setup_token_expires_at=datetime.utcnow() + timedelta(hours=48),
    )
    setup_url = f"{settings.FRONTEND_URL}/setup?token={raw_token}"
    return owner, setup_url


def _status_change_email(restaurant_name: str, new_status: str) -> tuple[str, str]:
    if new_status == "active":
        return (
            f"{restaurant_name} is active again",
            f"Good news -- {restaurant_name}'s WhatsApp ordering bot is active again and taking orders.",
        )
    if new_status == "suspended":
        return (
            f"{restaurant_name} has been suspended",
            f"{restaurant_name}'s WhatsApp ordering bot has been temporarily suspended and is not taking "
            f"orders. Contact the platform team to reactivate it.",
        )
    return (
        f"{restaurant_name} has been cancelled",
        f"{restaurant_name}'s account on the platform has been cancelled and its WhatsApp ordering bot is "
        f"no longer taking orders. Your data hasn't been deleted -- contact the platform team if you'd "
        f"like to come back.",
    )


@router.post("", response_model=RestaurantCreateResult, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_restaurant(
    request: Request,
    payload: RestaurantCreate,
    db: DbSession,
    user: User = Depends(require_roles(UserRole.SUPER_ADMIN)),
):
    repo = RestaurantRepository(db)
    if await repo.get_by_slug(payload.slug):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already in use")

    niche_template = None
    if payload.niche_code:
        niche_template = await NicheTemplateRepository(db).get_by_code(payload.niche_code)
        if niche_template is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown niche_code '{payload.niche_code}'")

    # Explicit package if given, else whichever is is_default=True, else none -- either
    # way enabled_features is a SNAPSHOT of feature_codes taken right now, never a live
    # reference (see FeaturePackage's docstring). Leaving enabled_features at its column
    # default (None = unrestricted) when no package resolves is deliberate, not a gap --
    # matches every other pre-existing/unassigned restaurant.
    feature_package = None
    if payload.feature_package_id:
        feature_package = await FeaturePackageRepository(db).get(payload.feature_package_id)
        if feature_package is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown feature_package_id")
    else:
        defaults = await FeaturePackageRepository(db).list(is_default=True)
        feature_package = defaults[0] if defaults else None

    secret_fields = {"whatsapp_access_token", "razorpay_key_secret", "razorpay_webhook_secret", "owner_email", "niche_code"}
    data = payload.model_dump(exclude=secret_fields)
    restaurant = Restaurant(**data)
    if feature_package is not None:
        restaurant.feature_package_id = feature_package.id
        restaurant.enabled_features = list(feature_package.feature_codes)
    if payload.whatsapp_access_token:
        restaurant.whatsapp_access_token_encrypted = encrypt_secret(payload.whatsapp_access_token)
    if payload.razorpay_key_secret:
        restaurant.razorpay_key_secret_encrypted = encrypt_secret(payload.razorpay_key_secret)
    if payload.razorpay_webhook_secret:
        restaurant.razorpay_webhook_secret_encrypted = encrypt_secret(payload.razorpay_webhook_secret)
    restaurant = await repo.create(restaurant)
    await db.flush()

    if niche_template is not None:
        # Seeds this business's own catalog/flow rows from the template's defaults and
        # flips uses_generic_engine on -- see app/services/niche_provisioning.py. Never
        # touches any other business; existing (legacy) restaurants are unaffected.
        await provision_from_template(db, restaurant, niche_template)

    # One click = the restaurant AND its owner login both exist immediately: no separate
    # /auth/register step for whoever's onboarding a new restaurant onto the platform.
    user_repo = UserRepository(db)
    owner_email = payload.owner_email or await _unique_owner_email(user_repo, restaurant.slug)
    owner, setup_url = build_owner_setup_user(owner_email, restaurant.id)
    await user_repo.create(owner)
    await repo.commit()

    await send_email(
        owner_email,
        f"Set up your {restaurant.name} dashboard",
        f"You've been given access to manage {restaurant.name} on the WhatsApp ordering platform.\n\n"
        f"Set your password to get started:\n{setup_url}\n\n"
        f"This link expires in 48 hours and can only be used once.",
    )

    return RestaurantCreateResult(
        **RestaurantRead.model_validate(restaurant).model_dump(),
        owner_email=owner_email,
        setup_url=setup_url,
    )


@router.get("", response_model=list[RestaurantListItem])
async def list_restaurants(db: DbSession, user: User = Depends(require_roles(UserRole.SUPER_ADMIN))):
    repo = RestaurantRepository(db)
    # Demo Bot restaurants (see app/services/demo_bot_service.py) are internal
    # infrastructure, not real tenants -- excluded here so they never appear in, or skew
    # counts on, the Super-Admin businesses list.
    restaurants = await repo.list(is_demo=False)
    order_summary = await OrderRepository(db).summary_by_restaurant()
    return [
        RestaurantListItem(**RestaurantRead.model_validate(r).model_dump(), **order_summary.get(r.id, {}))
        for r in restaurants
    ]


@router.get("/demo-bot-status", response_model=DemoBotStatus)
async def get_demo_bot_status(db: DbSession, user: User = Depends(require_roles(UserRole.SUPER_ADMIN))):
    """Read-only status for the /niches page's 'Demo Bot' panel -- which niches have a
    demo restaurant provisioned (app/services/demo_restaurant_sync.py) and whether the
    one sentinel restaurant that owns the real demo WhatsApp number exists. Registered
    before GET /{restaurant_id} so it isn't swallowed by that path parameter.
    """
    templates = await NicheTemplateRepository(db).list_all()
    demo_restaurants = await RestaurantRepository(db).list(is_demo=True)
    demo_niche_codes = {r.niche_type for r in demo_restaurants if r.niche_type}
    sentinel_configured = any(r.whatsapp_phone_number_id for r in demo_restaurants)
    return DemoBotStatus(
        sentinel_configured=sentinel_configured,
        niches=[
            DemoBotNicheStatus(code=t.code, name=t.name, has_demo_restaurant=t.code in demo_niche_codes)
            for t in templates
        ],
    )


@router.get("/{restaurant_id}", response_model=RestaurantRead)
async def get_restaurant(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    repo = RestaurantRepository(db)
    restaurant = await repo.get(tenant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
    return restaurant


@router.patch("/{restaurant_id}", response_model=RestaurantRead)
@limiter.limit("30/minute")
async def update_restaurant(
    request: Request, restaurant_id: uuid.UUID, payload: RestaurantUpdate, db: DbSession, user: CurrentUser
):
    tenant_id = resolve_tenant_id(user, restaurant_id)
    if user.role not in (UserRole.SUPER_ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    repo = RestaurantRepository(db)
    restaurant = await repo.get(tenant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    old_phone_number_id = restaurant.whatsapp_phone_number_id

    secret_fields = {"whatsapp_access_token", "razorpay_key_secret", "razorpay_webhook_secret"}
    updates = payload.model_dump(exclude_unset=True, exclude=secret_fields)

    # Suspending/cancelling/reactivating a restaurant (and its trial date), and
    # reassigning its Feature Package, are subscription-management actions, not a
    # settings edit -- restricted to super_admin even though owners can otherwise PATCH
    # their own restaurant, so an owner can never un-suspend themselves, push out their
    # own trial deadline, or grant themselves a bigger feature set. enabled_features
    # itself is never in RestaurantUpdate at all -- only ever set by the re-snapshot
    # logic below, not directly PATCHable by anyone.
    subscription_fields = {"status", "trial_ends_at", "feature_package_id"}
    if subscription_fields & updates.keys() and user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a super admin can change subscription status")
    old_status = restaurant.status

    for field, value in updates.items():
        setattr(restaurant, field, value)

    if "feature_package_id" in updates:
        # Re-snapshot, not a live reference -- editing the package later still won't
        # retroactively change this restaurant (see FeaturePackage's docstring).
        new_package_id = updates["feature_package_id"]
        if new_package_id is None:
            restaurant.enabled_features = None
        else:
            new_package = await FeaturePackageRepository(db).get(new_package_id)
            if new_package is None:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown feature_package_id")
            restaurant.enabled_features = list(new_package.feature_codes)
    if payload.whatsapp_access_token is not None:
        restaurant.whatsapp_access_token_encrypted = encrypt_secret(payload.whatsapp_access_token)
    if payload.razorpay_key_secret is not None:
        restaurant.razorpay_key_secret_encrypted = encrypt_secret(payload.razorpay_key_secret)
    if payload.razorpay_webhook_secret is not None:
        restaurant.razorpay_webhook_secret_encrypted = encrypt_secret(payload.razorpay_webhook_secret)

    status_changed = "status" in updates and updates["status"] != old_status
    if status_changed:
        await AuditLogRepository(db).record(
            actor_id=user.id,
            restaurant_id=restaurant.id,
            action="status_change",
            entity="restaurant",
            entity_id=str(restaurant.id),
            diff={"from": old_status.value, "to": updates["status"].value},
        )

    await repo.commit()

    if status_changed:
        owners = await UserRepository(db).list(restaurant_id=restaurant.id, role=UserRole.OWNER)
        new_status = updates["status"].value
        subject, body = _status_change_email(restaurant.name, new_status)
        for owner_user in owners:
            await send_email(owner_user.email, subject, body)

    # The webhook hot path caches phone_number_id -> restaurant for 60s. A phone number
    # change obviously needs to invalidate it, but so does a status change: without this,
    # a just-suspended restaurant's bot could keep responding to customers for up to 60
    # more seconds off a stale cached "active" row.
    if "whatsapp_phone_number_id" in updates or "status" in updates:
        if old_phone_number_id:
            invalidate_restaurant_cache(old_phone_number_id)
        if restaurant.whatsapp_phone_number_id:
            invalidate_restaurant_cache(restaurant.whatsapp_phone_number_id)

    return restaurant


@router.get("/{restaurant_id}/audit-log", response_model=list[AuditLogRead])
async def get_audit_log(
    restaurant_id: uuid.UUID, db: DbSession, user: User = Depends(require_roles(UserRole.SUPER_ADMIN))
):
    return await AuditLogRepository(db).list_for_restaurant(restaurant_id)


@router.get("/{restaurant_id}/export")
async def export_restaurant_data(restaurant_id: uuid.UUID, db: DbSession, user: CurrentUser) -> dict:
    """A full JSON dump of everything this restaurant owns -- for an owner taking their
    data with them off the platform, or a manual backup before/after cancelling one.
    Available to the restaurant's own owner too (not just super_admin): it's their data.
    Excludes secrets (encrypted tokens/keys are already dropped by RestaurantRead) and
    the raw password/setup-token hashes on users (not included at all -- nothing here
    reads app.models.user beyond what UserRepository already scopes out).
    """
    tenant_id = resolve_tenant_id(user, restaurant_id)
    restaurant = await RestaurantRepository(db).get(tenant_id)
    if not restaurant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    branches = await BranchRepository(db).list(restaurant_id=tenant_id)
    categories = await CategoryRepository(db).list(restaurant_id=tenant_id)
    products = await ProductRepository(db).list(restaurant_id=tenant_id)
    coupons = await CouponRepository(db).list(restaurant_id=tenant_id)
    customers = await CustomerRepository(db).list(restaurant_id=tenant_id)
    orders = await OrderRepository(db).list_with_items(tenant_id)

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "restaurant": RestaurantRead.model_validate(restaurant).model_dump(mode="json"),
        "branches": [BranchRead.model_validate(b).model_dump(mode="json") for b in branches],
        "categories": [CategoryRead.model_validate(c).model_dump(mode="json") for c in categories],
        "products": [ProductRead.model_validate(p).model_dump(mode="json") for p in products],
        "coupons": [CouponRead.model_validate(c).model_dump(mode="json") for c in coupons],
        "customers": [CustomerRead.model_validate(c).model_dump(mode="json") for c in customers],
        "orders": [OrderRead.model_validate(o).model_dump(mode="json") for o in orders],
    }
