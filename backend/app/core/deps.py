import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.repositories.user_repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _resolve_token(request: Request, header_token: str | None) -> str | None:
    """The browser admin panel authenticates via an httpOnly `access_token` cookie (set
    by POST /auth/login|/auth/refresh); the pytest suite, smoke_test.py, and any external
    API client authenticate via a plain `Authorization: Bearer` header. Accept either,
    preferring the header when both are present (keeps every existing bearer-token
    integration working unchanged) -- see GOING_LIVE.md for why cookies were added
    instead of replacing the header entirely.
    """
    return header_token or request.cookies.get("access_token")


async def get_current_user(
    request: Request, db: DbSession, header_token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    token = _resolve_token(request, header_token)
    if not token:
        raise credentials_exception
    try:
        payload = decode_token(token)
    except ValueError as exc:
        raise credentials_exception from exc
    if payload.get("type") != "access":
        raise credentials_exception
    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exception
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise credentials_exception from exc

    user = await UserRepository(db).get(user_uuid)
    if not user or not user.is_active:
        raise credentials_exception
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_user_optional(
    request: Request, db: DbSession, header_token: Annotated[str | None, Depends(oauth2_scheme)]
) -> User | None:
    """Same lookup as get_current_user, but returns None instead of raising 401 -- for
    the one endpoint (auth/register) that must work both for an authenticated caller
    creating a subordinate account and for the very first, unauthenticated bootstrap
    request on a brand-new deployment."""
    token = _resolve_token(request, header_token)
    if not token:
        return None
    try:
        payload = decode_token(token)
    except ValueError:
        return None
    if payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return None
    user = await UserRepository(db).get(user_uuid)
    if not user or not user.is_active:
        return None
    return user


OptionalCurrentUser = Annotated[User | None, Depends(get_current_user_optional)]


def require_roles(*roles: UserRole):
    async def _checker(user: CurrentUser) -> User:
        if user.role == UserRole.SUPER_ADMIN:
            return user
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _checker


def resolve_tenant_id(user: CurrentUser, restaurant_id: uuid.UUID | None = None) -> uuid.UUID:
    """Every tenant-scoped endpoint resolves its effective restaurant_id through this
    function: a super admin may target any restaurant explicitly, everyone else is
    locked to the restaurant on their own user record."""
    if user.role == UserRole.SUPER_ADMIN:
        if restaurant_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="restaurant_id is required")
        return restaurant_id
    if user.restaurant_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is not assigned to a restaurant")
    if restaurant_id is not None and restaurant_id != user.restaurant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another restaurant's data")
    return user.restaurant_id


def require_feature(code: str):
    """Gate an endpoint behind a Feature Package entitlement (see
    app/models/feature_package.py, app/core/feature_registry.py). Mirrors require_roles's
    factory shape and its super_admin-always-bypasses behavior. `restaurant_id` is picked
    up automatically from the path -- every router this is used on is already prefixed
    `/restaurants/{restaurant_id}/...`.

    Restaurant.enabled_features is None means "never assigned a package" and is treated as
    UNRESTRICTED (every gate passes) -- see that column's own docstring for why this has to
    be the default: every restaurant that predates this feature must be completely
    unaffected. Only a restaurant with a real (possibly empty) enabled_features list can
    ever be blocked by this.
    """

    async def _checker(user: CurrentUser, db: DbSession, restaurant_id: uuid.UUID) -> None:
        if user.role == UserRole.SUPER_ADMIN:
            return
        tenant_id = resolve_tenant_id(user, restaurant_id)
        restaurant = await db.get(Restaurant, tenant_id)
        if restaurant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
        if restaurant.enabled_features is not None and code not in restaurant.enabled_features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"'{code}' is not included in your plan -- contact support to upgrade.",
            )

    return _checker


def resolve_branch_scope(user: User, branch_id: uuid.UUID | None = None) -> uuid.UUID | None:
    """Resolves the branch filter a caller (a router) must apply to a branch-scoped query,
    given the branch recorded on the user's own account and an optional explicit
    `branch_id` the caller received from a query/path param.

    ## How to wire this into a router

    Call it right after `resolve_tenant_id`, passing along the same optional `branch_id`
    the endpoint accepts (add one if the endpoint doesn't have it yet):

        tenant_id = resolve_tenant_id(user, restaurant_id)
        effective_branch_id = resolve_branch_scope(user, branch_id)
        rows = await repo.list(restaurant_id=tenant_id, branch_id=effective_branch_id)

    `effective_branch_id` is either `None` (do not filter -- the caller is allowed to see
    every branch) or a concrete `uuid.UUID` the caller MUST filter its query by, e.g.
    `.where(Order.branch_id == effective_branch_id)`. (For a many-to-many table like
    `product_branch` where a row can also be assigned to *no* branch -- meaning
    "available at every branch" -- filter for "this branch OR no branch assigned" instead
    of an exact match; that's that table's own convention, not this function's.)

    ## Rules

    - owner / manager / super_admin are never branch-restricted: returns `branch_id`
      unchanged (`None` if the caller passed no filter, meaning "all branches"; the
      explicit id otherwise, since these roles may still choose to filter voluntarily,
      e.g. an owner viewing one branch's orders).
    - cashier / kitchen WITHOUT a `branch_id` on their user record are also unrestricted
      (there's nothing to scope them to) -- same behavior as above.
    - cashier / kitchen WITH a `branch_id` on their user record are locked to that one
      branch:
        - `branch_id` argument is `None` (caller applied no explicit filter) -> returns
          `user.branch_id`. The caller MUST apply this as an IMPLICIT filter so this staff
          member only ever sees their own branch's data, even from an endpoint whose
          contract doesn't otherwise take a branch_id param.
        - `branch_id` argument equals `user.branch_id` -> returns it unchanged.
        - `branch_id` argument differs from `user.branch_id` -> raises
          `HTTPException(403)`: this staff member may not access or filter by another
          branch.

    Raises:
        HTTPException(403): a branch-restricted cashier/kitchen user passed an explicit
            `branch_id` that isn't their own.
    """
    if user.role in (UserRole.CASHIER, UserRole.KITCHEN) and user.branch_id is not None:
        if branch_id is not None and branch_id != user.branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another branch's data"
            )
        return user.branch_id
    return branch_id
