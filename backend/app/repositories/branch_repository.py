from app.models.branch import Branch
from app.repositories.base import BaseRepository


class BranchRepository(BaseRepository[Branch]):
    model = Branch
