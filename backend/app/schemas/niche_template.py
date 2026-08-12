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
    default_catalog: list[dict[str, Any]] = []
    default_flow_steps: list[dict[str, Any]] = []
    # Visual-builder node positions for default_flow_steps -- see
    # FlowDefinition.ui_layout's docstring for why this is separate from the steps above.
    default_ui_layout: dict[str, Any] = {}
    terminology: dict[str, Any] = {}
    default_modules: dict[str, Any] = {}


class NicheTemplateCreate(NicheTemplateBase):
    code: str


class NicheTemplateUpdate(BaseModel):
    name: str | None = None
    action_type: EngagementType | None = None
    icon: str | None = None
    welcome_message: str | None = None
    welcome_banner_image: str | None = None
    default_catalog: list[dict[str, Any]] | None = None
    default_flow_steps: list[dict[str, Any]] | None = None
    default_ui_layout: dict[str, Any] | None = None
    terminology: dict[str, Any] | None = None
    default_modules: dict[str, Any] | None = None


class NicheTemplateFullRead(NicheTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    is_customized: bool
    created_at: datetime
    updated_at: datetime
