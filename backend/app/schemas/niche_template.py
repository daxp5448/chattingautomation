import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import EngagementType


class NicheTemplateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    action_type: EngagementType
    icon: str | None
    # Included directly on the summary (not just NicheTemplateFullRead) so the Super
    # Admin sidebar can resolve a business's terminology/module gating off the one
    # GET /niche-templates list call it already makes, without a second round trip per
    # page load just to read two small JSON fields -- see frontend/lib/restaurant.tsx.
    terminology: dict[str, Any]
    default_modules: dict[str, Any]
    default_personality: dict[str, Any]


class NichePublicSummary(BaseModel):
    """Unauthenticated niche picker for the public /signup page (see GET /signup/niches).
    Deliberately narrower than NicheTemplateSummary -- a stranger picking an industry needs
    just enough to render a picker, nothing about internal flow-engine configuration
    (no id, action_type, terminology, or module/personality defaults)."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    icon: str | None


class NicheCatalogItem(BaseModel):
    name: str
    description: str | None = None
    price: float | None = None
    price_type: str = "fixed"
    images: list[str] = []
    attributes: dict[str, Any] = {}


class NicheCatalogCategory(BaseModel):
    name: str
    icon_image: str | None = None
    items: list[NicheCatalogItem] = []


class NicheTemplateBase(BaseModel):
    name: str
    action_type: EngagementType
    icon: str | None = None
    welcome_message: str
    welcome_banner_image: str | None = None
    # Deliberately NOT exposing welcome_buttons here -- confirmed dead at runtime
    # (niche_provisioning.py never reads it; only default_flow_steps[entry_step_id]
    # .static_options drives a provisioned business's actual buttons). Editing it would
    # silently edit the wrong copy. See the approved plan's design-review findings.
    # Shape mirrors exactly what niche_provisioning.py reads (name/icon_image/items, each
    # item's name/description/price/price_type/images/attributes) -- validated here so a
    # malformed save is rejected immediately instead of KeyError-ing much later when a
    # real business is provisioned from this template.
    default_catalog: list[NicheCatalogCategory] = []
    default_flow_steps: list[dict[str, Any]] = []
    # Visual-builder node positions for default_flow_steps -- see
    # FlowDefinition.ui_layout's docstring for why this is separate from the steps above.
    default_ui_layout: dict[str, Any] = {}
    terminology: dict[str, Any] = {}
    default_modules: dict[str, Any] = {}
    default_personality: dict[str, Any] = {}


class NicheTemplateCreate(NicheTemplateBase):
    code: str


class NicheTemplateUpdate(BaseModel):
    name: str | None = None
    action_type: EngagementType | None = None
    icon: str | None = None
    welcome_message: str | None = None
    welcome_banner_image: str | None = None
    default_catalog: list[NicheCatalogCategory] | None = None
    default_flow_steps: list[dict[str, Any]] | None = None
    default_ui_layout: dict[str, Any] | None = None
    terminology: dict[str, Any] | None = None
    default_modules: dict[str, Any] | None = None
    default_personality: dict[str, Any] | None = None


class NicheTemplateFullRead(NicheTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    is_customized: bool
    created_at: datetime
    updated_at: datetime
