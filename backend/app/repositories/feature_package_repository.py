from app.models.feature_package import FeaturePackage
from app.repositories.base import BaseRepository


class FeaturePackageRepository(BaseRepository[FeaturePackage]):
    model = FeaturePackage
