import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.customer import Customer
from app.repositories.base import BaseRepository


class CustomerRepository(BaseRepository[Customer]):
    model = Customer

    async def get_by_phone(self, restaurant_id: uuid.UUID, phone: str) -> Customer | None:
        stmt = select(Customer).where(Customer.restaurant_id == restaurant_id, Customer.phone == phone)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_tags(self, restaurant_id: uuid.UUID, tags: list[str], exclude_blocked: bool = True) -> list[Customer]:
        """Segment resolution for the Broadcast Module (see app/api/v1/routers/
        broadcasts.py). `Customer.tags` is a plain JSON column with no cross-dialect
        containment operator (tests run on SQLite, production on Postgres) -- filtered
        in Python rather than in SQL. Empty `tags` means "every non-blocked customer,"
        an explicit documented convention, not an accidental match-nothing/match-everything
        ambiguity. Fine up to a few thousand customers per restaurant; revisit with an
        indexed/JSONB approach if any tenant's customer list grows past that.
        """
        stmt = select(Customer).where(Customer.restaurant_id == restaurant_id)
        if exclude_blocked:
            stmt = stmt.where(Customer.is_blocked.is_(False))
        result = await self.session.execute(stmt)
        customers = list(result.scalars().all())
        if not tags:
            return customers
        tag_set = set(tags)
        return [c for c in customers if tag_set & set(c.tags)]

    async def get_or_create(self, restaurant_id: uuid.UUID, phone: str) -> Customer:
        customer = await self.get_by_phone(restaurant_id, phone)
        if customer:
            return customer
        customer = Customer(restaurant_id=restaurant_id, phone=phone)
        try:
            return await self.create(customer)
        except IntegrityError:
            # Lost the race: another concurrent request for this same (restaurant, phone)
            # committed its own row first, tripping the uq_customer_restaurant_phone
            # constraint. Roll back this failed insert and use the row that won instead of
            # propagating a 500 for what is, from the caller's point of view, a normal
            # get-or-create.
            await self.session.rollback()
            existing = await self.get_by_phone(restaurant_id, phone)
            if existing:
                return existing
            raise
