from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class FeaturePackage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A Super-Admin-curated bundle of feature codes (see app/core/feature_registry.py for
    the fixed catalog they're drawn from) -- same "Super Admin curates, business consumes"
    pattern as NicheTemplate/ApiEndpoint. Assigning a package to a Restaurant SNAPSHOT-COPIES
    feature_codes into Restaurant.enabled_features at that moment (mirrors
    niche_provisioning.py's template->business copy) -- editing a package afterward never
    retroactively changes any restaurant already assigned to it. See
    app/core/deps.py::require_feature for how enabled_features is enforced, and
    Restaurant.enabled_features's own docstring for why NULL (not this package) is what a
    pre-existing/unassigned restaurant gets.
    """

    __tablename__ = "feature_packages"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000))
    feature_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # What a new business gets when Super Admin creates it without explicitly picking a
    # package -- see create_restaurant in app/api/v1/routers/restaurants.py. At most one
    # row should have this set; not DB-enforced (same trust level as the rest of this
    # Super-Admin-only table), the router just picks the first match if more than one is set.
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
