import uuid

from sqlalchemy import select

from app.models.display_device import DisplayDevice
from app.repositories.base import BaseRepository


class DisplayDeviceRepository(BaseRepository[DisplayDevice]):
    model = DisplayDevice

    async def get_active_by_token_hash(
        self, token_hash: str, restaurant_id: uuid.UUID
    ) -> DisplayDevice | None:
        stmt = select(DisplayDevice).where(
            DisplayDevice.token_hash == token_hash,
            DisplayDevice.restaurant_id == restaurant_id,
            DisplayDevice.revoked_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_token_hash_any_restaurant(self, token_hash: str) -> DisplayDevice | None:
        """Used by the WebSocket path, where the restaurant_id in the URL still needs
        to be validated against the token's own restaurant rather than trusted blindly."""
        stmt = select(DisplayDevice).where(
            DisplayDevice.token_hash == token_hash,
            DisplayDevice.revoked_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
