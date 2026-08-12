"""Creates a demo tenant so the platform is exercisable end-to-end out of the box.

Run with: python -m app.seed
"""

import asyncio

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import AsyncSessionLocal
from app.models.branch import Branch
from app.models.category import Category
from app.models.enums import BranchStatus, RestaurantStatus, UserRole
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User


async def seed() -> None:
    if settings.ENVIRONMENT == "production":
        raise RuntimeError(
            "Refusing to run app.seed against a production environment: this creates "
            "demo data with known default credentials (admin@kelviontech.dev / "
            "ChangeMe123!). Only run this against local/dev/staging databases."
        )

    async with AsyncSessionLocal() as session:
        restaurant = Restaurant(
            name="Demo Restaurant",
            slug="demo-restaurant",
            support_number="+910000000000",
            email="owner@demo-restaurant.kelviontech.dev",
            currency="INR",
            timezone="Asia/Kolkata",
            delivery_charge=30,
            tax_settings={"gst_percent": 5},
            status=RestaurantStatus.ACTIVE,
            # Set this to your test number's phone_number_id once Meta credentials exist.
            whatsapp_phone_number_id="DEMO_PHONE_NUMBER_ID",
        )
        session.add(restaurant)
        await session.flush()

        branch = Branch(
            restaurant_id=restaurant.id,
            name="Main Branch",
            address="123 Demo Street",
            status=BranchStatus.OPEN,
            estimated_delivery_time_minutes=35,
        )
        session.add(branch)

        category = Category(restaurant_id=restaurant.id, name="Pizza", display_order=1)
        session.add(category)
        await session.flush()

        session.add_all(
            [
                Product(
                    restaurant_id=restaurant.id,
                    category_id=category.id,
                    name="Margherita Pizza",
                    price=299,
                    gst_percent=5,
                    is_veg=True,
                    tags=["popular"],
                ),
                Product(
                    restaurant_id=restaurant.id,
                    category_id=category.id,
                    name="Farmhouse Pizza",
                    price=399,
                    gst_percent=5,
                    is_veg=True,
                    tags=["chef_special"],
                ),
            ]
        )

        session.add(
            User(
                email="admin@kelviontech.dev",
                hashed_password=hash_password("ChangeMe123!"),
                full_name="Platform Admin",
                role=UserRole.SUPER_ADMIN,
            )
        )
        session.add(
            User(
                email="owner@demo-restaurant.kelviontech.dev",
                hashed_password=hash_password("ChangeMe123!"),
                full_name="Demo Owner",
                role=UserRole.OWNER,
                restaurant_id=restaurant.id,
            )
        )

        await session.commit()
        print(f"Seeded restaurant '{restaurant.name}' ({restaurant.id})")


if __name__ == "__main__":
    asyncio.run(seed())
