from app.models.faq import FaqEntry
from app.repositories.base import BaseRepository


class FaqRepository(BaseRepository[FaqEntry]):
    model = FaqEntry
