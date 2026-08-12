from sqlalchemy import select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def exists_any(self) -> bool:
        result = await self.session.execute(select(User.id).limit(1))
        return result.first() is not None

    async def get_by_setup_token_hash(self, token_hash: str) -> User | None:
        result = await self.session.execute(select(User).where(User.setup_token_hash == token_hash))
        return result.scalar_one_or_none()
