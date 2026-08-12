import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EngagementType


class FlowDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    niche_code: str
    action_type: EngagementType
    entry_step_id: str
    steps: list[dict[str, Any]]
    ui_layout: dict[str, Any]


class FlowStepsUpdate(BaseModel):
    """Full step-graph replacement -- the Drag & Drop Flow Builder's save action (Phase 2
    Item 3), distinct from HomeButtonsUpdate below (which only ever touches the entry
    step's button list)."""

    steps: list[dict[str, Any]]
    entry_step_id: str
    ui_layout: dict[str, Any] = {}


class HomeButtonInput(BaseModel):
    id: str
    title: str
    icon: str | None = None
    visible: bool = True
    destination_step_id: str


class HomeButtonsUpdate(BaseModel):
    buttons: list[HomeButtonInput] = Field(min_length=1)


class HomeButtonOutput(HomeButtonInput):
    pass


class HomeButtonsRead(BaseModel):
    entry_step_id: str
    buttons: list[HomeButtonOutput]
