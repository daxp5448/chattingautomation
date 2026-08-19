from cachetools import TTLCache
from sqlalchemy import func, select

from app.models.enums import RestaurantStatus
from app.models.restaurant import Restaurant
from app.repositories.base import BaseRepository

# `get_by_whatsapp_phone_number_id` runs on every single inbound WhatsApp webhook -- at
# 50-100 tenant scale that's a hot, high-QPS lookup of a value that changes essentially
# never (only when a restaurant's WhatsApp number is reconfigured). A small in-process TTL
# cache avoids a DB round trip per webhook without needing a shared cache service for this
# scale. maxsize=500 comfortably covers the stated tenant count with headroom; ttl=60 is
# the hard backstop on staleness -- even if `invalidate_restaurant_cache` below is never
# called for some code path, a stale entry can live for at most 60 seconds.
_phone_number_id_cache: TTLCache = TTLCache(maxsize=500, ttl=60)


def invalidate_restaurant_cache(phone_number_id: str) -> None:
    """Must be called whenever a restaurant's `whatsapp_phone_number_id` changes (set,
    cleared, or reassigned) -- otherwise the webhook can keep routing to the old value (or
    fail to find the new one) for up to `ttl` seconds. See `routers/restaurants.py` /
    `update_restaurant` for where this needs to be wired in.
    """
    _phone_number_id_cache.pop(phone_number_id, None)


class RestaurantRepository(BaseRepository[Restaurant]):
    model = Restaurant

    async def get_by_slug(self, slug: str) -> Restaurant | None:
        result = await self.session.execute(select(Restaurant).where(Restaurant.slug == slug))
        return result.scalar_one_or_none()

    async def get_by_whatsapp_phone_number_id(self, phone_number_id: str) -> Restaurant | None:
        cached = _phone_number_id_cache.get(phone_number_id)
        if cached is not None:
            return cached

        result = await self.session.execute(
            select(Restaurant).where(Restaurant.whatsapp_phone_number_id == phone_number_id)
        )
        restaurant = result.scalar_one_or_none()
        if restaurant is not None:
            # Detach before caching: callers (the webhook handler) only ever read plain
            # column attributes off this object, never relationships or mutate it, so a
            # copy detached from *this* call's session -- and outliving it -- is safe to
            # hand back verbatim on future cache hits from other sessions.
            self.session.expunge(restaurant)
            _phone_number_id_cache[phone_number_id] = restaurant
        return restaurant

    async def platform_counts(self) -> dict:
        """Platform-wide business counts for the Super Admin Dashboard (see
        app/api/v1/routers/dashboard.py's /admin/platform-stats) -- excludes `is_demo`
        rows (showcase businesses, not real tenants) from every count, matching how the
        Businesses list already treats them as a distinct, badged category rather than a
        real business. One GROUP BY query for the niche breakdown, three plain counts for
        the rest -- small enough at this scale not to need combining into one round trip.
        """
        non_demo = Restaurant.is_demo.is_(False)
        total = (await self.session.execute(select(func.count(Restaurant.id)).where(non_demo))).scalar_one()
        active = (
            await self.session.execute(
                select(func.count(Restaurant.id)).where(non_demo, Restaurant.status == RestaurantStatus.ACTIVE)
            )
        ).scalar_one()
        connected_whatsapp = (
            await self.session.execute(
                select(func.count(Restaurant.id)).where(non_demo, Restaurant.whatsapp_phone_number_id.is_not(None))
            )
        ).scalar_one()
        niche_rows = (
            await self.session.execute(
                select(Restaurant.niche_type, func.count(Restaurant.id)).where(non_demo).group_by(Restaurant.niche_type)
            )
        ).all()
        return {
            "total": total,
            "active": active,
            "connected_whatsapp": connected_whatsapp,
            "by_niche": {(row[0] or "unassigned"): row[1] for row in niche_rows},
        }
