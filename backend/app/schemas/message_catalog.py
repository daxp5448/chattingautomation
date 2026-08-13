from pydantic import BaseModel, Field


class MessageEntry(BaseModel):
    step_id: str
    field: str
    message_key: str
    text: str
    step_type: str
    # Only populated for a business's own flow messages (see flow_definitions.py) --
    # compares against the owning NicheTemplate's current text for this step_id.
    # None for niche-template-level entries, where there is no "parent default" above
    # the template itself other than the original seed file (see the restore-default
    # endpoint, which reads that directly rather than exposing it as a field here).
    is_customized: bool | None = None
    default_text: str | None = None


class MessageTextUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=4096)


class MessagePreviewRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    variables: dict[str, str] | None = None


class MessagePreviewResponse(BaseModel):
    rendered: str
