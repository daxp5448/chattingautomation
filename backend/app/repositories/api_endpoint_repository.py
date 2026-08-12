from app.models.api_endpoint import ApiEndpoint
from app.repositories.base import BaseRepository


class ApiEndpointRepository(BaseRepository[ApiEndpoint]):
    model = ApiEndpoint
